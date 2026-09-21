"""Seed subjects from a CSV — same format and rules as the Subjects page
upload (see `apps.master.subject_import`).

    python manage.py import_subjects subjects.csv --dry-run
    python manage.py import_subjects subjects.csv

All-or-nothing: any row error aborts without writing.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.master import subject_import as imp


class Command(BaseCommand):
    help = "Create/update subjects from a CSV file."

    def add_arguments(self, parser):
        parser.add_argument("path", help="CSV file.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Validate and report without writing.")

    def handle(self, *args, **opts):
        path = opts["path"]
        with open(path, "rb") as fh:
            try:
                rows = imp.read_rows(fh.read())
            except imp.ImportFileError as exc:
                raise CommandError(f"{path}: {exc}")

        results = imp.plan(rows)
        summary = imp.summarise(results)
        for r in results:
            if r.errors:
                self.stdout.write(self.style.ERROR(
                    f"row {r.line} [{r.code or '-'}]: {'; '.join(r.errors)}"
                ))
        for s in summary["new_semesters"]:
            self.stdout.write(f"new semester: {s}")
        self.stdout.write(
            f"create {summary['create']}, update {summary['update']}, "
            f"unchanged {summary['unchanged']}, errors {summary['error']} "
            f"(of {summary['total']})"
        )
        if summary["error"]:
            raise CommandError("Errors found — nothing was written.")
        if opts["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run — nothing written."))
            return
        imp.apply(results)
        self.stdout.write(self.style.SUCCESS("Imported."))
