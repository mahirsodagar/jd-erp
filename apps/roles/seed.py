"""Seed catalogue of permissions + default Admin role. Idempotent."""

from .models import Permission, Role


def _crud(module, base, noun):
    """Four granular CRUD permission rows for a resource.

    Mirrors the `perm_base` mechanism in `apps.accounts.permissions.HasPerm`,
    which maps HTTP method -> {view, add, edit, delete}.
    """
    return [
        (module, f"{base}.view", f"View {noun}"),
        (module, f"{base}.add", f"Add {noun}"),
        (module, f"{base}.edit", f"Edit {noun}"),
        (module, f"{base}.delete", f"Delete {noun}"),
    ]


# Permission catalogue. Add new entries as new modules ship.
CATALOGUE = [
    # Module A — Authentication & Access Control
    ("accounts", "accounts.user.view", "View users"),
    ("accounts", "accounts.user.add", "Add users"),
    ("accounts", "accounts.user.edit", "Edit users"),
    ("accounts", "accounts.user.delete", "Delete users"),
    *_crud("roles", "roles.role", "roles & permissions"),
    ("audit", "audit.log.view", "View audit logs"),

    # Module B — Lead Management / CRM
    *_crud("master", "master.campus", "campuses"),
    *_crud("master", "master.program", "programs"),
    *_crud("master", "master.source", "lead sources"),
    ("leads", "leads.lead.create", "Create leads"),
    ("leads", "leads.lead.view", "View own assigned leads"),
    ("leads", "leads.lead.view_all", "View all leads (managers)"),
    ("leads", "leads.lead.edit", "Edit lead fields"),
    ("leads", "leads.lead.reassign", "Reassign leads to another counselor"),
    ("leads", "leads.lead.change_status", "Change lead status"),
    *_crud("leads", "leads.followup", "follow-ups"),
    ("leads", "leads.communication.log", "Log communications"),

    # Module C — Employee Management / HR
    *_crud("master", "master.institute", "institutes"),
    *_crud("master", "master.state", "states"),
    *_crud("master", "master.city", "cities"),
    *_crud("employees", "employees.master", "departments & designations"),
    ("employees", "employees.employee.view", "View employees in own campus(es)"),
    ("employees", "employees.employee.view_all_campuses", "View all employees across campuses"),
    ("employees", "employees.employee.create", "Create employees"),
    ("employees", "employees.employee.edit", "Edit employees"),
    ("employees", "employees.employee.change_status", "Activate / deactivate employees"),
    ("employees", "employees.employee.delete", "Soft-delete employees"),
    ("employees", "employees.employee.add_in_any_campus", "Create employees outside own campus scope"),
    ("employees", "employees.employee.manage_deleted", "View / manage soft-deleted employees"),

    # Module D — Leaves
    *_crud("leaves", "leaves.type", "leave types"),
    *_crud("leaves", "leaves.session", "academic sessions"),
    ("leaves", "leaves.allocation.add", "Allocate leaves (HR)"),
    ("leaves", "leaves.allocation.delete", "Delete unconsumed allocations"),
    ("leaves", "leaves.application.view_all", "View all leave applications"),
    ("leaves", "leaves.application.approve_any", "Approve any leave (HR override)"),
    ("leaves", "leaves.application.override_balance", "Apply force=true past balance"),
    ("leaves", "leaves.application.backdate_apply", "Apply leaves with from_date in the past"),
    ("leaves", "leaves.compoff.view_all", "View all comp-off applications"),
    ("leaves", "leaves.compoff.approve_any", "Approve any comp-off (HR override)"),
    *_crud("leaves", "leaves.holiday", "holidays"),
    ("leaves", "leaves.report.view", "View leave reports for own campuses"),
    ("leaves", "leaves.report.view_all", "View leave reports across all campuses"),

    # Module E.1 — Admissions + new masters
    *_crud("master", "master.academicyear", "academic years"),
    *_crud("master", "master.degree", "degrees"),
    *_crud("master", "master.course", "courses"),
    *_crud("master", "master.semester", "semesters"),
    *_crud("master", "master.batch", "batches"),

    ("admissions", "admissions.student.create", "Create students (promote leads)"),
    ("admissions", "admissions.student.view", "View students in own campus(es)"),
    ("admissions", "admissions.student.view_all_campuses", "View students across all campuses"),
    ("admissions", "admissions.student.edit", "Edit student records (HR)"),
    ("admissions", "admissions.student.promote", "Move students between status / batches"),
    *_crud("admissions", "admissions.document", "student documents"),
    *_crud("admissions", "admissions.enrollment", "enrollments"),

    # Module E.2 — Fees
    *_crud("master", "master.feetemplate", "fee templates"),
    *_crud("fees", "fees.installment", "per-student installments"),
    ("fees", "fees.receipt.create", "Record fee payments"),
    ("fees", "fees.receipt.view", "View receipts in own campus(es)"),
    ("fees", "fees.receipt.view_all", "View receipts across all campuses"),
    ("fees", "fees.receipt.edit", "Correct posted receipts"),
    ("fees", "fees.receipt.cancel", "Cancel posted receipts"),
    ("fees", "fees.concession.request", "Raise concession requests"),
    ("fees", "fees.concession.approve", "Approve / reject concession requests"),

    # Module F — Lead Management Hardening
    *_crud("leads", "leads.pool", "counsellor pools"),
    ("leads", "leads.escalation.receive", "Receive escalation alerts (managers)"),
    ("leads", "leads.report.view", "View lead reports / dashboards"),

    # Entrance Exams (Leads pipeline)
    ("leads", "leads.exam.create", "Create / edit entrance exams"),
    ("leads", "leads.exam.publish", "Publish / close / map entrance exams"),
    ("leads", "leads.exam.review", "Review short-answer exam responses"),
    ("leads", "leads.exam.view_all", "View all entrance exams / attempts / reports"),
    ("leads", "leads.exam.edit_any", "Edit any entrance exam (not just own)"),
    ("leads", "leads.exam.delete_any", "Delete any entrance exam (not just own)"),
    *_crud("notifications", "notifications.template", "notification templates"),
    ("notifications", "notifications.dispatch.view", "View notification dispatch log"),

    # Module G.1 — Course Scheduling
    *_crud("master", "master.subject", "subjects"),
    *_crud("master", "master.classroom", "classrooms"),
    *_crud("master", "master.timeslot", "time slots"),
    ("academics", "academics.schedule.add", "Create class schedule entries"),
    ("academics", "academics.schedule.edit", "Edit class schedule entries"),
    ("academics", "academics.schedule.delete", "Delete class schedule entries"),
    ("academics", "academics.schedule.view_all", "View schedules across all campuses"),

    # Module G.2 — Attendance
    ("academics", "academics.attendance.mark", "Mark attendance (non-instructor)"),
    ("academics", "academics.attendance.freeze", "Freeze / unfreeze attendance"),
    ("academics", "academics.attendance.edit_frozen", "Edit attendance after freeze"),
    ("academics", "academics.attendance.view_report", "View attendance reports across campuses"),

    # Module G.3 — Assignments + Marks
    ("academics", "academics.assignment.create", "Create / edit assignments"),
    ("academics", "academics.assignment.grade", "Grade any submission (HOD override)"),
    ("academics", "academics.assignment.edit_any", "Edit any assignment (not just own)"),
    ("academics", "academics.assignment.delete_any", "Delete any assignment (not just own)"),
    ("academics", "academics.lesson.create", "Create / edit lesson plans"),
    ("academics", "academics.lesson.view_all", "View all lesson plans"),
    ("academics", "academics.lesson.edit_any", "Edit / review any lesson plan (not just own)"),
    ("academics", "academics.lesson.delete_any", "Delete any lesson plan (not just own)"),
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
    ("academics", "academics.alumni.edit", "Edit any alumni record"),
    ("academics", "academics.alumni.delete", "Delete any alumni record"),

    # Module G.4 — Online Tests
    ("academics", "academics.test.create", "Create / edit tests"),
    ("academics", "academics.test.publish", "Publish / close / map tests"),
    ("academics", "academics.test.review", "Review short-answer responses"),
    ("academics", "academics.test.view_all", "View all tests / attempts / reports"),
    ("academics", "academics.test.edit_any", "Edit any test (not just own)"),
    ("academics", "academics.test.delete_any", "Delete any test (not just own)"),

    # Module H — Auditor / Reports
    # Faculty daily report — auditors get read-only visibility of every
    # faculty's report here. Filling one's OWN report lives under the
    # Dashboard module (dashboard.daily_report.submit) instead.
    ("audit", "audit.faculty_daily.view_all", "View all faculty daily reports"),
    # Admin daily report — auditors get read-only view of everyone's here;
    # filling one's OWN lives under Dashboard (dashboard.admin_daily.submit).
    ("audit", "audit.admin_daily.view_all", "View all admin daily reports"),
    ("audit", "audit.course_end.submit", "Submit own course-end reports"),
    ("audit", "audit.course_end.view_all", "View all course-end reports"),
    ("audit", "audit.course_end.review", "HOD-review course-end reports"),
    ("audit", "audit.batch_mentor.view_all", "View all batch-mentor reports"),
    ("audit", "audit.batch_mentor.submit_for_others", "Submit batch-mentor on behalf"),
    # Zero-Hour report — filled under Academics, reviewed under Audit.
    ("academics", "academics.zero_hour.submit", "Fill / manage own 0-Hour reports"),
    ("audit", "audit.zero_hour.view_all", "View all 0-Hour reports"),
    ("audit", "audit.feedback.view_all", "View all student feedback"),
    ("audit", "audit.self_appraisal.view_own", "View own self-appraisal"),
    ("audit", "audit.self_appraisal.submit", "Submit own self-appraisal"),
    ("audit", "audit.self_appraisal.view_all", "View all self-appraisals"),
    ("audit", "audit.self_appraisal.review", "Auditor reviews self-appraisals"),
    ("audit", "audit.compliance.view", "View compliance flags"),
    ("audit", "audit.compliance.flag", "Raise compliance flags"),
    ("audit", "audit.compliance.resolve", "Resolve compliance flags"),
    ("audit", "audit.report.consolidated", "View dashboards / consolidated reports"),
    *_crud("audit", "audit.form", "audit forms"),
    ("audit", "audit.submission.view_all", "View all audit form submissions"),

    # Module — Personal Dashboard (self-service)
    ("dashboard", "dashboard.daily_report.submit", "Fill / manage own daily report"),
    ("dashboard", "dashboard.admin_daily.submit", "Fill / manage own admin daily report"),

    # Module HR — Relieving (exit workflow + experience letter)
    ("hr", "hr.relieving.submit_for_others", "Submit relieving on behalf of others"),
    ("hr", "hr.relieving.view_all", "View all relieving applications"),
    ("hr", "hr.relieving.finalize", "HR finalizes relieving + generates letters"),
    ("hr", "hr.relieving.override", "Override approval sequence (skip levels)"),

    # Student & Parent Portal
    *_crud("courseware", "courseware", "courseware topics"),
    ("student_leaves", "student_leaves.view_all", "View all student leave applications"),
    ("student_leaves", "student_leaves.decide", "Approve / reject student leaves"),
    ("student_documents", "student_documents.view_all", "View all student document requests"),
    ("student_documents", "student_documents.decide", "Approve / reject document requests"),
    *_crud("admissions", "admissions.parent", "parent accounts"),
]


