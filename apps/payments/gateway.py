"""HDFC SmartGateway REST client (Basic-auth flavour).

Two calls and one check:

* `create_session()`   POST /session      → hosted payment page URL
* `fetch_order()`      GET  /orders/{id}  → authoritative order status
* `check_webhook_auth()`                  → validates an inbound webhook

Deliberately stdlib-only (`urllib.request`), matching
`apps.notifications.msg91`. The Juspay Java SDK in the repo root uses the
JWE/JWS-signed flavour of the same API; this module implements the
Basic-auth flavour documented at
https://smartgateway.hdfcbank.com/docs/smartgateway-api-ref-basicauth/,
which needs no key material on disk.

Note the two directions of auth, which are unrelated:

* **Outbound** (us → bank) is `Authorization: Basic base64(api_key:)`.
* **Inbound** (bank → us) is a *separate* username/password pair set in
  the SmartGateway dashboard, replayed on each webhook as its own Basic
  header. SmartGateway does not sign webhook bodies, so unlike an
  HMAC gateway there is nothing to verify against the payload — the
  credentials are the whole of the authentication, which is why the
  receiver also re-fetches the order before trusting it.

Nothing here touches the database — see `services.py` for that.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.conf import settings

from .errors import PaymentGatewayError

#: SmartGateway caps order_id at 21 characters and rejects anything with
#: special characters in it.
ORDER_ID_MAX_LENGTH = 20
ORDER_ID_ALLOWED = re.compile(r"^[A-Za-z0-9]+$")

SANDBOX_BASE_URL = "https://smartgateway.hdfcuat.bank.in"
PRODUCTION_BASE_URL = "https://smartgateway.hdfc.bank.in"

#: Sent as the `version` header on order-status reads. Pinned so a
#: server-side default change can't silently reshape the response.
API_VERSION = "2023-06-30"

#: SmartGateway sits behind Cloudflare, which blocks the default
#: `Python-urllib/3.x` agent with a 1010 "Access denied" (403). A
#: browser-shaped UA gets us to the origin — same trick as the MSG91
#: client. (Fixed 2026-08: without this every /session + /orders call 403s.)
_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class SmartGatewayError(PaymentGatewayError):
    """Any non-2xx from SmartGateway, or a transport failure.

    Carries the gateway's own `error_code` / `error_message` when present
    so logs show the bank's reason rather than a bare status code.
    """


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

#: Settings without which the flow cannot work end to end. Each maps to
#: the concrete thing that breaks if it's blank.
REQUIRED_SETTINGS = {
    "SMARTGATEWAY_API_KEY": "no authentication for /session or /orders",
    "SMARTGATEWAY_MERCHANT_ID": "the x-merchantid header would be empty",
    "SMARTGATEWAY_CLIENT_ID": "payment_page_client_id would be empty",
    # Without this the pay link and return_url would be built off
    # FRONTEND_BASE_URL — the SPA host, not the API — producing a link
    # that 404s for every lead it is sent to.
    "SMARTGATEWAY_PUBLIC_BASE_URL": (
        "the pay link would point at the SPA host instead of this API"
    ),
}

#: Per-merchant fields. Each settlement account (see `routing.ACCOUNTS`)
#: may set its own in settings.SMARTGATEWAY_ACCOUNTS[key]; a blank one
#: falls back to the shared SMARTGATEWAY_<FIELD>. That covers both ways
#: HDFC may issue the additional TIDs: as separate merchant logins (own
#: credentials) or as one merchant routed by `gateway_reference_id`.
MERCHANT_FIELDS = (
    "api_key", "merchant_id", "client_id", "reseller_id", "response_key",
    "webhook_username", "webhook_password", "gateway_reference_id",
)


@dataclass(frozen=True)
class MerchantConfig:
    """The effective credentials for one settlement account.

    `account == ""` is the legacy single-merchant config, which requests
    raised before routing existed still use.
    """

    account: str
    live: bool
    api_key: str = ""
    merchant_id: str = ""
    client_id: str = ""
    reseller_id: str = ""
    response_key: str = ""
    webhook_username: str = ""
    webhook_password: str = ""
    gateway_reference_id: str = ""


def _account_overrides(account: str) -> dict:
    return (getattr(settings, "SMARTGATEWAY_ACCOUNTS", {}) or {}).get(account) or {}


def merchant_config(account: str = "") -> MerchantConfig:
    overrides = _account_overrides(account) if account else {}
    values = {
        field: (
            overrides.get(field)
            or getattr(settings, f"SMARTGATEWAY_{field.upper()}", "")
            or ""
        )
        for field in MERCHANT_FIELDS
    }
    if not account:
        # The legacy config never routes by reference id.
        values["gateway_reference_id"] = ""
    # An account is only live when explicitly marked so. Falling back to
    # the shared credentials must never, by itself, start settling (say)
    # Trust fees into whatever account the shared merchant pays out to.
    live = True if not account else bool(overrides.get("live"))
    return MerchantConfig(account=account, live=live, **values)


def configured_accounts() -> list[str]:
    """Account keys that have a SMARTGATEWAY_ACCOUNTS entry."""
    return list((getattr(settings, "SMARTGATEWAY_ACCOUNTS", {}) or {}).keys())


def missing_settings(account: str = "") -> list[str]:
    """Required settings that are unset. Empty means good to go.

    Separate from `is_enabled()` so callers can *report* why the gateway
    is inert rather than just falling back in silence — a half-filled
    .env is otherwise indistinguishable from a deliberate opt-out.
    """
    cfg = merchant_config(account)
    missing = []
    for name in REQUIRED_SETTINGS:
        if name == "SMARTGATEWAY_PUBLIC_BASE_URL":
            if not getattr(settings, name, ""):
                missing.append(name)
            continue
        field = name.removeprefix("SMARTGATEWAY_").lower()
        if not getattr(cfg, field):
            missing.append(
                f"SMARTGATEWAY_{account}_{field.upper()}" if account else name,
            )
    if account and not cfg.live:
        missing.append(f"SMARTGATEWAY_{account}_LIVE")
    return missing


def is_enabled(account: str = "") -> bool:
    """True when SmartGateway is switched on AND actually usable.

    Both halves matter: `SMARTGATEWAY_ENABLED` is the per-environment
    kill switch, but a half-filled .env must not send leads a broken
    link. Callers treat False as "fall back to UPI/bank instructions",
    which is always safe. With an `account`, that account must also be
    marked live.
    """
    if not getattr(settings, "SMARTGATEWAY_ENABLED", False):
        return False
    return not missing_settings(account)


def is_sandbox() -> bool:
    return bool(getattr(settings, "SMARTGATEWAY_SANDBOX", True))


def base_url() -> str:
    """Explicit override wins; otherwise the sandbox flag decides."""
    override = getattr(settings, "SMARTGATEWAY_BASE_URL", "") or ""
    if override:
        return override.rstrip("/")
    return SANDBOX_BASE_URL if is_sandbox() else PRODUCTION_BASE_URL


def _auth_header(cfg: MerchantConfig) -> str:
    """`Basic base64(api_key:)` — the API key as username, no password."""
    raw = f"{cfg.api_key}:".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _base_headers(cfg: MerchantConfig, customer_id: str = "") -> dict:
    headers = {
        "Authorization": _auth_header(cfg),
        "x-merchantid": cfg.merchant_id,
        "Accept": "application/json",
        "User-Agent": _BROWSER_UA,
    }
    if cfg.reseller_id:
        headers["x-resellerid"] = cfg.reseller_id
    if customer_id:
        headers["x-customerid"] = customer_id
    return headers


# ---------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------

def format_amount(amount) -> str:
    """Rupees → the stringified 2dp value SmartGateway expects.

    Refuses a value that isn't a whole number of paise rather than
    rounding it: rounding here means charging a student the wrong amount.
    """
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, TypeError) as e:
        raise SmartGatewayError(f"Amount {amount!r} is not a number.") from e

    quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if quantized != value:
        raise SmartGatewayError(
            f"Amount {amount} is not a whole number of paise.",
        )
    if quantized <= Decimal("0.00"):
        raise SmartGatewayError(f"Amount {amount} must be positive.")
    return f"{quantized:.2f}"


def validate_order_id(order_id: str) -> str:
    """Enforce SmartGateway's order_id rules before we spend a round trip."""
    if not order_id or len(order_id) > ORDER_ID_MAX_LENGTH:
        raise SmartGatewayError(
            f"order_id {order_id!r} must be 1–{ORDER_ID_MAX_LENGTH} "
            f"characters.",
        )
    if not ORDER_ID_ALLOWED.match(order_id):
        raise SmartGatewayError(
            f"order_id {order_id!r} must be alphanumeric — SmartGateway "
            f"rejects special characters.",
        )
    return order_id


