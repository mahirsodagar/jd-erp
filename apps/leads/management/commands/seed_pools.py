from django.core.management.base import BaseCommand

from apps.leads.models import CounsellorPool


POOLS = [
    ("Long Course Pool", CounsellorPool.Category.REGULAR),
    ("Short Course Pool", CounsellorPool.Category.SHORT),
    ("New Course Pool", CounsellorPool.Category.NEW),
]


class Command(BaseCommand):
    help = "Seed the three counsellor pools (Regular / Short / New). Idempotent."

    def handle(self, *args, **opts):
        for name, category in POOLS:
            CounsellorPool.objects.update_or_create(
                category=category,
                defaults={"name": name, "is_active": True},
            )
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(POOLS)} counsellor pools."))
