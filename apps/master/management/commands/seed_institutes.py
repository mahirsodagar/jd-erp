"""Seed the institute master list and the letterhead printed on the fee
receipt and the fee undertaking.

Letterhead values are transcribed from the legacy PHP, which hard-codes
them per institute in `JD_ERP/admissions/save.php` (the `$address`,
`$src` and `$schoolname` branches around the invoice and undertaking
templates). The logos are the same two files that PHP serves.

Two things this deliberately does NOT do:

- It never overwrites a value someone has edited. Finance owns these
  fields through Master -> Institutes; the seed only fills blanks, so
  re-running after an address change is safe.
- It seeds the *corporate* address only. The legacy templates also swap
  in a Goa block with its own GSTIN when the paying campus is Goa
  (`$paycampus == "2"`), which needs letterhead on Campus, not
  Institute — see the note in the class docstring.
"""

from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from apps.master.models import Institute

#: Bundled alongside this app so a deploy has the artwork — and the
#: student handbooks — without anyone having to upload them first.
_ASSETS = Path(__file__).resolve().parents[2] / "seed_assets"

#: Institute files seeded from `seed_assets`: (spec key, model field).
#: Each follows the same rule as the letterhead text — attached only
#: when the field is still empty, or always with --force.
_FILES = (("logo", "logo"), ("handbook", "handbook_pdf"))

INSTITUTES = [
    {
        "code": "JDIFT",
        "name": "JD Institute of Fashion Technology",
        "logo": "jdift-logo.png",
        # 2026 JDI Student Handbook (diploma / PG / short-term courses).
        "handbook": "jdift-student-handbook.pdf",
        # JDI prints the address under the logo, left-aligned.
        "letterhead_placement": Institute.LetterheadPlacement.LEFT,
        "letterhead_title": "Corporate Center",
        "address": "#40, Swan house, 4th cross,\n"
                   "Residency Road, Banglore-560025",
        "phone": "+91 99019 99903",
        "email": "jdfashion@jdindia.com",
        "gstin": "29AAEPD3991M2Z8",
        "payee_name": "JD INSTITUTE OF FASHION TECHNOLOGY",
    },
    {
        "code": "JDSD",
        "name": "JD School of Design",
        "logo": "jdsd-logo.png",
        # 2026 JDSD Student Handbook (degree / master's programmes).
        "handbook": "jdsd-student-handbook.pdf",
        # JDSD prints it opposite the logo, right-aligned.
        "letterhead_placement": Institute.LetterheadPlacement.RIGHT,
        "letterhead_title": "Corporate Center",
        "address": "#No.18, Edward House,\n"
                   "Brigade Road, Bangalore - 560001",
        "phone": "+91 99019 99903",
        "email": "jdfashion@jdindia.com",
        "gstin": "29AAATJ5101D1Z4",
        # Cheques go to the trust, not the school — as in the PHP.
        "payee_name": "JD Educational Trust",
    },
]


class Command(BaseCommand):
    """Idempotent. Fills only what is still blank, unless --force.

    NOTE: receipts raised at the Goa campus should carry the Goa address
    and GSTIN 30AAATJ5101D1ZL, which the legacy PHP swaps in per campus.
    Our letterhead lives on Institute, so Goa currently prints the
    Bangalore block. Moving it to Campus is a separate change.
    """

    help = ("Seed institutes and the letterhead printed on receipts and "
            "Fee Payment Schedules. Idempotent; will not clobber edited values.")

    def add_arguments(self, parser):
        parser.add_argument(
            "--force", action="store_true",
            help="Overwrite existing letterhead values, logos and handbooks "
                 "too. Use only to reset an institute back to the bundled "
                 "defaults.",
        )

    def handle(self, *args, **opts):
        force = opts["force"]
        verbose = opts.get("verbosity", 1) > 0
        created_n = filled_n = file_n = 0

        for spec in INSTITUTES:
            spec = dict(spec)
            code = spec.pop("code")
            asset_files = {field: spec.pop(key) for key, field in _FILES}
            name = spec.pop("name")

            institute, created = Institute.objects.get_or_create(
                code=code, defaults={"name": name},
            )
            created_n += int(created)

            # `letterhead_placement` always holds one of two choices, so
            # "still blank" can't identify an unconfigured institute.
            # The address does: when it is empty this letterhead has
            # never been set up, and the whole block gets seeded —
            # placement included. After that, only genuinely empty
            # fields are filled, so an edited placement survives.
            unconfigured = force or not institute.address

            changed = []
            for field, value in spec.items():
                if unconfigured or not getattr(institute, field):
                    setattr(institute, field, value)
                    changed.append(field)
            if changed:
                institute.save(update_fields=changed)
                filled_n += 1

            for field, filename in asset_files.items():
                if not force and getattr(institute, field):
                    continue
                path = _ASSETS / filename
                if path.is_file():
                    getattr(institute, field).save(
                        filename, ContentFile(path.read_bytes()), save=True,
                    )
                    file_n += 1
                else:
                    # Always worth saying: without the logo the document
                    # silently prints the institute name instead, and
                    # without the handbook "Send handbook" is refused.
                    self.stdout.write(self.style.WARNING(
                        f"{code}: {field} asset missing at {path}",
                    ))

            if verbose:
                self.stdout.write(
                    f"{code}: {'created' if created else 'updated'}"
                    + (f", set {', '.join(changed)}" if changed else
                       ", letterhead already set")
                )

        if verbose:
            self.stdout.write(self.style.SUCCESS(
                f"{len(INSTITUTES)} institutes ({created_n} created), "
                f"{filled_n} letterheads filled, {file_n} files "
                f"(logos/handbooks) attached."
            ))
