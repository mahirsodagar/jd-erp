"""Send a test SMS through the live gateway and/or show queued SMS
notices — built for running from the VPS console to diagnose outbound
SMS the same way `send_test_mail` does for email.

    python manage.py send_test_sms 9XXXXXXXXX
    python manage.py send_test_sms 9XXXXXXXXX --template attendance.student_absent_v2.sms \
                                              --var name=Ayush --var date=2026-06-18 --var subject=Sketching
    python manage.py send_test_sms 9XXXXXXXXX --raw       # hit the gateway directly, no DB row
    python manage.py send_test_sms --show                 # just list recent SMS dispatch-log rows

The default (no --raw) goes through the real `queue_notification` code
path, so it writes a NotificationDispatchLog row (the "SMS notice
queued") and then dispatches it via settings.SMS_PROVIDER — exactly what
the app does for attendance / fees / leads. A PASS here means the live
provider (BulkSMS by default) genuinely accepted the message.

Flags:
    --template KEY   DLT-mapped template_key to send (default:
                     fees.bulk_reminder.sms — a static body needing no vars).
    --var k=v        Context value for {placeholders} in the template
                     (repeatable). Required for templates that have vars.
    --raw            Bypass the queue/DB and call the gateway directly,
                     to isolate credentials/connectivity from the ORM.
    --show [N]       Print the last N SMS dispatch-log rows (default 15)
                     and exit without sending.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Send a test SMS through the live gateway and report the result."

    def add_arguments(self, parser):
        parser.add_argument(
            "recipient", nargs="?",
            help="Destination mobile number (e.g. 9XXXXXXXXX). "
                 "Omit only with --show.",
        )
        parser.add_argument(
            "--template", default="fees.bulk_reminder.sms",
            help="DLT-mapped template_key (default: fees.bulk_reminder.sms).",
        )
        parser.add_argument(
            "--var", action="append", default=[], metavar="k=v",
            help="Context value for a {placeholder} in the template (repeatable).",
        )
        parser.add_argument(
            "--raw", action="store_true",
            help="Call the gateway directly (no DB row), to isolate creds/connectivity.",
        )
        parser.add_argument(
            "--show", nargs="?", type=int, const=15, default=None, metavar="N",
            help="List the last N SMS dispatch-log rows and exit (default 15).",
        )

    # ------------------------------------------------------------------

    def handle(self, *args, **opts):
        self._banner()

        if opts["show"] is not None:
            self._show_log(opts["show"])
            return

        recipient = (opts["recipient"] or "").strip().replace(" ", "")
        if not recipient:
            raise CommandError(
                "A recipient mobile number is required (or use --show)."
            )
        if not recipient.lstrip("+").isdigit():
            raise CommandError(f"'{recipient}' does not look like a mobile number.")

        template_key = opts["template"]
        context = self._parse_vars(opts["var"])

        # Pre-flight: warn (don't fail) on a missing DLT id so the gateway
        # error is still surfaced verbatim.
        dlt = (getattr(settings, "BULK_SMS_TEMPLATE_IDS", {}) or {}).get(template_key)
        if (settings.SMS_PROVIDER or "").lower() == "bulksms" and not dlt:
            self.stdout.write(self.style.WARNING(
                f"  ! No BULK_SMS_TEMPLATE_IDS mapping for '{template_key}' — "
                f"the send will be rejected. Add a DLT_TPL_* env or pick a "
                f"mapped --template."
            ))

        if opts["raw"]:
            self._send_raw(recipient, template_key, context)
        else:
            self._send_queued(recipient, template_key, context)

    # --- modes ---------------------------------------------------------

    def _send_raw(self, recipient, template_key, context):
        """Hit the gateway directly via the dispatcher facade — no DB row."""
        from apps.notifications.sms import send_sms
        from apps.notifications.models import NotificationTemplate as NT
        from apps.notifications.services import _render

        body = ""
        tmpl = NT.objects.filter(key=template_key, channel="SMS").first()
        if tmpl:
            body = _render(tmpl.body_template, context)

        self.stdout.write(f"RAW send → {recipient}  ({template_key})")
        self.stdout.write(f"  body: {body or '(provider stores body — vars only)'}")
        ok, payload = send_sms(
            recipient=recipient, body=body,
            template_key=template_key, context=context,
        )
        self._verdict(ok, payload)

    def _send_queued(self, recipient, template_key, context):
        """Full path: queue_notification → dispatch log row → live send."""
        from apps.notifications.services import queue_notification
        from apps.notifications.models import NotificationDispatchLog as L

        self.stdout.write(f"QUEUE + send → {recipient}  ({template_key})")
        log = queue_notification(
            template_key=template_key, recipient=recipient, context=context,
        )
        # Re-read so we report the post-dispatch status, not the create-time one.
        if isinstance(log, L):
            log.refresh_from_db()
            self.stdout.write(f"  dispatch log #{log.id}")
            self.stdout.write(f"  body: {log.body!r}")
            self._verdict(log.status == L.Status.SENT, log.error or "(no error)")
        else:
            # A future fire_at would return a ScheduledNotification — not
            # expected here, but report it rather than crash.
            self.stdout.write(self.style.WARNING(
                f"  scheduled (not dispatched now): {log}"
            ))

    def _show_log(self, n):
        from apps.notifications.models import NotificationDispatchLog as L

        qs = L.objects.filter(channel="SMS").order_by("-created_at")[:n]
        total = L.objects.filter(channel="SMS").count()
        self.stdout.write(f"Recent SMS dispatch-log rows (showing {len(qs)} of {total}):")
        self.stdout.write("-" * 84)
        if not qs:
            self.stdout.write("  (none yet)")
            return
        for r in qs:
            tag = {
                L.Status.SENT: self.style.SUCCESS("SENT  "),
                L.Status.FAILED: self.style.ERROR("FAILED"),
            }.get(r.status, self.style.WARNING("QUEUED"))
            self.stdout.write(
                f"  #{r.id:<5d} {r.created_at:%Y-%m-%d %H:%M} [{tag}] "
                f"{r.template_key:34s} → {r.recipient}"
            )
            if r.error:
                self.stdout.write(f"          err: {r.error[:70]}")

    # --- helpers -------------------------------------------------------

    def _parse_vars(self, pairs):
        ctx = {}
        for p in pairs:
            if "=" not in p:
                raise CommandError(f"--var must be k=v, got '{p}'.")
            k, v = p.split("=", 1)
            ctx[k.strip()] = v
        return ctx

    def _banner(self):
        provider = (getattr(settings, "SMS_PROVIDER", "") or "?").lower()
        self.stdout.write("=" * 84)
        self.stdout.write(f"SMS_PROVIDER = {provider}")
        if provider == "bulksms":
            self.stdout.write(
                f"  BulkSMS user={getattr(settings, 'BULK_SMS_USER', '') or '(unset)'} "
                f"sender={getattr(settings, 'BULK_SMS_SENDER', '')} "
                f"password={'set' if getattr(settings, 'BULK_SMS_PASSWORD', '') else 'UNSET'}"
            )
        elif provider == "msg91":
            key = getattr(settings, "MSG91_SMS_AUTHKEY", "") or getattr(settings, "MSG91_AUTHKEY", "")
            self.stdout.write(f"  MSG91 authkey={'set' if key else 'UNSET'}")
        self.stdout.write("=" * 84)

    def _verdict(self, ok, payload):
        tag = self.style.SUCCESS("PASS") if ok else self.style.ERROR("FAIL")
        self.stdout.write(f"  [{tag}] gateway: {payload}")
        self.stdout.write("=" * 84)
