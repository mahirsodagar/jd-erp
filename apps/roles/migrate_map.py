"""Old-key -> new-key mapping for the granular-permission rollout.

Between the Dashboard, Leads, Admission, Fee Collection and LMS passes,
a lot of behaviour that used to ride on one broad key was split onto
several narrow ones. Re-seeding alone would therefore *remove* access:
the new keys exist but nobody holds them, and a few old keys
(`leads.report.view`, `admissions.document.edit`, …) get pruned outright.

`RULES` maps each new key to the old keys that used to imply it. A role
holding ANY of the listed old keys is granted the new one. The mapping
is deliberately generous — it reproduces the access a role effectively
had before the split, and an admin can then take away what they don't
want. It never removes anything.

Consumed by `manage.py migrate_permissions`, which snapshots the current
role -> key sets *before* seeding (so pruned keys are still visible) and
applies these rules afterwards.
"""

#: new key -> old keys that used to grant the same ability.
#: Order is presentational only; lookups are set-based.
RULES: dict[str, tuple[str, ...]] = {

    # --- Module 1: Dashboard -------------------------------------------
    # Sessions and the My Work feed are self-service, so every role that
    # had any access at all keeps them (see EVERY_ROLE below).
    "dashboard.sessions.view_all": ("academics.schedule.view_all",),
    "dashboard.leads.view": ("leads.lead.view", "leads.lead.view_all"),
    "dashboard.enrollments.view": (
        "admissions.enrollment.view", "admissions.enrollment.add",
        "admissions.enrollment.edit",
    ),
    "dashboard.students.view": ("admissions.student.view",),
    # Engagement mixes lead, enrolment and student figures — a
    # manager-level view, so key it off the cross-campus lead grant.
    "dashboard.engagement.view": (
        "leads.lead.view_all", "leads.report.view",
    ),

    # --- Module 2: Leads -----------------------------------------------
    "leads.lead.view_history": ("leads.lead.view", "leads.lead.view_all"),
    "leads.lead.promote": ("admissions.student.create",),
    # The five outreach actions all used to be `leads.communication.log`.
    "leads.send.fee_link": ("leads.communication.log",),
    "leads.send.application_link": ("leads.communication.log",),
    "leads.send.welcome": ("leads.communication.log",),
    "leads.bulk_message.send": ("leads.communication.log",),
    "leads.application_fee.record": ("leads.communication.log",),
    "leads.application_fee.clear": ("leads.communication.log",),
    # Closing / reopening the student's form was `leads.lead.edit`.
    "leads.application_form.lock": ("leads.lead.edit",),
    # Pool reads were open to any authenticated user; give the key to
    # anyone who could already write pools.
    "leads.pool.view": (
        "leads.pool.add", "leads.pool.edit", "leads.pool.delete",
    ),
    # `leads.report.view` is pruned by the reseed — hence the snapshot.
    "leads.report.funnel": ("leads.report.view",),
    "leads.report.leaderboard": ("leads.report.view",),
    "leads.report.revenue": ("leads.report.view",),
    "leads.report.quality": ("leads.report.view",),
    "leads.exam.view_lead_attempts": (
        "leads.exam.view_all", "leads.exam.create", "leads.lead.view",
        "leads.lead.view_all",
    ),

    # --- Module 3.1: Admission > Students ------------------------------
    "admissions.student.view_sensitive": ("admissions.student.view",),
    "admissions.student.view_education": ("admissions.student.view",),
    "admissions.student.view_attendance": ("admissions.student.view",),
    "admissions.student.view_fees": (
        "fees.receipt.view", "fees.receipt.view_all",
    ),
    "admissions.student.view_remarks": ("admissions.student.view",),
    "admissions.document.view": ("admissions.student.view",),
    "admissions.enrollment.view": ("admissions.student.view",),
    "admissions.enrollment.send_undertaking": ("admissions.student.view",),
    "admissions.parent.view": ("admissions.parent.view", "admissions.parent.add"),
    # Everything below used to be covered by `admissions.student.edit`.
    "admissions.student.transfer": ("admissions.student.edit",),
    "admissions.student.set_registration_no": ("admissions.student.edit",),
    "admissions.student.add_remark": ("admissions.student.edit",),
    "admissions.student.send_credentials": ("admissions.student.edit",),
    "admissions.student.send_handbook": ("admissions.student.edit",),
    # Batch promotion accepted `enrollment.edit` as an alternative.
    "admissions.student.promote": (
        "admissions.student.promote", "admissions.enrollment.edit",
    ),

    # --- Module 3.2: Admission > Fee Collection ------------------------
    "fees.installment.view": ("fees.receipt.view", "fees.receipt.view_all"),
    "fees.otherfee.view": ("fees.receipt.view", "fees.receipt.view_all"),
    "fees.otherfee.add": ("fees.installment.add",),
    "fees.otherfee.delete": ("fees.installment.delete",),
    "fees.balance.view": ("fees.receipt.view", "fees.receipt.view_all"),

    # --- Modules 3.3 / 3.4: Fee + Concession Reports -------------------
    "fees.report.view": ("fees.receipt.view", "fees.receipt.view_all"),
    "fees.concession_report.view": (
        "fees.concession.approve", "fees.concession.request",
    ),

    # --- Module 4: LMS -------------------------------------------------
    # The assignment / lesson / test lists were ungated or owner-scoped;
    # grant the new view key to anyone holding a key in that area.
    "academics.assignment.view": (
        "academics.assignment.create", "academics.assignment.grade",
        "academics.assignment.edit_any", "academics.assignment.delete_any",
    ),
    "academics.assignment.view_all_campuses": ("academics.schedule.view_all",),
    "academics.assignment.view_submissions": ("academics.assignment.grade",),
    "academics.lesson.view": (
        "academics.lesson.create", "academics.lesson.view_all",
        "academics.lesson.edit_any", "academics.lesson.delete_any",
    ),
    "academics.marks.view": (
        "academics.marks.enter", "academics.marks.publish",
    ),
    "academics.marks.unpublish": ("academics.marks.publish",),
    "academics.test.view": (
        "academics.test.create", "academics.test.view_all",
        "academics.test.publish", "academics.test.review",
        "academics.test.edit_any", "academics.test.delete_any",
    ),

    # --- Module 5: Slot ------------------------------------------------
    # The timetable was readable by anyone authenticated, so key the new
    # read permission off holding any schedule permission at all.
    "academics.schedule.view": (
        "academics.schedule.add", "academics.schedule.edit",
        "academics.schedule.delete", "academics.schedule.view_all",
    ),
    # Forcing past a classroom clash needed nothing beyond add/edit.
    "academics.schedule.override_conflict": (
        "academics.schedule.add", "academics.schedule.edit",
    ),

    # --- Module 6.2: Academics > Attendance ----------------------------
    # The roster was readable by anyone authenticated; give the key to
    # everyone who already held an attendance permission.
    "academics.attendance.view_roster": (
        "academics.attendance.mark", "academics.attendance.freeze",
        "academics.attendance.edit_frozen",
        "academics.attendance.view_report",
    ),
    # Absence alerts rode on the mark permission.
    "academics.attendance.notify_absent": ("academics.attendance.mark",),
    "academics.attendance.view_instructor_log": (
        "academics.attendance.view_report",
    ),
    # `view_report` holders could already open any batch's report.
    "academics.attendance.view_all_campuses": (
        "academics.attendance.view_report",
    ),

    # --- Module 6.3: Academics > Batch Report --------------------------
    # The roster and the institute-wide scope both used to come free
    # with `batch_report.view`. Note the roster's personal columns now
    # additionally require `admissions.student.view_sensitive`, which is
    # deliberately NOT backfilled from here — that key is granted from
    # the Students module on its own merits.
    "academics.batch_report.view_roster": ("academics.batch_report.view",),
    "academics.batch_report.view_all_campuses": (
        "academics.batch_report.view",
    ),

    # --- Module 6.4: Academics > Closing Report ------------------------
    # The report was institute-wide for anyone who could read it.
    "academics.closing_report.view_all_campuses": (
        "academics.closing_report.view",
    ),

    # --- Module 6.5: Academics > Records -------------------------------
    # Rejecting a certificate request used to be part of issuing it.
    "academics.certificate.reject": ("academics.certificate.issue",),
    # Graduating accepted either key depending on which endpoint you
    # hit — the per-enrolment one wanted `admissions.enrollment.edit`,
    # the batch one `academics.certificate.issue`. Preserve both.
    "academics.certificate.graduate": (
        "admissions.enrollment.edit", "academics.certificate.issue",
    ),
    # Certificates and alumni were institute-wide for anyone who could
    # read them.
    "academics.certificate.view_all_campuses": (
        "academics.certificate.view_all",
    ),
    "academics.alumni.view_all_campuses": ("academics.alumni.view_all",),

    # --- Module 6.6: Academics > 0-Hour Form ---------------------------
    # Deleting your own report used to come with `submit`. The *_any
    # keys are NOT backfilled: editing or deleting someone else's report
    # was superuser-only, so nobody held a permission that implied it.
    "academics.zero_hour.delete": ("academics.zero_hour.submit",),

    # --- Module 6.7: Academics > Student Leaves ------------------------
    # `student_leaves.decide` covered both outcomes and is retired.
    "student_leaves.approve": ("student_leaves.decide",),
    "student_leaves.reject": ("student_leaves.decide",),

    # --- Module 6.8: Academics > Document Requests ---------------------
    # `student_documents.decide` covered both outcomes and is retired.
    # The old `view_all` was the only read key, so it grants both halves
    # of the new campus-scoped pair.
    "student_documents.view": ("student_documents.view_all",),
    "student_documents.approve": ("student_documents.decide",),
    "student_documents.reject": ("student_documents.decide",),

    # --- Module 6.9: Academics > Appointments --------------------------
    # `appointments.decide` covered confirm, decline and complete alike
    # and is retired.
    "appointments.confirm": ("appointments.decide",),
    "appointments.decline": ("appointments.decide",),
    "appointments.complete": ("appointments.decide",),

    # --- Module 7: HR --------------------------------------------------
    # Department / designation reads were open to any authenticated
    # user, so grant the (pre-existing but unenforced) view key to
    # anyone who could already write them.
    "employees.master.view": (
        "employees.master.add", "employees.master.edit",
        "employees.master.delete",
    ),
    # Personal / family / address fields came free with the list key.
    "employees.employee.view_sensitive": ("employees.employee.view",),
    # Employee documents rode on view / edit respectively.
    "employees.document.view": ("employees.employee.view",),
    "employees.document.add": ("employees.employee.edit",),
    "employees.document.delete": ("employees.employee.edit",),
    # NB `employees.employee.provision_portal` is an AND-rule — see
    # ALL_OF_RULES below.

    # --- Module 8: Leaves ----------------------------------------------
    # Rejecting was part of the approve key in both flows.
    "leaves.application.reject_any": ("leaves.application.approve_any",),
    "leaves.compoff.reject_any": ("leaves.compoff.approve_any",),
    # The allocations list was readable by any authenticated user, and
    # its campus scope keyed off a different resource's view_all.
    "leaves.allocation.view": (
        "leaves.allocation.add", "leaves.allocation.delete",
        "leaves.application.view_all",
    ),
    "leaves.allocation.view_all_campuses": ("leaves.application.view_all",),

    # --- Module 10.1: Audit > Dashboards -------------------------------
    # One key opened all five dashboards.
    "audit.report.live_faculty": ("audit.report.consolidated",),
    "audit.report.instructor_feedback": ("audit.report.consolidated",),

    # --- Module 10.2: Audit > Forms ------------------------------------
    # Publishing / closing was a `status` field on the edit PATCH.
    "audit.form.publish": ("audit.form.edit",),

    # --- Module 11: Admin ----------------------------------------------
    # `accounts.user.edit` covered assigning roles / campuses and
    # resetting passwords. Backfilled so nobody loses a capability, but
    # this is the split most worth reviewing afterwards: it is the
    # difference between fixing a typo and granting yourself Admin.
    "accounts.user.assign_roles": ("accounts.user.edit",),
    "accounts.user.assign_campuses": ("accounts.user.edit",),
    "accounts.user.reset_password": ("accounts.user.edit",),

    # --- Module 10.4: Audit > Periodic Reports -------------------------
    # `audit.course_end.review` covered both outcomes and is retired.
    "audit.course_end.approve": ("audit.course_end.review",),
    "audit.course_end.return": ("audit.course_end.review",),
}


