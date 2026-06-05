"""Fire installment-due reminder SMS to student + parent.

Usage
-----
    # Default: remind installments due in 7 days
    python manage.py notify_installments_due

    # Remind installments due in N days (e.g. day-of, day-before)
    python manage.py notify_installments_due --days 1
    python manage.py notify_installments_due --days 0   # today
    python manage.py notify_installments_due --days 3

    # Dry-run — list affected installments, don't send
    python manage.py notify_installments_due --days 3 --dry-run

Designed to be run from cron — schedule daily for whichever windows you
want (e.g. 7-day heads-up, 3-day reminder, day-of nudge).

The command skips installments that are already fully paid (their
linked receipts' active total covers the installment amount).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Sum
from django.utils import timezone

from apps.fees.models import FeeReceipt, Installment
from apps.fees.notifications import fire_installment_due_reminder


class Command(BaseCommand):
    help = (
        "Fire SMS reminders for installments due in N days (defaults to 7). "
        "Skips already-paid installments. Idempotent within a single day."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=7,
            help="Days from today to look at (0=today, 1=tomorrow, ...).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="List matched installments without sending SMS.",
        )

    def handle(self, *args, **opts):
        days = opts["days"]
        target_date = timezone.localdate() + timedelta(days=days)

        qs = (
            Installment.objects
            .filter(due_date=target_date)
            .select_related(
                "enrollment", "enrollment__student",
                "enrollment__program",
            )
        )

        considered = fired = paid_skip = no_student = 0
        for inst in qs:
            considered += 1

            # Paid check — sum ACTIVE receipts tied to this installment.
            paid = (
                FeeReceipt.objects
                .filter(installment=inst, status=FeeReceipt.Status.ACTIVE)
                .aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
            )
            if paid >= inst.amount:
                paid_skip += 1
                continue

            student = getattr(inst.enrollment, "student", None)
            if student is None:
                no_student += 1
                continue

            if opts["dry_run"]:
                self.stdout.write(
                    f"  would-fire #{inst.id} seq={inst.sequence} "
                    f"amt={inst.amount} due={inst.due_date} → "
                    f"{student.student_name} ({student.student_mobile})"
                )
            else:
                fire_installment_due_reminder(inst)
            fired += 1

        verb = "would-fire" if opts["dry_run"] else "fired"
        self.stdout.write(self.style.SUCCESS(
            f"installments_due — target={target_date} "
            f"considered={considered} {verb}={fired} "
            f"paid_skip={paid_skip} no_student={no_student}"
        ))
