from django.core.management.base import BaseCommand

from apps.roles.seed import seed_all


class Command(BaseCommand):
    help = "Seed permission catalogue + default Tenant Admin role. Idempotent."

    def handle(self, *args, **opts):
        seed_all()
        self.stdout.write(self.style.SUCCESS("Seeded permissions and admin role."))
