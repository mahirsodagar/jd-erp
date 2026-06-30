"""Split combined `.manage` / `.manage_any` permissions into granular
view / add / edit / delete (and edit_any / delete_any) keys.

Every role that held an old combined key is granted ALL the new keys it
maps to, so no role loses access. The old Permission rows are then removed.
The Admin system role is re-synced to the full catalogue by
`seed_permissions` on deploy, and superusers bypass checks entirely.
"""

from django.db import migrations


# Resources that split into the full view/add/edit/delete set.
CRUD_BASES = [
    "roles.role",
    "master.campus", "master.program", "master.source",
    "master.institute", "master.state", "master.city",
    "master.academicyear", "master.degree", "master.course",
    "master.semester", "master.batch", "master.subject",
    "master.classroom", "master.timeslot", "master.feetemplate",
    "employees.master",
    "leaves.type", "leaves.session", "leaves.holiday",
    "notifications.template",
    "admissions.document", "admissions.enrollment", "admissions.parent",
    "fees.installment",
    "leads.followup", "leads.pool",
    "audit.form",
    "courseware",
]

# Bases whose `.manage_any` splits into edit_any / delete_any.
MANAGE_ANY_BASES = [
    "academics.lesson", "academics.assignment",
    "academics.test", "leads.exam",
]

# Partial / bespoke splits.
SPECIAL = {
    # `accounts.user.view` already existed; only add/edit/delete are new.
    "accounts.user.manage": [
        "accounts.user.add", "accounts.user.edit", "accounts.user.delete",
    ],
    "academics.alumni.manage": [
        "academics.alumni.edit", "academics.alumni.delete",
    ],
    "academics.schedule.manage": [
        "academics.schedule.add", "academics.schedule.edit",
        "academics.schedule.delete",
    ],
}


def _build_map():
    mapping = {}
    for base in CRUD_BASES:
        mapping[f"{base}.manage"] = [
            f"{base}.view", f"{base}.add", f"{base}.edit", f"{base}.delete",
        ]
    for base in MANAGE_ANY_BASES:
        mapping[f"{base}.manage_any"] = [
            f"{base}.edit_any", f"{base}.delete_any",
        ]
    mapping.update(SPECIAL)
    return mapping


OLD_TO_NEW = _build_map()


def _labels():
    """key -> (module, label) for every new key, taken from the catalogue."""
    from apps.roles.seed import CATALOGUE
    return {key: (module, label) for module, key, label in CATALOGUE}


def forwards(apps, schema_editor):
    Permission = apps.get_model("roles", "Permission")
    meta = _labels()

    # Ensure every new permission row exists.
    new_rows = {}
    for new_keys in OLD_TO_NEW.values():
        for nk in new_keys:
            module, label = meta.get(nk, (nk.split(".")[0], nk))
            row, _ = Permission.objects.get_or_create(
                key=nk, defaults={"module": module, "label": label},
            )
            new_rows[nk] = row

    # Re-grant + drop the old combined rows.
    for old_key, new_keys in OLD_TO_NEW.items():
        try:
            old = Permission.objects.get(key=old_key)
        except Permission.DoesNotExist:
            continue
        grants = [new_rows[nk] for nk in new_keys]
        for role in old.roles.all():
            role.permissions.add(*grants)
        old.delete()


def backwards(apps, schema_editor):
    Permission = apps.get_model("roles", "Permission")

    # Recreate the old combined rows and grant them back to any role that
    # holds one of the granular keys. New granular rows are left in place
    # (harmless); seed_permissions will reconcile the catalogue.
    old_meta = {
        "accounts.user.manage": ("accounts", "Manage users"),
        "academics.alumni.manage": ("academics", "Edit any alumni record"),
        "academics.schedule.manage": ("academics", "Create / edit class schedule"),
    }
    for base in CRUD_BASES:
        old_meta[f"{base}.manage"] = (base.split(".")[0], f"Manage {base}")
    for base in MANAGE_ANY_BASES:
        old_meta[f"{base}.manage_any"] = (base.split(".")[0], f"Manage any {base}")

    for old_key, new_keys in OLD_TO_NEW.items():
        module, label = old_meta[old_key]
        old, _ = Permission.objects.get_or_create(
            key=old_key, defaults={"module": module, "label": label},
        )
        role_ids = set(
            Permission.objects.filter(key__in=new_keys)
            .values_list("roles__id", flat=True)
        )
        role_ids.discard(None)
        if role_ids:
            Role = apps.get_model("roles", "Role")
            for role in Role.objects.filter(id__in=role_ids):
                role.permissions.add(old)


class Migration(migrations.Migration):

    dependencies = [
        ("roles", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
