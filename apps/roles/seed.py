"""Seed catalogue of permissions + default Admin role. Idempotent."""

from .models import Permission, Role


# Permission catalogue. Add new entries as new modules ship.
CATALOGUE = [
    # Module A — Authentication & Access Control
    ("accounts", "accounts.user.manage", "Manage users"),
    ("accounts", "accounts.user.view", "View users"),
    ("roles", "roles.role.manage", "Manage roles & permissions"),
    ("audit", "audit.log.view", "View audit logs"),

    # Module B — Lead Management / CRM
    ("master", "master.campus.manage", "Manage campuses"),
    ("master", "master.program.manage", "Manage programs"),
    ("master", "master.source.manage", "Manage lead sources"),
    ("leads", "leads.lead.create", "Create leads"),
    ("leads", "leads.lead.view", "View own assigned leads"),
    ("leads", "leads.lead.view_all", "View all leads (managers)"),
    ("leads", "leads.lead.edit", "Edit lead fields"),
    ("leads", "leads.lead.reassign", "Reassign leads to another counselor"),
    ("leads", "leads.lead.change_status", "Change lead status"),
    ("leads", "leads.followup.manage", "Add/edit follow-ups"),
    ("leads", "leads.communication.log", "Log communications"),

    # Module C — Employee Management / HR
    ("master", "master.institute.manage", "Manage institutes"),
    ("master", "master.state.manage", "Manage states"),
    ("master", "master.city.manage", "Manage cities"),
    ("employees", "employees.master.manage", "Manage departments & designations"),
    ("employees", "employees.employee.view", "View employees in own campus(es)"),
    ("employees", "employees.employee.view_all_campuses", "View all employees across campuses"),
    ("employees", "employees.employee.create", "Create employees"),
    ("employees", "employees.employee.edit", "Edit employees"),
    ("employees", "employees.employee.change_status", "Activate / deactivate employees"),
    ("employees", "employees.employee.delete", "Soft-delete employees"),
    ("employees", "employees.employee.add_in_any_campus", "Create employees outside own campus scope"),
    ("employees", "employees.employee.manage_deleted", "View / manage soft-deleted employees"),

    # Module D — Leaves
    ("leaves", "leaves.type.manage", "Manage leave-type catalogue"),
    ("leaves", "leaves.session.manage", "Manage academic sessions"),
    ("leaves", "leaves.allocation.add", "Allocate leaves (HR)"),
    ("leaves", "leaves.allocation.delete", "Delete unconsumed allocations"),
    ("leaves", "leaves.application.view_all", "View all leave applications"),
    ("leaves", "leaves.application.approve_any", "Approve any leave (HR override)"),
    ("leaves", "leaves.application.override_balance", "Apply force=true past balance"),
    ("leaves", "leaves.application.backdate_apply", "Apply leaves with from_date in the past"),
    ("leaves", "leaves.compoff.view_all", "View all comp-off applications"),
    ("leaves", "leaves.compoff.approve_any", "Approve any comp-off (HR override)"),
    ("leaves", "leaves.holiday.manage", "Manage the holiday calendar"),
    ("leaves", "leaves.report.view", "View leave reports for own campuses"),
    ("leaves", "leaves.report.view_all", "View leave reports across all campuses"),
]


def seed_permissions():
    for module, key, label in CATALOGUE:
        Permission.objects.update_or_create(
            key=key,
            defaults={"module": module, "label": label},
        )


def seed_admin_role():
    role, _ = Role.objects.get_or_create(
        name="Admin",
        defaults={
            "description": "Full access — assign sparingly.",
            "is_system": True,
        },
    )
    role.is_system = True
    role.save(update_fields=["is_system"])
    role.permissions.set(Permission.objects.all())
    return role


def seed_all():
    seed_permissions()
    seed_admin_role()
