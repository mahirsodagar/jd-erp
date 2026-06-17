"""MSG91 v5 transactional email client.

Mirrors what the legacy PHP project did — see e.g.
JD_ERP/admissions/save.php and JD_ERP/mailcheck.php which POST raw JSON
to `https://control.msg91.com/api/v5/email/send` with an `authkey:` header.

MSG91 templates are pre-registered on their dashboard by name (e.g.
`student_invoice_copy`, `assignment_assigned`). The payload supplies a
dict of variables that the registered template fills in.

Configuration lives in `settings`:

    MSG91_AUTHKEY        — auth header (defaults to the PHP project's key)
    MSG91_SENDER_EMAIL   — from-address shown to recipients
    MSG91_DOMAIN         — the registered sender domain (must match the
                           `from` email's domain, MSG91 cross-checks)
    MSG91_EMAIL_TEMPLATES — registry mapping our internal template_key
                            → the MSG91 template name. Templates not in
                            the registry fall through to plain SMTP.
    MSG91_TIMEOUT        — seconds, default 10.

Returns (ok, response_text) consistently with `sms.send_sms` so the
NotificationDispatchLog row records the provider's reply verbatim.
"""

from __future__ import annotations

import http.client
import json
import socket
import urllib.error
import urllib.request

from django.conf import settings


_MSG91_URL = "https://control.msg91.com/api/v5/email/send"


# control.msg91.com is dual-stack (Cloudflare A + AAAA records). On a
# dual-stack host the default resolver prefers IPv6, so the request
# egresses from the host's IPv6 address — which MSG91's per-authkey "IP
# Security" whitelist (IPv4 only) does not recognise, and every call is
# rejected with HTTP 401 / apiError 418. Forcing the connection to IPv4
# pins egress to the whitelisted A-record IP. Harmless on IPv4-only
# hosts (getaddrinfo just returns the v4 address). Toggle with
# settings.MSG91_FORCE_IPV4 (default True).
class _IPv4HTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        infos = socket.getaddrinfo(
            self.host, self.port, socket.AF_INET, socket.SOCK_STREAM,
        )
        af, socktype, proto, _canon, sa = infos[0]
        sock = socket.socket(af, socktype, proto)
        if self.timeout is not None:
            sock.settimeout(self.timeout)
        if self.source_address:
            sock.bind(self.source_address)
        sock.connect(sa)
        # Preserve SNI / cert hostname matching against the real host.
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _IPv4HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_IPv4HTTPSConnection, req)


# Built once; reused across calls.
_ipv4_opener = urllib.request.build_opener(_IPv4HTTPSHandler())


def _urlopen(req, timeout):
    """Open `req`, forcing IPv4 unless explicitly disabled in settings."""
    if getattr(settings, "MSG91_FORCE_IPV4", True):
        return _ipv4_opener.open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)


def _split_csv(s: str) -> list[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def send_msg91_template(
    *,
    template_name: str,
    recipient_email: str,
    recipient_name: str = "",
    variables: dict | None = None,
    cc: str | list[str] = "",
    sender_email: str | None = None,
    domain: str | None = None,
    timeout: int | None = None,
    dry_run: bool = False,
) -> tuple[bool, str]:
    """POST a single-recipient transactional email through MSG91 v5.

    All MSG91 templates are referenced by *name* (not numeric id) — the
    name is what shows up in the MSG91 console.

    `variables` keys should match what the template author defined
    (typically VAR1, VAR2 ... — see the PHP wrappers for examples).

    `dry_run=True` skips the network call and returns the payload that
    would have been posted; useful for tests + initial wiring.
    """
    if not template_name:
        return False, "msg91: template_name is required"
    if not recipient_email:
        return False, "msg91: recipient_email is required"

    authkey = getattr(settings, "MSG91_AUTHKEY", "")
    if not authkey:
        return False, "msg91: MSG91_AUTHKEY not configured"

    sender_email = sender_email or getattr(
        settings, "MSG91_SENDER_EMAIL", "",
    )
    domain = domain or getattr(settings, "MSG91_DOMAIN", "")
    if not sender_email or not domain:
        return False, "msg91: MSG91_SENDER_EMAIL / MSG91_DOMAIN not configured"

    cc_list = cc if isinstance(cc, list) else _split_csv(cc)

    payload = {
        "recipients": [
            {
                "to": [{
                    "email": recipient_email,
                    **({"name": recipient_name} if recipient_name else {}),
                }],
                **({"cc": [{"email": e} for e in cc_list]} if cc_list else {}),
                "variables": variables or {},
            },
        ],
        "from": {"email": sender_email},
        "domain": domain,
        "template_id": template_name,
    }

    if dry_run:
        return True, json.dumps(payload, indent=2)

    data = json.dumps(payload).encode("utf-8")
    # Cloudflare (in front of control.msg91.com) flags requests with
    # `Python-urllib/3.x` as bot traffic and returns 403 / error 1010.
    # Set a generic browser-shaped User-Agent so the request looks like
    # any HTTP client. Real browsers don't send `authkey` headers, but
    # CF only fingerprints UA + IP, so this is enough on its own.
    req = urllib.request.Request(
        _MSG91_URL,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "authkey": authkey,
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        },
    )
    try:
        with _urlopen(
            req, timeout=timeout or getattr(settings, "MSG91_TIMEOUT", 10),
        ) as resp:
            body = resp.read().decode("utf-8", errors="replace").strip()
            # MSG91 returns 2xx + a JSON body like
            #   {"status": "success", "data": {"request_id": "..."}}
            # on accept. Anything else is failure.
            try:
                parsed = json.loads(body) if body else {}
                ok = str(parsed.get("status", "")).lower() == "success"
            except json.JSONDecodeError:
                ok = False
            return ok, body or "(empty response)"
    except urllib.error.HTTPError as e:
        # 4xx / 5xx — read the body so the dispatch log captures the reason
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        return False, f"HTTP {e.code}: {err_body or e.reason}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------------
# Registry helpers
# ---------------------------------------------------------------------

def template_for(template_key: str) -> str | None:
    """Resolve our internal template_key → MSG91 template name via
    settings.MSG91_EMAIL_TEMPLATES. Returns None when unmapped."""
    registry = getattr(settings, "MSG91_EMAIL_TEMPLATES", {}) or {}
    return registry.get(template_key)
