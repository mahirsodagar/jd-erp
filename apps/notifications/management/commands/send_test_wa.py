"""Send a test WhatsApp message through XIRCLS and/or show queued WA
notices — the WhatsApp counterpart to send_test_sms / send_test_mail,
for diagnosing outbound WhatsApp from the VPS console.

    python manage.py send_test_wa 9XXXXXXXXX
    python manage.py send_test_wa 9XXXXXXXXX --template lead_welcome_wa \
                                             --var name=Ayush --var program=Interior
    python manage.py send_test_wa 9XXXXXXXXX --raw      # hit XIRCLS directly, no DB row
    python manage.py send_test_wa --show               # list recent WA dispatch-log rows

The default (no --raw) goes through the real `queue_notification` path,
so it writes a NotificationDispatchLog row and dispatches it via XIRCLS
— exactly what signals/attendance do. A PASS means XIRCLS accepted the
message (final delivery is in WhatsApp's DLR).

Requires WHATSAPP_ENABLED=True plus XIRCLS_API_KEY,
XIRCLS_WHATSAPP_PROJECT_KEY, and an XIRCLS_WA_TRIGGERS mapping for the
template — otherwise the send returns a clear configuration error.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Send a test WhatsApp message through XIRCLS and report the result."

    def add_arguments(self, parser):
        parser.add_argument(
            "recipient", nargs="?",
            help="Destination mobile number (e.g. 9XXXXXXXXX). "
                 "Omit only with --show.",
        )
        parser.add_argument(
            "--template", default="lead_welcome_wa",
            help="WHATSAPP template_key to send (default: lead_welcome_wa).",
        )
        parser.add_argument(
            "--var", action="append", default=[], metavar="k=v",
            help="Context value for a template parameter (repeatable).",
        )
        parser.add_argument(
            "--raw", action="store_true",
            help="Call XIRCLS directly (no DB row), to isolate creds/connectivity.",
        )
        parser.add_argument(
            "--show", nargs="?", type=int, const=15, default=None, metavar="N",
            help="List the last N WhatsApp dispatch-log rows and exit (default 15).",
        )

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

        # Pre-flight warnings (don't fail — let the provider error surface).
        if not getattr(settings, "WHATSAPP_ENABLED", False):
            self.stdout.write(self.style.WARNING(
                "  ! WHATSAPP_ENABLED is False — sends are disabled. "
                "Set it True in the server .env once XIRCLS is configured."
            ))
        trig = (getattr(settings, "XIRCLS_WA_TRIGGERS", {}) or {}).get(template_key)
        if not trig:
            self.stdout.write(self.style.WARNING(
                f"  ! No XIRCLS_WA_TRIGGERS mapping for '{template_key}' — "
                f"the send will be rejected. Set the trigger name first."
            ))

        if opts["raw"]:
            self._send_raw(recipient, template_key, context)
        else:
            self._send_queued(recipient, template_key, context)

    # --- modes ---------------------------------------------------------

    def _send_raw(self, recipient, template_key, context):
        """Hit XIRCLS directly via the facade — no DB row."""
        from apps.notifications.whatsapp import send_whatsapp

        self.stdout.write(f"RAW send → {recipient}  ({template_key})")
        self.stdout.write(f"  params: {context or '(none)'}")
        ok, payload = send_whatsapp(
            recipient=recipient, template_key=template_key, context=context,
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
        if isinstance(log, L):
            log.refresh_from_db()
            self.stdout.write(f"  dispatch log #{log.id}  [{log.status}]")
            self._verdict(log.status == L.Status.SENT, log.error or "(no error)")
        else:
            self.stdout.write(self.style.WARNING(
                f"  scheduled (not dispatched now): {log}"
            ))

    def _show_log(self, n):
        from apps.notifications.models import NotificationDispatchLog as L

        qs = L.objects.filter(channel="WHATSAPP").order_by("-created_at")[:n]
        total = L.objects.filter(channel="WHATSAPP").count()
        self.stdout.write(
            f"Recent WhatsApp dispatch-log rows (showing {len(qs)} of {total}):"
        )
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
                f"{r.template_key:30s} → {r.recipient}"
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
        enabled = getattr(settings, "WHATSAPP_ENABLED", False)
        api = "set" if getattr(settings, "XIRCLS_API_KEY", "") else "UNSET"
        proj = "set" if getattr(settings, "XIRCLS_WHATSAPP_PROJECT_KEY", "") else "UNSET"
        self.stdout.write("=" * 84)
        self.stdout.write(
            f"WhatsApp via XIRCLS | enabled={enabled} | "
            f"Api-key={api} | Project-Key={proj}"
        )
        self.stdout.write("=" * 84)

    def _verdict(self, ok, payload):
        tag = self.style.SUCCESS("PASS") if ok else self.style.ERROR("FAIL")
        self.stdout.write(f"  [{tag}] xircls: {payload}")
        self.stdout.write("=" * 84)
