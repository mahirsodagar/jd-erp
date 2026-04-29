from django.core.management.base import BaseCommand

from apps.master.models import Degree


DEGREES = [
    ("UG", "Undergraduate"),
    ("PG", "Postgraduate"),
    ("DIP", "Diploma"),
    ("CERT", "Certificate"),
]


class Command(BaseCommand):
    help = "Seed the degree master list. Idempotent."

    def handle(self, *args, **opts):
        for code, name in DEGREES:
            Degree.objects.update_or_create(
                code=code,
                defaults={"name": name},
            )
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(DEGREES)} degrees."))
