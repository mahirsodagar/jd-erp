"""Reseed the catalogue and carry existing roles across the granular split.

Run this INSTEAD of `seed_permissions` when deploying the granular
permission work. Plain reseeding would silently strip access: the new
narrow keys exist but no role holds them, and retired keys such as
`leads.report.view` are pruned outright.

Order matters:

  1. snapshot every role's current key set (before anything is pruned),
  2. seed the catalogue + refresh the Admin role,
  3. grant each role the new keys implied by its old ones.

`seed_faculty_role()` is deliberately NOT called — it resets the Faculty
role's permissions to the baseline list and would discard site-specific
customisation. Pass --with-faculty if you actually want that reset.

Only ever adds permissions. Safe to re-run; a second pass reports zero
changes. Use --dry-run first.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.roles.migrate_map import ALL_OF_RULES, EVERY_ROLE, RULES
from apps.roles.models import Permission, Role
from apps.roles.seed import seed_admin_role, seed_faculty_role, seed_permissions


class Command(BaseCommand):
    help = (
        "Seed the permission catalogue and backfill existing roles so the "
        "granular split does not remove access. Idempotent."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would change without writing anything.",
        )
        parser.add_argument(
            "--with-faculty", action="store_true",
            help="Also reset the Faculty role to its baseline key list "
                 "(discards customisation — off by default).",
        )

    def handle(self, *args, **opts):
        dry = opts["dry_run"]

        # 1. Snapshot BEFORE seeding — retired keys vanish in step 2.
        before = {
            role.id: set(role.permissions.values_list("key", flat=True))
            for role in Role.objects.prefetch_related("permissions")
        }
        names = dict(Role.objects.values_list("id", "name"))
        if not before:
            self.stdout.write(self.style.WARNING("No roles found — nothing to migrate."))
            return

        with transaction.atomic():
            # 2. Seed. Admin is refreshed to "everything"; Faculty only on
            #    request, since reseeding it discards customisation.
            #    A dry run seeds too, then rolls the whole transaction
            #    back — otherwise the new keys wouldn't exist yet and
            #    every rule would look unresolvable.
            pruned = seed_permissions()
            seed_admin_role()
            if opts["with_faculty"]:
                seed_faculty_role()

            # 3. Backfill.
            by_key = {p.key: p for p in Permission.objects.all()}
            missing_keys: set[str] = set()
            total_added = 0
            report: list[tuple[str, list[str]]] = []

            for role in Role.objects.prefetch_related("permissions"):
                held_before = before.get(role.id, set())
                if not held_before:
                    # A role with no permissions had no access to preserve.
                    continue
                held_now = set(role.permissions.values_list("key", flat=True))

                wanted = {
                    new_key
                    for new_key, old_keys in RULES.items()
                    if held_before.intersection(old_keys)
                }
                # AND-rules: every listed old key must have been held.
                wanted.update(
                    new_key
                    for new_key, old_keys in ALL_OF_RULES.items()
                    if held_before.issuperset(old_keys)
                )
                wanted.update(EVERY_ROLE)
                to_add = sorted(wanted - held_now)
                if not to_add:
                    continue

                resolved = []
                for key in to_add:
                    perm = by_key.get(key)
                    if perm is None:
                        missing_keys.add(key)
                        continue
                    resolved.append(perm)

                if resolved:
                    role.permissions.add(*resolved)
                total_added += len(resolved)
                report.append((names.get(role.id, f"#{role.id}"),
                               [p.key for p in resolved]))

            if dry:
                transaction.set_rollback(True)

        # --- Output ----------------------------------------------------
        prefix = "[dry-run] " if dry else ""
        if not report:
            self.stdout.write(self.style.SUCCESS(
                f"{prefix}Nothing to backfill — every role already holds "
                "the keys implied by its old ones.",
            ))
        for role_name, keys in report:
            self.stdout.write(f"\n{prefix}{role_name}  (+{len(keys)})")
            for key in keys:
                self.stdout.write(f"    + {key}")

        if missing_keys:
            self.stdout.write(self.style.WARNING(
                f"\n{prefix}{len(missing_keys)} mapped key(s) are not in the "
                "catalogue and were skipped:",
            ))
            for key in sorted(missing_keys):
                self.stdout.write(self.style.WARNING(f"    ? {key}"))

        self.stdout.write(self.style.SUCCESS(
            f"\n{prefix}Done — {total_added} grant(s) across "
            f"{len(report)} role(s); {pruned} retired key(s) pruned.",
        ))
        if dry:
            self.stdout.write(
                "Re-run without --dry-run to apply. Users must log out and "
                "back in before the new keys reach their session.",
            )
