"""Generate each program's semesters from its duration.

Semesters are per-program, so 60 programs x N semesters is far too much
to enter by hand. This derives the count from `Program.duration_months`
at two semesters a year and creates any that are missing. Idempotent —
existing semesters are left exactly as they are.
"""

from django.core.management.base import BaseCommand

from apps.master.models import Program, Semester

#: Legacy programs are all two-semester years.
MONTHS_PER_SEMESTER = 6


class Command(BaseCommand):
    help = "Create Semester rows for each program from its duration."

    def add_arguments(self, parser):
        parser.add_argument(
            "--program", type=str, default="",
            help="Only this program code. Default: every active program.",
        )
        parser.add_argument(
            "--count", type=int, default=0,
            help="Force this many semesters instead of deriving from "
                 "duration_months.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would be created without writing.",
        )

    def handle(self, *args, **opts):
        qs = Program.objects.filter(is_active=True)
        if opts["program"]:
            qs = qs.filter(code=opts["program"])

        created = skipped = 0
        no_duration = []

        for program in qs.order_by("code"):
            wanted = opts["count"] or self._semester_count(program)
            if not wanted:
                no_duration.append(program.code)
                continue

            existing = set(
                program.semesters.values_list("number", flat=True)
            )
            for number in range(1, wanted + 1):
                if number in existing:
                    skipped += 1
                    continue
                if not opts["dry_run"]:
                    Semester.objects.create(
                        program=program,
                        name=f"Semester {number}",
                        number=number,
                    )
                created += 1

        verb = "Would create" if opts["dry_run"] else "Created"
        self.stdout.write(self.style.SUCCESS(
            f"{verb} {created} semester(s); {skipped} already existed."
        ))
        if no_duration:
            self.stdout.write(self.style.WARNING(
                f"No duration_months, skipped: {', '.join(no_duration)}. "
                f"Pass --count to set them explicitly."
            ))

    @staticmethod
    def _semester_count(program) -> int:
        if not program.duration_months:
            return 0
        # Round up so an 11-month course still gets its second semester.
        return -(-program.duration_months // MONTHS_PER_SEMESTER)
