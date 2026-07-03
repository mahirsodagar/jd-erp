from django.core.management.base import BaseCommand

from apps.roles.seed import seed_admin_role, seed_faculty_role, seed_permissions


class Command(BaseCommand):
    help = (
        "Seed the permission catalogue (creating new keys and pruning retired "
        "ones) + refresh the default Admin / Faculty roles. Idempotent."
    )

    def handle(self, *args, **opts):
        removed = seed_permissions()
        seed_admin_role()
        seed_faculty_role()
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded permissions (pruned {removed} retired) "
                "and refreshed Admin + Faculty roles."
            )
        )
