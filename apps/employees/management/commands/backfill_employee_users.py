"""Create a portal `User` for every existing Employee that doesn't
have one yet. Useful as a one-shot after deploying the auto-provision
change so historical employees become visible on the Users page.

Usage:
    python manage.py backfill_employee_users           # dry-run
    python manage.py backfill_employee_users --apply   # write
"""

from django.core.management.base import BaseCommand

from apps.employees.models import Employee
from apps.employees.services import provision_portal_user


class Command(BaseCommand):
    help = ("Backfill portal users for existing employees missing a "
            "user_account link.")

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Persist changes (without this flag the command is a dry-run).",
        )

    def handle(self, *args, **opts):
        apply = bool(opts["apply"])
        qs = (
            Employee.all_objects
            .filter(user_account__isnull=True, is_deleted=False)
            .order_by("emp_code")
        )
        total = qs.count()
        self.stdout.write(
            f"Found {total} employee(s) without a portal user.",
        )
        if not total:
            return
        if not apply:
            for emp in qs[:50]:
                self.stdout.write(f"  would provision: {emp.emp_code} — {emp.full_name}")
            if total > 50:
                self.stdout.write(f"  …and {total - 50} more.")
            self.stdout.write(
                self.style.WARNING(
                    "\nDry-run complete. Re-run with --apply to write.",
                ),
            )
            return

        ok = skipped = 0
        for emp in qs.iterator():
            try:
                user, temp_pw = provision_portal_user(employee=emp)
            except Exception as e:
                self.stderr.write(f"  ✗ {emp.emp_code}: {e}")
                continue
            if temp_pw:
                ok += 1
                self.stdout.write(
                    f"  ✓ {emp.emp_code} → user={user.username} "
                    f"temp_password={temp_pw}",
                )
            else:
                skipped += 1
                self.stdout.write(
                    f"  · {emp.emp_code} → linked to existing user "
                    f"{user.username} (no new password issued)",
                )
        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Created {ok}, linked existing {skipped}.",
            ),
        )
