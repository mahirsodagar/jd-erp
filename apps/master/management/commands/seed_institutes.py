from django.core.management.base import BaseCommand

from apps.master.models import Institute


INSTITUTES = [
    ("JD Institute of Fashion Technology", "JDIFT"),
    ("JD School of Design", "JDSD"),
]


class Command(BaseCommand):
    help = "Seed the institute master list. Idempotent."

    def handle(self, *args, **opts):
        for name, code in INSTITUTES:
            Institute.objects.update_or_create(
                code=code,
                defaults={"name": name},
            )
        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(INSTITUTES)} institutes."
        ))