def seed_permissions():
    keys = set()
    for module, key, label in CATALOGUE:
        Permission.objects.update_or_create(
            key=key,
            defaults={"module": module, "label": label},
        )
        keys.add(key)
    # Prune permissions dropped from the catalogue so re-seeding fully
    # reconciles the DB (e.g. retired faculty_daily scopes). The catalogue
    # is the single source of truth — admins never mint their own keys.
    stale = Permission.objects.exclude(key__in=keys)
    removed = stale.count()
    stale.delete()
    return removed


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


# Permission keys auto-granted to a new employee.
#
# The frontend sidebar gates each menu group on its module key being
# present in the user's `modules` list, which is derived from their
# permissions. So we grant the minimum set of perms whose presence
# unlocks the right sidebar groups for an everyday employee:
#
#   leaves.report.view     → "Leaves" group (Apply, My Leaves, Balances)
#   audit.course_end.submit → "Audit" group (so they can submit own
#                              Faculty Daily / Course-End / Self-Appraisal)
#
# All listed perms also gate at least one endpoint that the employee
# legitimately needs. Anything more sensitive (view_all, approve_any,
# manage) stays admin-only and is granted later from the Users page.
FACULTY_PERMISSION_KEYS = [
    "leaves.report.view",
    "audit.course_end.submit",
    # Fill their own daily report (Dashboard → Daily Report).
    "dashboard.daily_report.submit",
    # Their own self-appraisal (submit + view).
    "audit.self_appraisal.view_own",
    "audit.self_appraisal.submit",
]


def seed_faculty_role():
    """Baseline role assigned to every freshly-provisioned employee.

    The keys in `FACULTY_PERMISSION_KEYS` are intentionally minimal —
    HR grants extra access from the Users page when needed.
    """
    role, _ = Role.objects.get_or_create(
        name="Faculty",
        defaults={
            "description": (
                "Baseline access for employees: self-service leaves, "
                "personal timetable / attendance / tests / certificates, "
                "own daily reports, and tasks."
            ),
            "is_system": True,
        },
    )
    role.is_system = True
    role.description = role.description or (
        "Baseline access for employees: self-service leaves, "
        "personal timetable / attendance / tests / certificates, "
        "own daily reports, and tasks."
    )
    role.save(update_fields=["is_system", "description"])
    perms = Permission.objects.filter(key__in=FACULTY_PERMISSION_KEYS)
    role.permissions.set(perms)
    return role


def seed_all():
    seed_permissions()
    seed_admin_role()
    seed_faculty_role()