#: Rules whose source keys must ALL be held, not any. `RULES` is an
#: any-of mapping, which is right for a key that was split apart; this
#: one is for a key that replaces a check requiring two permissions at
#: once. Mapping such a key from either half alone would widen access.
ALL_OF_RULES: dict[str, tuple[str, ...]] = {
    # Provisioning an employee's portal login used to require BOTH
    # `accounts.user.add` (it creates a User) AND
    # `employees.employee.edit` (it writes to the Employee).
    "employees.employee.provision_portal": (
        "accounts.user.add", "employees.employee.edit",
    ),
}


#: Self-service keys granted to every role that holds at least one
#: permission. Both are scoped to the caller's own data server-side, so
#: handing them out broadly reproduces the pre-split behaviour (the
#: sessions strip and My Work feed were ungated).
EVERY_ROLE: tuple[str, ...] = (
    "dashboard.sessions.view",
    "dashboard.my_work.view",
)


#: New keys deliberately left out of `RULES`. Each grants an ability
#: that no pre-split permission implied, so backfilling one would hand
#: out access nobody previously had. They start unassigned and are
#: granted from the Roles page on their own merits.
#:
#: Listed so a coverage audit ("every new key is either mapped or
#: knowingly skipped") stays meaningful as more modules land.
#: Note `admissions.student.view_sensitive` is NOT listed here: it is
#: backfilled from `admissions.student.view` (Students module), which is
#: correct — those staff could already read the fields on the student
#: profile. What the Batch Report pass fixed was the roster handing them
#: out on `academics.batch_report.view` ALONE.
INTENTIONALLY_NOT_BACKFILLED: dict[str, str] = {
    # Editing / deleting someone else's 0-Hour report was superuser-only,
    # so no pre-split permission implied it.
    "academics.zero_hour.edit_any": "was superuser-only",
    "academics.zero_hour.delete_any": "was superuser-only",
    # `tasks.view_all` was checked in code but absent from the
    # catalogue, so it could never be granted — nobody held it, and
    # only superusers ever saw the unscoped Tasks Report.
    "tasks.view_all": "phantom key — was uncheckable, nobody held it",
    "tasks.delete_any": "new admin override; deletion was creator/assignee",
    # Editing / deleting someone else's daily report was superuser-only,
    # same as the 0-Hour pair above.
    "audit.faculty_daily.edit_any": "was superuser-only",
    "audit.faculty_daily.delete_any": "was superuser-only",
    "audit.admin_daily.edit_any": "was superuser-only",
    "audit.admin_daily.delete_any": "was superuser-only",
    # Course-end and batch-mentor reports had no edit / delete endpoint
    # at all, for anyone — these keys back brand-new functionality.
    "audit.course_end.edit_any": "no edit endpoint existed",
    "audit.course_end.delete_any": "no delete endpoint existed",
    "audit.batch_mentor.edit_any": "no edit endpoint existed",
    "audit.batch_mentor.delete_any": "no delete endpoint existed",
    # Student feedback and self-appraisals were equally immutable.
    "audit.feedback.edit_any": "no edit endpoint existed",
    "audit.feedback.delete_any": "no delete endpoint existed",
    "audit.self_appraisal.edit_any": "no edit endpoint existed",
    "audit.self_appraisal.delete_any": "no delete endpoint existed",
    # Flags and stars were likewise immutable — a star is by design
    # never resolved, so a mis-filed one was permanent.
    "audit.compliance.edit_any": "no edit endpoint existed",
    "audit.compliance.delete_any": "no delete endpoint existed",
}