def normalise_phone(phone: str) -> str:
    """Last 10 digits — SmartGateway wants the number without +91.

    Returns "" when there aren't 10 digits to give, since the field is
    optional and a malformed one is worse than an absent one.
    """
    digits = re.sub(r"\D", "", phone or "")
    return digits[-10:] if len(digits) >= 10 else ""


# ---------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------

def _request(
    method: str, path: str, *, cfg: MerchantConfig,
    payload: dict | None = None,
    customer_id: str = "", extra_headers: dict | None = None,
) -> dict:
    url = f"{base_url()}/{path.lstrip('/')}"
    headers = _base_headers(cfg, customer_id)
    headers.update(extra_headers or {})

    data = None
    if payload is not None:
        # UAT's /session rejects form-encoded bodies with 415 and only
        # accepts JSON (verified 2026-08 against smartgateway.hdfcuat).
        # JSON also carries nested keys (udf/metadata) cleanly.
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    timeout = getattr(settings, "SMARTGATEWAY_TIMEOUT", 20)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        code = message = ""
        try:
            parsed = json.loads(err_body)
            code = str(parsed.get("error_code", "") or "")
            message = str(
                parsed.get("error_message")
                or parsed.get("message")
                or "",
            )
        except Exception:
            pass
        raise SmartGatewayError(
            message or f"HTTP {e.code}: {e.reason}",
            status=e.code, body=err_body, error_code=code,
        ) from e
    except Exception as e:
        raise SmartGatewayError(f"{type(e).__name__}: {e}") from e


