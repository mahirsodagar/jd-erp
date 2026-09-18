"""Razorpay Payment Links client — JDSD's application fee.

Why Payment Links rather than Standard Checkout: our fee link goes out by
SMS and is opened days later on a phone, with no page of ours to host
Razorpay's JS. A Payment Link is a hosted page minted server-side, so it
drops into the flow SmartGateway already uses:

    PaymentRequest (token in the SMS)
        └── PaymentOrder  == one Razorpay payment link, minted on click

`PaymentOrder.order_id` is sent as the link's `reference_id` and
`PaymentOrder.sg_order_ref` holds the `plink_…` id.

Three calls and two checks:

* `create_payment_link()`        POST /v1/payment_links
* `fetch_payment_link()`         GET  /v1/payment_links/{id}
* `normalise_link()`             link body → the order-body shape
                                 `services.apply_order_body` understands
* `verify_callback_signature()`  the redirect back to our callback_url
* `verify_webhook_signature()`   X-Razorpay-Signature on a webhook

Unlike SmartGateway, Razorpay *does* sign webhook bodies (HMAC-SHA256
with the dashboard's webhook secret). We still re-read the link before
settling, so every path settles from the API's answer.

Docs: https://razorpay.com/docs/api/payments/payment-links/
Stdlib-only, matching `gateway.py` and `apps.notifications.msg91`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone as dt_timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.conf import settings

from .errors import PaymentGatewayError

BASE_URL = "https://api.razorpay.com/v1"

_USER_AGENT = "jd-erp/1.0 (+payments)"

#: Razorpay link status → our PaymentOrder status vocabulary.
LINK_STATUS_MAP = {
    "created": "NEW",
    "partially_paid": "STARTED",
    "paid": "CHARGED",
    "expired": "EXPIRED",
    "cancelled": "CANCELLED",
}

#: Razorpay payment `method` → our payment_method_type, which
#: `services._payment_mode` reads (only UPI is distinguished there).
METHOD_TYPE_MAP = {
    "upi": "UPI",
    "card": "CARD",
    "netbanking": "NB",
    "wallet": "WALLET",
    "emi": "CARD",
    "cardless_emi": "EMI",
    "paylater": "PAYLATER",
}


class RazorpayError(PaymentGatewayError):
    """Any non-2xx from Razorpay, or a transport failure."""


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

REQUIRED_SETTINGS = {
    "RAZORPAY_KEY_ID": "no authentication for the Payment Links API",
    "RAZORPAY_KEY_SECRET": "no authentication, and callbacks can't be verified",
    "SMARTGATEWAY_PUBLIC_BASE_URL": (
        "the pay link and callback_url would have no public host"
    ),
}


def missing_settings() -> list[str]:
    return [n for n in REQUIRED_SETTINGS if not getattr(settings, n, "")]


def is_enabled() -> bool:
    """Switched on (`RAZORPAY_ENABLED`) and fully configured."""
    if not getattr(settings, "RAZORPAY_ENABLED", False):
        return False
    return not missing_settings()


def is_test_mode() -> bool:
    return str(getattr(settings, "RAZORPAY_KEY_ID", "")).startswith("rzp_test_")


def _auth_header() -> str:
    raw = f"{settings.RAZORPAY_KEY_ID}:{settings.RAZORPAY_KEY_SECRET}"
    return "Basic " + base64.b64encode(raw.encode("utf-8")).decode("ascii")


# ---------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------

def to_paise(amount) -> int:
    """Rupees → integer paise. Refuses sub-paise values rather than
    rounding them, same rule as SmartGateway's `format_amount`."""
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, TypeError) as e:
        raise RazorpayError(f"Amount {amount!r} is not a number.") from e
    if value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) != value:
        raise RazorpayError(f"Amount {amount} is not a whole number of paise.")
    if value < Decimal("1.00"):
        # Razorpay's floor for a payment link is ₹1.
        raise RazorpayError(f"Amount {amount} is below Razorpay's ₹1 minimum.")
    return int(value * 100)


def _contact(phone: str) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    return f"+91{digits[-10:]}" if len(digits) >= 10 else ""


