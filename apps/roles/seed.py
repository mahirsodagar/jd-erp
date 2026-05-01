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

    # Module E.1 — Admissions + new masters
    ("master", "master.academicyear.manage", "Manage academic years"),
    ("master", "master.degree.manage", "Manage degrees"),
    ("master", "master.course.manage", "Manage courses"),
    ("master", "master.semester.manage", "Manage semesters"),
    ("master", "master.batch.manage", "Manage batches"),

    ("admissions", "admissions.student.create", "Create students (promote leads)"),
    ("admissions", "admissions.student.view", "View students in own campus(es)"),
    ("admissions", "admissions.student.view_all_campuses", "View students across all campuses"),
    ("admissions", "admissions.student.edit", "Edit student records (HR)"),
    ("admissions", "admissions.student.promote", "Move students between status / batches"),
    ("admissions", "admissions.document.manage", "Upload / delete student documents"),
    ("admissions", "admissions.enrollment.manage", "Create / edit enrollments"),

    # Module E.2 — Fees
    ("master", "master.feetemplate.manage", "Manage fee templates"),
    ("fees", "fees.installment.manage", "Create / edit per-student installments"),
    ("fees", "fees.receipt.create", "Record fee payments"),
    ("fees", "fees.receipt.view", "View receipts in own campus(es)"),
    ("fees", "fees.receipt.view_all", "View receipts across all campuses"),
    ("fees", "fees.receipt.edit", "Correct posted receipts"),
    ("fees", "fees.receipt.cancel", "Cancel posted receipts"),
    ("fees", "fees.concession.request", "Raise concession requests"),
    ("fees", "fees.concession.approve", "Approve / reject concession requests"),

    # Module F — Lead Management Hardening
    ("leads", "leads.pool.manage", "Manage counsellor pools"),
    ("leads", "leads.escalation.receive", "Receive escalation alerts (managers)"),
    ("leads", "leads.report.view", "View lead reports / dashboards"),
    ("notifications", "notifications.template.manage", "Manage notification templates"),
    ("notifications", "notifications.dispatch.view", "View notification dispatch log"),

    # Module G.1 — Course Scheduling
    ("master", "master.subject.manage", "Manage subjects"),
    ("master", "master.classroom.manage", "Manage classrooms"),
    ("master", "master.timeslot.manage", "Manage time slots"),
    ("academics", "academics.schedule.manage", "Create / edit class schedule"),
    ("academics", "academics.schedule.view_all", "View schedules across all campuses"),

    # Module G.2 — Attendance
    ("academics", "academics.attendance.mark", "Mark attendance (non-instructor)"),
    ("academics", "academics.attendance.freeze", "Freeze / unfreeze attendance"),
    ("academics", "academics.attendance.edit_frozen", "Edit attendance after freeze"),
    ("academics", "academics.attendance.view_report", "View attendance reports across campuses"),

    # Module G.3 — Assignments + Marks
    ("academics", "academics.assignment.create", "Create / edit assignments"),
    ("academics", "academics.assignment.grade", "Grade any submission (HOD override)"),
    ("academics", "academics.assignment.manage_any", "Edit / delete any assignment"),
    ("academics", "academics.marks.enter", "Enter / edit draft marks"),
    ("academics", "academics.marks.publish", "Publish / unpublish marks"),
    ("academics", "academics.marks.edit_published", "Edit published marks"),
    ("academics", "academics.transcript.view_any", "View any student's transcript"),
    ("academics", "academics.transcript.view_drafts", "Include unpublished marks in transcripts"),

    # Module G.5 — Certificates + Alumni
    ("academics", "academics.certificate.issue", "Issue / reject certificates"),
    ("academics", "academics.certificate.override_eligibility", "Issue ignoring eligibility"),
    ("academics", "academics.certificate.view_all", "View any student's certificates"),
    ("academics", "academics.certificate.request_for_others", "Raise certificate requests for others"),
    ("academics", "academics.alumni.view_all", "View all alumni records"),
    ("academics", "academics.alumni.manage", "Edit any alumni record"),

    # Module G.4 — Online Tests
    ("academics", "academics.test.create", "Create / edit tests"),
    ("academics", "academics.test.publish", "Publish / close / map tests"),
    ("academics", "academics.test.review", "Review short-answer responses"),
    ("academics", "academics.test.view_all", "View all tests / attempts / reports"),
    ("academics", "academics.test.manage_any", "Edit / delete any test"),

    # Module H — Auditor / Reports
    ("audit", "audit.faculty_daily.view_all", "View all faculty daily reports"),
    ("audit", "audit.faculty_daily.submit_for_others", "Submit faculty daily on behalf of others"),
    ("audit", "audit.admin_daily.view_all", "View all admin daily reports"),
    ("audit", "audit.course_end.submit", "Submit course-end reports"),
    ("audit", "audit.course_end.view_all", "View all course-end reports"),
    ("audit", "audit.course_end.review", "HOD-review course-end reports"),
    ("audit", "audit.batch_mentor.view_all", "View all batch-mentor reports"),
    ("audit", "audit.batch_mentor.submit_for_others", "Submit batch-mentor on behalf"),
    ("audit", "audit.feedback.view_all", "View all student feedback"),
    ("audit", "audit.self_appraisal.view_all", "View all self-appraisals"),
    ("audit", "audit.self_appraisal.review", "Auditor reviews self-appraisals"),
    ("audit", "audit.compliance.view", "View compliance flags"),
    ("audit", "audit.compliance.flag", "Raise compliance flags"),
    ("audit", "audit.compliance.resolve", "Resolve compliance flags"),
    ("audit", "audit.report.consolidated", "View dashboards / consolidated reports"),
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
