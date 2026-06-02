"""SMS dispatcher — provider-agnostic facade.

Picks the backend based on `settings.SMS_PROVIDER`:

  * "msg91"   — control.msg91.com /api/v5/flow/  (default; works on
                PythonAnywhere free tier via UA-spoofed Cloudflare
                bypass; uses per-template flow IDs from
                `settings.MSG91_SMS_TEMPLATE_IDS`).
  * "bulksms" — api.bulksmsgateway.in            (legacy; blocked on
                PA free by the outbound proxy; only works on paid PA
                plans or non-PA hosts).

Both return (ok: bool, payload: str) where `payload` is whatever the
provider returned verbatim — kept that way for the dispatch log so
debugging stays painless.

The dispatcher in services._dispatch_now now passes `context` in
addition to `body`. BulkSMS uses the rendered body (DLT-approved
wording is sent over the wire). MSG91 ignores the rendered body and
uses positional vars (var1/var2/…) from the context dict per
settings.MSG91_SMS_VAR_ORDER — MSG91 stores the body on their side.
"""

from __future__ import annotations

import urllib.parse
import urllib.request

from django.conf import settings


_BULK_SMS_URL = "https://api.bulksmsgateway.in/sendmessage.php"


# ---------------------------------------------------------------------
# Public entry point — dispatched by SMS_PROVIDER
# ---------------------------------------------------------------------

def send_sms(
    *,
    recipient: str,
    body: str,
    template_key: str,
    context: dict | None = None,
) -> tuple[bool, str]:
    provider = (getattr(settings, "SMS_PROVIDER", "msg91") or "msg91").lower()
    if provider == "msg91":
        return _send_via_msg91(
            recipient=recipient, template_key=template_key,
            context=context or {},
        )
    if provider == "bulksms":
        return _send_via_bulksms(
            recipient=recipient, body=body, template_key=template_key,
        )
    return False, f"Unknown SMS_PROVIDER {provider!r} (expected 'msg91' or 'bulksms')."


# ---------------------------------------------------------------------
# MSG91 backend
# ---------------------------------------------------------------------

def _send_via_msg91(
    *, recipient: str, template_key: str, context: dict,
) -> tuple[bool, str]:
    from .msg91_sms import (
        send_msg91_sms, template_id_for, variables_for,
    )
    template_id = template_id_for(template_key)
    if not template_id:
        return False, (
            f"No MSG91 flow ID for template_key {template_key!r}. "
            f"Register the template on MSG91 dashboard, then set "
            f"MSG91_SMS_TEMPLATE_IDS[{template_key!r}] (or env "
            f"MSG91_FLOW_*) to the resulting flow id."
        )
    return send_msg91_sms(
        recipient=recipient,
        template_id=template_id,
        variables=variables_for(template_key, context),
    )


# ---------------------------------------------------------------------
# BulkSMS backend (legacy)
# ---------------------------------------------------------------------

def _send_via_bulksms(
    *, recipient: str, body: str, template_key: str,
) -> tuple[bool, str]:
    user = getattr(settings, "BULK_SMS_USER", "")
    password = getattr(settings, "BULK_SMS_PASSWORD", "")
    sender = getattr(settings, "BULK_SMS_SENDER", "JDEDUC")
    templates = getattr(settings, "BULK_SMS_TEMPLATE_IDS", {})
    template_id = templates.get(template_key, "")

    if not (user and password):
        return False, "BULK_SMS_USER / BULK_SMS_PASSWORD not configured."
    if not template_id:
        return False, f"No DLT template_id mapped for '{template_key}'."

    params = {
        "user": user,
        "password": password,
        "mobile": recipient,
        "message": body,
        "sender": sender,
        "type": "3",  # transactional
        "template_id": template_id,
    }
    url = f"{_BULK_SMS_URL}?{urllib.parse.urlencode(params)}"

    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            text = resp.read().decode("utf-8", errors="replace").strip()
        # Provider returns plain text; non-2xx status raises above.
        # Treat any response containing "submitted" / a job id as success;
        # otherwise log it as failure for triage.
        ok = bool(text) and "error" not in text.lower()
        return ok, text or "(empty response)"
    except Exception as e:  # network, timeout, DNS, etc.
        return False, f"{type(e).__name__}: {e}"
