"""Send a test email through every institute sending transport and
report the per-transport result — built for running from a console
(e.g. the VPS shell) to diagnose outbound mail.

    python manage.py send_test_mail you@example.com

Each transport uses its real production code path, so a PASS here means
that channel genuinely delivers:

    jdindia.com           -> dedicated Zoho SMTP   (SMTP_JDINDIA_*)
    mail.jdinstitute.com  -> MSG91 v5 email API     (MSG91_AUTHKEY)
    default backend       -> project SMTP           (EMAIL_HOST_*, should
                             be the same Zoho mailbox; used by triggers
                             with no sender-domain policy)

jdinstitute.edu.in (Google Workspace) is no longer a sending domain.

Flags:
    --only jdindia|msg91|default   send through just one transport
                                   (``edu`` is accepted as a legacy
                                   alias for ``default``)
    --msg91-template NAME          MSG91 template_id to use (default:
                                   student_portal_credentials)
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Send a test email through every sending transport and report results."

    def add_arguments(self, parser):
        parser.add_argument(
            "recipient",
            help="Destination email address for the test messages.",
        )
        parser.add_argument(
            "--only",
            choices=["jdindia", "msg91", "default", "edu"],
            help="Send through a single transport instead of all three.",
        )
        parser.add_argument(
            "--msg91-template",
            default="student_portal_credentials",
            help="MSG91 template_id to use (default: student_portal_credentials).",
        )

    def handle(self, *args, **opts):
        recipient = opts["recipient"].strip()
        if "@" not in recipient:
            raise CommandError(f"'{recipient}' does not look like an email address.")

        only = opts.get("only")
        if only == "edu":
            only = "default"
        results: list[tuple[str, str, bool, str]] = []

        if only in (None, "jdindia"):
            results.append(self._send_jdindia(recipient))
        if only in (None, "msg91"):
            results.append(self._send_msg91(recipient, opts["msg91_template"]))
        if only in (None, "default"):
            results.append(self._send_default(recipient))

        self._report(recipient, results)

    # --- per-transport senders (mirror apps.notifications routing) -------

    def _send_jdindia(self, recipient):
        """Staff / HR / admission mail — dedicated Zoho SMTP connection."""
        from apps.notifications.email import send_email

        domain, transport = "jdindia.com", "Zoho SMTP"
        cfg = (getattr(settings, "EMAIL_SMTP_BY_DOMAIN", {}) or {}).get("jdindia.com")
        if not cfg:
            return (domain, transport, False,
                    "Not configured — set SMTP_JDINDIA_HOST/USER/PASSWORD in .env")
        ok, detail = send_email(
            recipient=recipient,
            subject="[JD ERP test] jdindia.com (Zoho SMTP)",
            body="Delivery test via the jdindia.com Zoho SMTP transport.",
            smtp=cfg,
        )
        return (domain, transport, ok, detail)

    def _send_msg91(self, recipient, template_name):
        """Portal credentials / password reset — MSG91 v5 email API."""
        from apps.notifications.msg91 import send_msg91_template

        domain, transport = "mail.jdinstitute.com", "MSG91 API"
        if not getattr(settings, "MSG91_AUTHKEY", ""):
            return (domain, transport, False, "MSG91_AUTHKEY not set in .env")
        ok, detail = send_msg91_template(
            template_name=template_name,
            recipient_email=recipient,
            variables={"VAR1": "Test"},
        )
        return (domain, transport, ok, detail)

    def _send_default(self, recipient):
        """Triggers with no sender-domain policy — project default backend."""
        from apps.notifications.email import send_email

        host_user = getattr(settings, "EMAIL_HOST_USER", "") or ""
        domain = host_user.split("@", 1)[1] if "@" in host_user else "(default)"
        transport = f"default SMTP {getattr(settings, 'EMAIL_HOST', '')}"
        backend = getattr(settings, "EMAIL_BACKEND", "")
        if "console" in backend:
            return (domain, transport, False,
                    "EMAIL_BACKEND is the console backend — mail is printed, "
                    "NOT sent. Set EMAIL_BACKEND=django.core.mail.backends."
                    "smtp.EmailBackend in .env")
        ok, detail = send_email(
            recipient=recipient,
            subject=f"[JD ERP test] {domain} (default SMTP backend)",
            body="Delivery test via the project default SMTP backend (EMAIL_HOST_*).",
        )
        return (domain, transport, ok, detail)

    # --- output ----------------------------------------------------------

    def _report(self, recipient, results):
        self.stdout.write("")
        self.stdout.write(f"Test mail → {recipient}")
        self.stdout.write("=" * 72)
        passed = 0
        for domain, transport, ok, detail in results:
            tag = self.style.SUCCESS("PASS") if ok else self.style.ERROR("FAIL")
            passed += int(ok)
            self.stdout.write(f"[{tag}] {domain:22s} ({transport})")
            self.stdout.write(f"        {detail}")
        self.stdout.write("=" * 72)
        summary = f"{passed}/{len(results)} transport(s) delivered."
        self.stdout.write(
            self.style.SUCCESS(summary) if passed == len(results)
            else self.style.WARNING(summary)
        )
