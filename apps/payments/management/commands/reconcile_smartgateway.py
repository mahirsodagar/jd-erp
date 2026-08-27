"""Re-read non-terminal SmartGateway orders and settle any that were paid.

The safety net for webhooks that never landed — a misconfigured endpoint,
or downtime that outlasted SmartGateway's retry schedule. Safe to run on
a cron; `apply_order_body` is idempotent, so an order that already
settled via webhook is left alone.

    python manage.py reconcile_smartgateway --days 30
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.payments.gateway import SmartGatewayError, is_enabled
from apps.payments.models import PaymentOrder
from apps.payments.services import reconcile_order


class Command(BaseCommand):
    help = "Poll SmartGateway for the status of unsettled payment orders."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=30,
            help="Only check orders created in the last N days (default 30).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would be checked without calling SmartGateway.",
        )

    def handle(self, *args, **options):
        if not is_enabled():
            self.stderr.write(self.style.ERROR(
                "SmartGateway is not enabled — set SMARTGATEWAY_ENABLED and "
                "the API key / merchant id / client id.",
            ))
            return

        cutoff = timezone.now() - timedelta(days=options["days"])
        # Only orders the student actually reached the bank with, and
        # only those that could still change.
        orders = (
            PaymentOrder.objects
            .filter(created_on__gte=cutoff)
            .exclude(status__in=PaymentOrder.TERMINAL_STATUSES)
            .exclude(sg_order_ref="")
            .select_related("request", "request__lead")
            .order_by("created_on")
        )

        self.stdout.write(f"{orders.count()} unsettled order(s) to check.")
        settled = errors = 0
        for order in orders:
            if options["dry_run"]:
                self.stdout.write(
                    f"  would check {order.order_id} ({order.status})",
                )
                continue
            previous = order.status
            try:
                updated = reconcile_order(order)
            except SmartGatewayError as e:
                errors += 1
                self.stderr.write(self.style.WARNING(
                    f"  {order.order_id}: {e}",
                ))
                continue
            if updated.status != previous:
                settled += 1
                self.stdout.write(self.style.SUCCESS(
                    f"  {order.order_id}: {previous} → {updated.status}",
                ))

        if not options["dry_run"]:
            self.stdout.write(f"Done. {settled} changed, {errors} error(s).")