# ---------------------------------------------------------------------
# Session API
# ---------------------------------------------------------------------

def create_session(
    *,
    order_id: str,
    amount,
    customer_id: str,
    return_url: str,
    customer_email: str = "",
    customer_phone: str = "",
    first_name: str = "",
    last_name: str = "",
    description: str = "",
    currency: str = "INR",
    udf: dict | None = None,
    account: str = "",
) -> dict:
    """Create a payment-page session; returns SmartGateway's response.

    The useful bit is `payment_links.web` — the hosted page we redirect
    the payer to — and `payment_links.expiry`, which is why we mint these
    on demand rather than at SMS-send time.

    Raises `SmartGatewayError` on anything other than success.
    """
    validate_order_id(order_id)
    cfg = merchant_config(account)

    payload = {
        "order_id": order_id,
        "amount": format_amount(amount),
        "customer_id": customer_id,
        "payment_page_client_id": cfg.client_id,
        "action": "paymentPage",
        "return_url": return_url,
        "currency": currency,
    }
    if customer_email:
        payload["customer_email"] = customer_email
    phone = normalise_phone(customer_phone)
    if phone:
        payload["customer_phone"] = phone
    if first_name:
        payload["first_name"] = first_name[:64]
    if last_name:
        payload["last_name"] = last_name[:64]
    if description:
        payload["description"] = description[:200]
    for key, value in (udf or {}).items():
        payload[key] = str(value)
    if cfg.gateway_reference_id:
        # Juspay's flat key for "route this order to the PG account mapped
        # to this reference id in PG Control Centre". Case-sensitive, and a
        # value the dashboard doesn't know leaves the order stuck STARTED.
        payload["metadata.JUSPAY:gateway_reference_id"] = (
            cfg.gateway_reference_id
        )

    return _request(
        "POST", "/session", cfg=cfg, payload=payload, customer_id=customer_id,
    )


def fetch_order(
    order_id: str, *, customer_id: str = "", account: str = "",
) -> dict:
    """GET /orders/{order_id} — the authoritative status.

    Used both to reconcile a missing webhook and to re-check an order
    after a webhook arrives, since SmartGateway webhooks are authenticated
    by shared credentials rather than a signature over the body.
    """
    validate_order_id(order_id)
    return _request(
        "GET", f"/orders/{urllib.parse.quote(order_id)}",
        cfg=merchant_config(account),
        customer_id=customer_id,
        extra_headers={"version": API_VERSION},
    )


