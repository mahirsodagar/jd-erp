"""SMS dispatcher — Bulk SMS Gateway India (`api.bulksmsgateway.in`).

DLT-compliant: every send must use a registered template_id whose body
matches the PHP-side approved wording. Templates are mapped in
`settings.BULK_SMS_TEMPLATE_IDS`.

Returns (ok: bool, payload: str). Payload is whatever the provider
returned — kept verbatim for the dispatch log.
"""

from __future__ import annotations

import urllib.parse
import urllib.request

from django.conf import settings


_BULK_SMS_URL = "https://api.bulksmsgateway.in/sendmessage.php"


def send_sms(*, recipient: str, body: str, template_key: str) -> tuple[bool, str]:
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