def _iso(ts) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(int(ts), tz=dt_timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return ""


# ---------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------

def _request(method: str, path: str, *, payload: dict | None = None) -> dict:
    url = f"{BASE_URL}/{path.lstrip('/')}"
    headers = {
        "Authorization": _auth_header(),
        "Accept": "application/json",
        "User-Agent": _USER_AGENT,
    }
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    timeout = getattr(settings, "RAZORPAY_TIMEOUT", 20)
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
            err = json.loads(err_body).get("error") or {}
            code = str(err.get("code") or "")
            message = str(err.get("description") or "")
        except Exception:
            pass
        raise RazorpayError(
            message or f"HTTP {e.code}: {e.reason}",
            status=e.code, body=err_body, error_code=code,
        ) from e
    except Exception as e:
        raise RazorpayError(f"{type(e).__name__}: {e}") from e


# ---------------------------------------------------------------------
# Payment Links API
# ---------------------------------------------------------------------

def create_payment_link(
    *,
    reference_id: str,
    amount,
    callback_url: str,
    description: str = "",
    customer_name: str = "",
    customer_email: str = "",
    customer_phone: str = "",
    expire_by: datetime | None = None,
    notes: dict | None = None,
    currency: str = "INR",
) -> dict:
    """Mint a hosted payment link; `short_url` is where the payer goes.

    Razorpay's own SMS/email notifications are switched off — the lead
    already has our link, and a second message from an unfamiliar
    sender reads like phishing.
    """
    if not reference_id or len(reference_id) > 40:
        raise RazorpayError(f"reference_id {reference_id!r} must be 1–40 chars.")

    payload = {
        "amount": to_paise(amount),
        "currency": currency,
        "accept_partial": False,
        "reference_id": reference_id,
        "description": (description or "")[:2048],
        "notify": {"sms": False, "email": False},
        "reminder_enable": False,
        "callback_url": callback_url,
        "callback_method": "get",
        "notes": {k: str(v)[:256] for k, v in (notes or {}).items()},
    }
    customer = {}
    if customer_name:
        customer["name"] = customer_name[:100]
    if customer_email:
        customer["email"] = customer_email
    contact = _contact(customer_phone)
    if contact:
        customer["contact"] = contact
    if customer:
        payload["customer"] = customer
    if expire_by is not None:
        payload["expire_by"] = int(expire_by.timestamp())

    try:
        return _request("POST", "/payment_links", payload=payload)
    except RazorpayError as e:
        # Razorpay validates prefill hard ("Recurring digits in customer
        # contact are disallowed" for 9999999999, malformed emails…) and
        # leads carry plenty of junk. The prefill is a convenience, so a
        # bad one must not cost the payment: retry once without it.
        if e.status == 400 and "customer" in payload and "customer" in str(e).lower():
            payload.pop("customer")
            return _request("POST", "/payment_links", payload=payload)
        raise


def fetch_payment_link(link_id: str) -> dict:
    """GET /v1/payment_links/{id} — the authoritative status."""
    if not link_id:
        raise RazorpayError("No Razorpay payment link id to fetch.")
    return _request("GET", f"/payment_links/{urllib.parse.quote(link_id)}")


def cancel_payment_link(link_id: str) -> dict:
    """POST /v1/payment_links/{id}/cancel — so a superseded link can't be
    paid. Razorpay refuses this for a link already paid or expired."""
    if not link_id:
        raise RazorpayError("No Razorpay payment link id to cancel.")
    return _request(
        "POST", f"/payment_links/{urllib.parse.quote(link_id)}/cancel",
        payload={},
    )


def normalise_link(link: dict) -> dict:
    """A payment-link body in the order-body shape `apply_order_body` reads.

    Keeps settlement in one place: the webhook, the callback and the
    reconcile command all end in `apply_order_body`, whichever gateway
    the money came through.
    """
    status = LINK_STATUS_MAP.get(str(link.get("status") or "").lower(), "")
    payments = link.get("payments") or []
    captured = [
        p for p in payments
        if str(p.get("status") or "").lower() == "captured"
    ]
    payment = (captured or payments or [{}])[-1]
    method = str(payment.get("method") or "").lower()

    body = {
        "id": link.get("id") or "",
        "status": status,
        "txn_id": payment.get("payment_id") or "",
        "payment_method": method.upper(),
        "payment_method_type": METHOD_TYPE_MAP.get(method, method.upper()),
    }
    paid_at = _iso(payment.get("created_at") if captured else None)
    if paid_at:
        body["date_created"] = paid_at
    return body


# ---------------------------------------------------------------------
# Signatures
# ---------------------------------------------------------------------

def _hmac_hex(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_callback_signature(params: dict) -> bool:
    """Validate the params Razorpay appends to callback_url.

        signature = HMAC_SHA256(
            link_id|reference_id|link_status|payment_id, key_secret)

    Fails closed when anything is missing.
    """
    secret = getattr(settings, "RAZORPAY_KEY_SECRET", "")
    received = params.get("razorpay_signature") or ""
    parts = [
        params.get("razorpay_payment_link_id"),
        params.get("razorpay_payment_link_reference_id"),
        params.get("razorpay_payment_link_status"),
        params.get("razorpay_payment_id"),
    ]
    if not secret or not received or not all(parts):
        return False
    expected = _hmac_hex(secret, "|".join(parts).encode("utf-8"))
    return hmac.compare_digest(expected, received)


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    """X-Razorpay-Signature = HMAC_SHA256(raw body, webhook secret).

    Computed over the exact bytes received — re-serialising the JSON
    would change whitespace and never match.
    """
    secret = getattr(settings, "RAZORPAY_WEBHOOK_SECRET", "")
    if not secret or not signature:
        return False
    return hmac.compare_digest(_hmac_hex(secret, raw_body), signature)