# ---------------------------------------------------------------------
# Inbound webhook authentication
# ---------------------------------------------------------------------

def _php_urlencode(value: str) -> str:
    """Python equivalent of PHP's `urlencode()`.

    The reference implementation is PHP, so the encoding has to match it
    byte for byte or the HMAC won't. Differences from `quote_plus`'s
    defaults: space becomes `+`, and `~` IS encoded (PHP 5.3+).
    """
    return urllib.parse.quote_plus(str(value), safe="").replace("~", "%7E")


def signature_payload(params: dict) -> str:
    """The exact string SmartGateway signs, per the reference PHP:

        ksort($params)
        foreach: $s .= urlencode($k)."=".urlencode($v)."&"
        $s = urlencode(rtrim($s, "&"))

    Note the double encoding — each key and value is encoded, the pairs
    are joined, and then the WHOLE string is encoded again. Missing that
    second pass is the usual reason a correct-looking implementation
    never validates.
    """
    joined = "&".join(
        f"{_php_urlencode(key)}={_php_urlencode(params[key])}"
        for key in sorted(params)
    )
    return _php_urlencode(joined)


def verify_return_signature(params: dict, account: str = "") -> bool:
    """Validate the HMAC signature on SmartGateway's return_url params.

    SmartGateway redirects the payer back with something like

        ?order_id=AF1N01&status=CHARGED&status_id=21
        &signature=euKz...%3D&signature_algorithm=HMAC-SHA256

    signed with the merchant's RESPONSE_KEY (a different secret again
    from the API key and the webhook credentials). `signature` and
    `signature_algorithm` are excluded from the signed set.

    Returns False when the key isn't configured — fail closed, same as
    the webhook credentials.
    """
    response_key = merchant_config(account).response_key
    if not response_key:
        return False

    received = params.get("signature") or ""
    if not received:
        return False

    algorithm = (params.get("signature_algorithm") or "HMAC-SHA256").upper()
    if algorithm != "HMAC-SHA256":
        # Only the one algorithm is documented; anything else is either a
        # gateway change we must notice or someone probing.
        return False

    signed_params = {
        k: v for k, v in params.items()
        if k not in ("signature", "signature_algorithm")
    }
    if not signed_params:
        return False

    digest = hmac.new(
        response_key.encode("utf-8"),
        signature_payload(signed_params).encode("utf-8"),
        hashlib.sha256,
    ).digest()
    computed = base64.b64encode(digest).decode("ascii")

    # The reference implementations compare after urldecoding BOTH sides,
    # so mirror that rather than comparing raw base64 — `+` in a digest
    # would otherwise never match a value that arrived as a space.
    return hmac.compare_digest(
        urllib.parse.unquote_plus(computed),
        urllib.parse.unquote_plus(received),
    )


def check_webhook_auth(authorization_header: str) -> bool:
    """Validate the Basic credentials SmartGateway replays to us.

    Configured in the SmartGateway dashboard as a username/password pair
    and sent as an ordinary `Authorization: Basic` header. Compared with
    `hmac.compare_digest` so a wrong guess can't be timed out character by
    character. Fails closed when either side is unset.

    With separate merchants each dashboard may hold its own pair, so any
    configured account's credentials are accepted. That is safe because
    the webhook only ever triggers a re-read of the order, and that
    re-read uses the order's own account.
    """
    pairs = {
        (cfg.webhook_username, cfg.webhook_password)
        for cfg in (
            merchant_config(""),
            *(merchant_config(a) for a in configured_accounts()),
        )
        if cfg.webhook_username and cfg.webhook_password
    }
    if not pairs:
        return False

    header = (authorization_header or "").strip()
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return False
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except Exception:
        return False

    username, sep, password = decoded.partition(":")
    if not sep:
        return False
    ok = False
    for expected_user, expected_pass in pairs:
        # Both compared, and always both, so the timing doesn't leak which
        # half was wrong.
        user_ok = hmac.compare_digest(username, expected_user)
        pass_ok = hmac.compare_digest(password, expected_pass)
        ok = ok or (user_ok and pass_ok)
    return ok
