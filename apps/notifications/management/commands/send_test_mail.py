"""Send a test email through the ZeptoMail SMTP transport and report the
result — built for running from a console (e.g. the VPS shell) to
diagnose outbound mail.

    python manage.py send_test_mail you@example.com
    python manage.py send_test_mail you@example.com --reply-to hr@x.in
    python manage.py send_test_mail you@example.com --template student.portal_credentials.email

It uses the real production code path (`apps.notifications.email.
send_email`, or the dispatcher when `--template` is given), so a PASS
here means mail genuinely delivers From no-reply@dkul.in with the
Reply-To the policy picks.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Send a test email through the ZeptoMail SMTP transport."

    def add_arguments(self, parser):
        parser.add_argument(
            "recipient",
            help="Destination email address for the test message.",
        )
        parser.add_argument(
            "--reply-to", default="",
            help="Explicit Reply-To for the plain test mail (default: the "
                 "policy fallback EMAIL_DEFAULT_REPLY_TO).",
        )
        parser.add_argument(
            "--template", default="",
            help="Send a NotificationTemplate row through the dispatcher "
                 "instead of the plain test mail (placeholders filled "
                 "with 'TEST').",
        )

    def handle(self, *args, **opts):
        recipient = opts["recipient"].strip()
        if "@" not in recipient:
            raise CommandError(f"'{recipient}' does not look like an email address.")

        self._print_config()

        backend = getattr(settings, "EMAIL_BACKEND", "")
        if "console" in backend or "locmem" in backend:
            raise CommandError(
                f"EMAIL_BACKEND={backend} — mail is printed/discarded, NOT "
                "sent. Set EMAIL_BACKEND=django.core.mail.backends.smtp."
                "EmailBackend in .env (or remove the override)."
            )
        if not getattr(settings, "EMAIL_HOST_PASSWORD", ""):
            raise CommandError(
                "ZEPTOMAIL_SMTP_TOKEN is not set in .env — the SMTP login "
                "will be refused."
            )

        if opts["template"]:
            ok, detail = self._send_template(recipient, opts["template"])
        else:
            ok, detail = self._send_plain(recipient, opts["reply_to"])

        self.stdout.write("")
        tag = self.style.SUCCESS("PASS") if ok else self.style.ERROR("FAIL")
        self.stdout.write(f"[{tag}] {recipient}: {detail}")

    # --- helpers ---------------------------------------------------------

    def _print_config(self):
        from apps.notifications.email import resolve_from_email
        from apps.notifications.reply_to import default_reply_to

        self.stdout.write("ZeptoMail SMTP transport")
        self.stdout.write("=" * 72)
        self.stdout.write(
            f"  host      {getattr(settings, 'EMAIL_HOST', '')}:"
            f"{getattr(settings, 'EMAIL_PORT', '')}  "
            f"ssl={getattr(settings, 'EMAIL_USE_SSL', False)} "
            f"tls={getattr(settings, 'EMAIL_USE_TLS', False)}"
        )
        self.stdout.write(f"  user      {getattr(settings, 'EMAIL_HOST_USER', '')}")
        self.stdout.write(
            f"  token     {'set' if getattr(settings, 'EMAIL_HOST_PASSWORD', '') else 'UNSET'}"
        )
        self.stdout.write(f"  from      {resolve_from_email()}")
        self.stdout.write(f"  reply-to  {default_reply_to()} (default)")
        self.stdout.write("=" * 72)

    def _send_plain(self, recipient, reply_to):
        from apps.notifications.email import send_email

        return send_email(
            recipient=recipient,
            subject="[JD ERP test] ZeptoMail SMTP",
            body=(
                "Delivery test via the ZeptoMail SMTP transport.\n\n"
                "If you can read this, outbound mail works. Hit Reply to "
                "confirm the Reply-To routing lands in the right inbox."
            ),
            reply_to=reply_to,
        )

    def _send_template(self, recipient, key):
        import re

        from apps.notifications.models import (
            NotificationDispatchLog, NotificationTemplate,
        )
        from apps.notifications.services import _PLACEHOLDER_RE, queue_notification

        try:
            tmpl = NotificationTemplate.objects.get(key=key)
        except NotificationTemplate.DoesNotExist:
            raise CommandError(f"No NotificationTemplate with key {key!r}.")
        names = {
            (m.group(1) or m.group(2))
            for m in _PLACEHOLDER_RE.finditer(
                tmpl.subject_template + "\n" + tmpl.body_template,
            )
        }
        context = {n: "TEST" for n in names}
        context.update({"url": "https://example.com/test",
                        "login_url": "https://example.com/test"})
        context = {k: v for k, v in context.items() if re.match(r"\w+$", k)}
        log = queue_notification(template_key=key, recipient=recipient,
                                 context=context)
        ok = getattr(log, "status", "") == NotificationDispatchLog.Status.SENT
        return ok, (f"dispatch log #{log.pk} status={log.status}"
                    + (f" error={log.error}" if not ok else ""))
