"""MSG91 v5 transactional SMS client (flow-based API).

MSG91's SMS API is template-driven like its email API: every send
references a `template_id` that was registered + DLT-approved through
the MSG91 dashboard. Variables come over the wire as `var1`, `var2`, …
(positional) — the order matches the `{#var#}` placeholders in the
template body as registered with MSG91.

Wire shape:

    POST https://control.msg91.com/api/v5/flow/
    headers:
      authkey: <key>
      Content-Type: application/json
      User-Agent: <browser-shaped>  # bypasses Cloudflare 1010
    body:
      {
        "template_id": "675ad5a4d6fc051d1a04b3f3",
        "short_url":   "0",
        "recipients": [
          {"mobiles": "919900000000", "var1": "Aisha", "var2": "https://..."}
        ]
      }

Returns (ok, response_text) — same shape as the email client so the
NotificationDispatchLog captures provider replies verbatim.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from django.conf import settings


_MSG91_SMS_URL = "https://control.msg91.com/api/v5/flow/"

# Same User-Agent we use for the email client — Cloudflare flags
# `Python-urllib/3.x` + datacenter IP as bot traffic.
_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _normalize_phone(phone: str) -> str:
    """MSG91 expects digits only — no '+', no spaces, no dashes.
    A bare 10-digit Indian mobile is prefixed with 91."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    # Bare 10-digit number → assume India.
    if len(digits) == 10:
        digits = "91" + digits
    return digits


def send_msg91_sms(
    *,
    recipient: str,
    template_id: str,
    variables: dict | None = None,
    sender: str | None = None,
    authkey: str | None = None,
    timeout: int | None = None,
    dry_run: bool = False,
) -> tuple[bool, str]:
    """POST one SMS through MSG91's flow API.

    `template_id` is the MSG91 flow id (24-char hex), NOT the DLT id.
    The DLT id is registered separately on MSG91's dashboard and the
    flow id is what comes back. Pass that here.

    `variables` should already be keyed `var1`, `var2`, … — the
    caller in `sms.send_sms` handles the positional mapping from our
    template-key context dict.
    """
    if not template_id:
        return False, "msg91-sms: template_id is required"
    if not recipient:
        return False, "msg91-sms: recipient phone is required"

    mobiles = _normalize_phone(recipient)
    if not mobiles:
        return False, f"msg91-sms: could not normalize phone {recipient!r}"

    authkey = authkey or getattr(settings, "MSG91_SMS_AUTHKEY", "") or \
        getattr(settings, "MSG91_AUTHKEY", "")
    if not authkey:
        return False, "msg91-sms: MSG91_SMS_AUTHKEY / MSG91_AUTHKEY not configured"

    sender = sender or getattr(settings, "MSG91_SMS_SENDER_ID", "") or "JDEDUC"

    payload = {
        "template_id": template_id,
        "short_url": "0",     # we already shorten URLs ourselves via tinyurl
        "realTimeResponse": "1",
        "recipients": [
            {
                "mobiles": mobiles,
                **(variables or {}),
            },
        ],
    }
    if sender:
        payload["sender"] = sender

    if dry_run:
        return True, json.dumps(payload, indent=2)

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        _MSG91_SMS_URL,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "authkey": authkey,
            "User-Agent": _BROWSER_UA,
        },
    )
    try:
        with urllib.request.urlopen(
            req, timeout=timeout or getattr(settings, "MSG91_TIMEOUT", 10),
        ) as resp:
            body = resp.read().decode("utf-8", errors="replace").strip()
            try:
                parsed = json.loads(body) if body else {}
                ok = str(parsed.get("type") or parsed.get("status", "")).lower() in {
                    "success", "ok",
                }
            except json.JSONDecodeError:
                ok = False
            return ok, body or "(empty response)"
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        return False, f"HTTP {e.code}: {err_body or e.reason}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def template_id_for(template_key: str) -> str | None:
    """Resolve our internal template_key → MSG91 SMS flow ID via
    settings.MSG91_SMS_TEMPLATE_IDS. Returns None when unmapped."""
    registry = getattr(settings, "MSG91_SMS_TEMPLATE_IDS", {}) or {}
    return registry.get(template_key) or None


def variables_for(template_key: str, context: dict) -> dict:
    """Map our template-key context dict → MSG91's positional var1/var2/…
    using settings.MSG91_SMS_VAR_ORDER. Missing keys are emitted as
    empty strings so the registered template body always renders cleanly.
    """
    order = (
        getattr(settings, "MSG91_SMS_VAR_ORDER", {}) or {}
    ).get(template_key, [])
    out: dict[str, str] = {}
    for i, key in enumerate(order, start=1):
        out[f"var{i}"] = str((context or {}).get(key, "") or "")
    return out
