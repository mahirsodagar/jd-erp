from django.core.management.base import BaseCommand

from apps.notifications.services import process_due


class Command(BaseCommand):
    help = ("Process due ScheduledNotification rows into "
            "NotificationDispatchLog. Run periodically (cron / PA Tasks).")

    def add_arguments(self, parser):
        parser.add_argument("--batch", type=int, default=200)

    def handle(self, *args, **opts):
        out = process_due(batch_size=opts["batch"])
        self.stdout.write(self.style.SUCCESS(
            f"processed={out['processed']} dispatched={out['dispatched']} "
            f"missing_template={out['missing_template']} errors={out['errors']}"
        ))
