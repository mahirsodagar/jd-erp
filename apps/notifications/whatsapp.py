"""XIRCLS WhatsApp client — trigger-based WABA messaging.

XIRCLS is a bridge to the WhatsApp Business API. Every send references a
pre-configured *trigger* (campaign) created on the XIRCLS platform, plus
a dict of named *parameters* that fill the approved template. Wire shape:

    POST https://api.xircls.com/talk/api/v1/send_trigger_message/
    headers:
      Api-key: <xircls api key>            # Profile → Global Settings
      Whatsapp-Project-Key: <project token> # Settings → Projects → Token
      Content-Type: application/json
    body:
      {
        "trigger": "lead_added",
        "country_code": "91",     # default 91 if omitted
        "contact": "9969333666",
        "parameters": {"lead_firstname": "Alex", "lead_lastname": "Brown"}
      }

Success reply:
    {"message": "Message sent successfully",
     "response": {"messages": [{"id": "...", "message_status": "accepted"}]}}

Returns (ok, response_text) — same contract as the sms/msg91 clients so
the NotificationDispatchLog records provider replies verbatim.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request

from django.conf import settings


logger = logging.getLogger(__name__)

_DEFAULT_URL = "https://api.xircls.com/talk/api/v1/send_trigger_message/"


def _mask(secret: str) -> str:
    """Mask a secret for logging: show a short prefix/suffix + length.

    Enough to verify the right key is wired (and catch typos like a
    dropped leading char) without writing the full token to log files.
    Set XIRCLS_LOG_FULL_KEYS=True to log the raw value when debugging.
    """
    s = secret or ""
    if getattr(settings, "XIRCLS_LOG_FULL_KEYS", False):
        return s
    if len(s) <= 10:
        return f"***(len={len(s)})"
    return f"{s[:6]}…{s[-4:]} (len={len(s)})"


def _split_phone(phone: str, default_cc: str) -> tuple[str, str]:
    """Split a raw phone into (country_code, national_number), digits only.

    XIRCLS wants the country code and the local number as separate fields.
    Handles +91XXXXXXXXXX, 0091..., 91XXXXXXXXXX, 0XXXXXXXXXX and a bare
    10-digit Indian mobile. Falls back to `default_cc` when no code is
    discernible.
    """
    digits = re.sub(r"\D", "", phone or "")
    if not digits:
        return default_cc, ""
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        return default_cc, digits[1:]
    if len(digits) == 10:
        return default_cc, digits
    if len(digits) > 10 and digits.startswith(default_cc):
        return default_cc, digits[len(default_cc):]
    if len(digits) > 10:
        # Unknown code — assume the trailing 10 digits are the number.
        return digits[:-10], digits[-10:]
    return default_cc, digits


# ---------------------------------------------------------------------
# Public entry point — called by services._dispatch_now for WHATSAPP
# ---------------------------------------------------------------------

def send_whatsapp(
    *, recipient: str, template_key: str, context: dict | None = None,
) -> tuple[bool, str]:
    """Send one WhatsApp message via XIRCLS for a notification template_key.

    Returns (ok, payload) where `payload` is the provider's verbatim reply
    (or a clear configuration error). Gated behind `WHATSAPP_ENABLED` so
    the channel stays dormant (queue-only) until explicitly turned on.
    """
    if not getattr(settings, "WHATSAPP_ENABLED", True):
        return False, (
            "WhatsApp disabled — set WHATSAPP_ENABLED=True once the XIRCLS "
            "triggers/keys are configured."
        )

    trigger = trigger_for(template_key)
    if not trigger:
        return False, (
            f"No XIRCLS trigger mapped for template_key {template_key!r}. "
            f"Create the trigger on the XIRCLS platform, then set "
            f"XIRCLS_WA_TRIGGERS[{template_key!r}] (or its XIRCLS_TRIGGER_* env)."
        )

    api_key = getattr(settings, "XIRCLS_API_KEY", "")
    project_key = getattr(settings, "XIRCLS_WHATSAPP_PROJECT_KEY", "")
    if not (api_key and project_key):
        return False, (
            "xircls: XIRCLS_API_KEY / XIRCLS_WHATSAPP_PROJECT_KEY not configured."
        )

    default_cc = str(getattr(settings, "XIRCLS_DEFAULT_COUNTRY_CODE", "91"))
    country_code, contact = _split_phone(recipient, default_cc)
    if not contact:
        return False, f"xircls: could not parse phone {recipient!r}"

    return _post(
        trigger=trigger,
        country_code=country_code,
        contact=contact,
        parameters=parameters_for(template_key, context or {}),
        api_key=api_key,
        project_key=project_key,
    )


def _post(
    *, trigger: str, country_code: str, contact: str, parameters: dict,
    api_key: str, project_key: str, timeout: int | None = None,
) -> tuple[bool, str]:
    payload = {
        "trigger": trigger,
        "country_code": str(country_code),
        "contact": contact,
        "parameters": parameters,
    }
    data = json.dumps(payload).encode("utf-8")
    url = getattr(settings, "XIRCLS_API_URL", _DEFAULT_URL)
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Api-key": api_key,
        "Whatsapp-Project-Key": project_key,
    }
    # Log the exact outbound call (secret header values masked).
    log_headers = {
        **headers,
        "Api-key": _mask(api_key),
        "Whatsapp-Project-Key": _mask(project_key),
    }
    logger.info(
        "XIRCLS WhatsApp request → POST %s | headers=%s | payload=%s",
        url, json.dumps(log_headers), json.dumps(payload),
    )

    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(
            req, timeout=timeout or getattr(settings, "XIRCLS_TIMEOUT", 10),
        ) as resp:
            status = resp.status
            body = resp.read().decode("utf-8", errors="replace").strip()
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        logger.warning(
            "XIRCLS WhatsApp response ← HTTP %s | body=%s", e.code,
            err_body or e.reason,
        )
        return False, f"HTTP {e.code}: {err_body or e.reason}"
    except Exception as e:  # network, timeout, DNS, etc.
        logger.warning(
            "XIRCLS WhatsApp request failed ← %s: %s", type(e).__name__, e,
        )
        return False, f"{type(e).__name__}: {e}"

    logger.info("XIRCLS WhatsApp response ← HTTP %s | body=%s", status, body)
    return _interpret_response(body)


def _interpret_response(text: str) -> tuple[bool, str]:
    """Decide ok/payload from XIRCLS's reply.

    Happy path is {"message": "Message sent successfully", "response":
    {"messages": [{"message_status": "accepted"}]}}. A 200 with a
    "Campaign not active" message (inactive trigger) is a failure. As with
    the SMS client, `accepted` means XIRCLS handed it to WhatsApp — final
    delivery is in WhatsApp's DLR, not this response.
    """
    if not text:
        return False, "(empty response)"
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        # Non-JSON reply — treat as a rejection and surface verbatim.
        return False, text

    if isinstance(data, dict):
        message = str(data.get("message", "")).lower()
        if "success" in message or "sent successfully" in message:
            return True, text
        # Some flows omit the top-level message but include an accepted
        # status in the nested WhatsApp response.
        try:
            statuses = [
                str(m.get("message_status", "")).lower()
                for m in data["response"]["messages"]
            ]
            if any(s in {"accepted", "sent", "delivered"} for s in statuses):
                return True, text
        except (KeyError, TypeError, AttributeError):
            pass
        return False, str(data.get("message") or data.get("error") or text)

    return False, text


# ---------------------------------------------------------------------
# template_key → trigger / parameters resolution
# ---------------------------------------------------------------------

def trigger_for(template_key: str) -> str | None:
    """Resolve our internal template_key → XIRCLS trigger name via
    settings.XIRCLS_WA_TRIGGERS. Returns None when unmapped/blank."""
    registry = getattr(settings, "XIRCLS_WA_TRIGGERS", {}) or {}
    return registry.get(template_key) or None


def parameters_for(template_key: str, context: dict) -> dict:
    """Build the XIRCLS `parameters` dict for a template_key.

    `settings.XIRCLS_WA_PARAM_MAP` maps each template_key to
    {xircls_param_name: our_context_key}. When an explicit map exists,
    only those params are sent (renamed from our context keys). Without a
    map, the context dict is passed through as-is (param names == our
    context keys) so a XIRCLS template configured with matching names
    works out of the box. Values are coerced to strings; missing keys
    render as empty strings.
    """
    pmap = (getattr(settings, "XIRCLS_WA_PARAM_MAP", {}) or {}).get(template_key)
    if pmap:
        return {
            pname: str((context or {}).get(ckey, "") or "")
            for pname, ckey in pmap.items()
        }
    return {
        k: (str(v) if v is not None else "")
        for k, v in (context or {}).items()
    }
