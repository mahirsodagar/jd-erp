"""Replay leave / comp-off emails that were not delivered.

Leave mail is sent inline when the application is filed or decided. Rows
only pile up when the host had SMTP egress disabled at that moment
(`EMAIL_SMTP_OUTBOUND_ENABLED=False`) or the transport rejected the
message. This command drains them.

    python manage.py send_leave_emails            # queued only
    python manage.py send_leave_emails --failed   # queued + failed
    python manage.py send_leave_emails --limit 50
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.leaves.models import EmailDispatchLog
from apps.leaves.services.notifications import deliver


class Command(BaseCommand):
    help = "Send leave/comp-off emails still sitting at queued (or failed)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--failed", action="store_true",
            help="Also retry rows that previously failed.",
        )
        parser.add_argument(
            "--limit", type=int, default=200,
            help="Maximum rows to process (default 200).",
        )

    def handle(self, *args, **opts):
        if not getattr(settings, "EMAIL_SMTP_OUTBOUND_ENABLED", True):
            self.stderr.write(self.style.ERROR(
                "EMAIL_SMTP_OUTBOUND_ENABLED is False — this host is "
                "configured as having no SMTP egress, so nothing would be "
                "sent. Set it True and re-run."
            ))
            return

        backend = getattr(settings, "EMAIL_BACKEND", "")
        if "console" in backend or "locmem" in backend:
            self.stderr.write(self.style.WARNING(
                f"EMAIL_BACKEND={backend} — mail is printed/discarded, NOT "
                "delivered, and rows will still be marked 'sent'. Set "
                "EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend."
            ))

        statuses = [EmailDispatchLog.Status.QUEUED]
        if opts["failed"]:
            statuses.append(EmailDispatchLog.Status.FAILED)

        rows = EmailDispatchLog.objects.filter(
            status__in=statuses,
        ).order_by("created_at")[: opts["limit"]]

        sent = failed = 0
        for row in rows:
            deliver(row)
            if row.status == EmailDispatchLog.Status.SENT:
                sent += 1
            else:
                failed += 1
                self.stderr.write(f"  #{row.pk} {row.to}: {row.error}")

        self.stdout.write(self.style.SUCCESS(
            f"Processed {sent + failed} — sent={sent} failed={failed}."
        ))
