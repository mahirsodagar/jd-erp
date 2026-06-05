"""Fire the static bulk fee-reminder SMS to active students + their parents.

Usage
-----
    # Default: every active student
    python manage.py notify_fee_bulk_reminder

    # Filter by institute / campus / batch / program
    python manage.py notify_fee_bulk_reminder --institute JDSD
    python manage.py notify_fee_bulk_reminder --campus 5
    python manage.py notify_fee_bulk_reminder --batch 12
    python manage.py notify_fee_bulk_reminder --program 3

    # Dry-run — print recipient counts, send nothing
    python manage.py notify_fee_bulk_reminder --dry-run

The DLT body has no variables, so this fires the same wording to every
recipient. Designed for end-of-month / pre-deadline blast announcements.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.admissions.models import Enrollment, Student
from apps.fees.notifications import fire_bulk_fee_reminder


class Command(BaseCommand):
    help = (
        "Fire bulk fee-reminder SMS to active students + parents. "
        "Optionally scope by institute/campus/batch/program."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--institute", help="Institute code (e.g. JDSD, JDIFT).",
        )
        parser.add_argument("--campus", type=int, help="Campus ID.")
        parser.add_argument("--batch", type=int, help="Batch ID.")
        parser.add_argument("--program", type=int, help="Program ID.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Print recipient counts without sending.",
        )

    def handle(self, *args, **opts):
        # Active students = students with at least one ACTIVE enrollment
        # that matches the scope filters.
        enr_qs = Enrollment.objects.filter(status=Enrollment.Status.ACTIVE)
        if opts.get("campus"):
            enr_qs = enr_qs.filter(campus_id=opts["campus"])
        if opts.get("batch"):
            enr_qs = enr_qs.filter(batch_id=opts["batch"])
        if opts.get("program"):
            enr_qs = enr_qs.filter(program_id=opts["program"])

        student_ids = enr_qs.values_list("student_id", flat=True).distinct()

        students_qs = Student.objects.filter(id__in=student_ids)
        if opts.get("institute"):
            students_qs = students_qs.filter(
                institute__code=opts["institute"],
            )

        students = list(
            students_qs.only(
                "id", "student_name", "student_mobile",
                "father_mobile", "mother_mobile",
            )
        )

        if opts["dry_run"]:
            with_student = sum(
                1 for s in students if (s.student_mobile or "").strip()
            )
            with_parent = sum(
                1 for s in students
                if (s.father_mobile or "").strip() or (s.mother_mobile or "").strip()
            )
            self.stdout.write(
                f"DRY RUN — would target {len(students)} students "
                f"(student_phone={with_student}, parent_phone={with_parent})"
            )
            return

        counts = fire_bulk_fee_reminder(students)
        self.stdout.write(self.style.SUCCESS(
            f"bulk_fee_reminder — students={counts['students_fired']} "
            f"parents={counts['parents_fired']} skipped={counts['skipped']}"
        ))
