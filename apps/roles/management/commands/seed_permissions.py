from django.core.management.base import BaseCommand

from apps.roles.seed import seed_admin_role, seed_faculty_role, seed_permissions


class Command(BaseCommand):
    help = (
        "Seed the permission catalogue (creating new keys and pruning retired "
        "ones) + refresh the default Admin / Faculty roles. Idempotent."
    )

    def handle(self, *args, **opts):
        # Reseeding alone strips access on an existing install: the
        # granular split introduced narrow keys that no role holds yet,
        # and it prunes retired ones. `migrate_permissions` seeds AND
        # carries roles across; use this command only on a fresh DB.
        self.stdout.write(self.style.WARNING(
            "Note: on an existing database use `migrate_permissions` "
            "instead — it seeds and backfills roles. This command also "
            "resets the Faculty role to its baseline keys.",
        ))
        removed = seed_permissions()
        seed_admin_role()
        seed_faculty_role()
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded permissions (pruned {removed} retired) "
                "and refreshed Admin + Faculty roles."
            )
        )
