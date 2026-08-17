"""Seed catalogue of permissions + default Admin role. Idempotent."""

from .models import Permission, Role


def _writes(module, base, noun):
    """Add / edit / delete rows for a resource whose *reads are open*.

    The Master Data reference lists (states, cities, academic years,
    degrees, courses, semesters, batches, subjects, classrooms, time
    slots) are readable by any authenticated user by design — they feed
    dropdowns across the app. They therefore carry no `.view` key: one
    would be a checkbox that changes nothing, which is worse than no
    checkbox at all. See `apps.master.views._ListCreateBase`.
    """
    return [
        (module, f"{base}.add", f"Add {noun}"),
        (module, f"{base}.edit", f"Edit {noun}"),
        (module, f"{base}.delete", f"Deactivate {noun}"),
    ]


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
    # Module 11 — Admin
    #
    # `accounts.user.edit` used to cover assigning roles, assigning
    # campuses, setting is_staff and resetting anyone's password — i.e.
    # a holder could grant themselves Admin or take over a superuser
    # account. Those three are carved out; what remains is the ordinary
    # profile edit its label describes.
    #
    # Campus assignment matters beyond this module: nearly every
    # `*_all_campuses` scope in the app falls back to `user.campuses`.
    ("accounts", "accounts.user.view", "See the user list and open a user"),
    ("accounts", "accounts.user.add", "Add a user"),
    ("accounts", "accounts.user.edit", "Edit a user's name, email and active status"),
    ("accounts", "accounts.user.delete", "Deactivate a user"),
    ("accounts", "accounts.user.assign_roles", "Assign roles to a user"),
    ("accounts", "accounts.user.assign_campuses", "Assign campuses to a user"),
    ("accounts", "accounts.user.reset_password", "Reset another user's password"),

    ("roles", "roles.role.view", "See roles and the permission catalogue"),
    ("roles", "roles.role.add", "Create a role"),
    ("roles", "roles.role.edit", "Edit a role's permissions"),
    ("roles", "roles.role.delete", "Delete a role"),
    # `audit.log.view` dropped: the auth / data-change log endpoints are
    # superuser-only in code and the key was never checked, so it was a
    # checkbox that did nothing. There is no UI for them either.

    # Module B — Lead Management / CRM
    *_crud("master", "master.campus", "campuses"),
    *_crud("master", "master.program", "programs"),
    *_crud("master", "master.source", "lead sources"),

    # Module 2 — Leads
    #
    # One key per action a counsellor can take. Outreach, application
    # fee and application-form control used to share a single
    # `leads.communication.log` key; they are separate now so a
    # counsellor can log a call without also being able to blast bulk
    # SMS or declare fees received.
    ("leads", "leads.lead.view", "See leads assigned to me"),
    ("leads", "leads.lead.view_all", "See every lead, not just mine"),
    ("leads", "leads.lead.create", "Add a new lead"),
    ("leads", "leads.lead.edit", "Edit a lead's details"),
    ("leads", "leads.lead.view_history", "See a lead's status history timeline"),
    ("leads", "leads.lead.reassign", "Reassign a lead to another counsellor"),
    ("leads", "leads.lead.change_status", "Move a lead to a different status"),
    ("leads", "leads.lead.promote", "Convert a lead into a student"),

    ("leads", "leads.communication.log", "Log a call or message against a lead"),
    ("leads", "leads.send.fee_link", "Send the fee payment link to a lead"),
    ("leads", "leads.send.application_link", "Send the application form link to a lead"),
    ("leads", "leads.send.welcome", "Send the welcome message to a lead"),
    ("leads", "leads.bulk_message.send", "Send a bulk message to many leads at once"),

    ("leads", "leads.application_fee.record", "Record the application fee as paid"),
    ("leads", "leads.application_fee.clear", "Undo a recorded application fee"),
    ("leads", "leads.application_form.lock", "Close and re-open a student's application form"),

    ("leads", "leads.followup.view", "See follow-ups on a lead"),
    ("leads", "leads.followup.add", "Add a follow-up to a lead"),
    ("leads", "leads.followup.edit", "Edit a follow-up"),
    ("leads", "leads.followup.delete", "Delete a follow-up"),

    # Module C — Employee Management / HR
    *_crud("master", "master.institute", "institutes"),
    *_writes("master", "master.state", "states"),
    *_writes("master", "master.city", "cities"),
    # Module 7 — HR
    #
    # Departments and Designations share one key set: both are small HR
    # reference lists maintained by the same person, so splitting them
    # would double the checkboxes without adding real control. Their
    # reads used to be open to any authenticated user.
    #
    # Employee documents (contracts, ID proofs, qualifications) carry
    # their own keys rather than riding on `employees.employee.edit`,
    # matching the Students module.
    ("employees", "employees.master.view", "See departments and designations"),
    ("employees", "employees.master.add", "Add a department or designation"),
    ("employees", "employees.master.edit", "Edit a department or designation"),
    ("employees", "employees.master.delete", "Deactivate a department or designation"),

    ("employees", "employees.employee.view", "See the employee list and open an employee"),
    ("employees", "employees.employee.view_all_campuses", "See employees from every campus, not just mine"),
    ("employees", "employees.employee.view_sensitive", "See an employee's personal, family and address details"),
    ("employees", "employees.employee.manage_deleted", "See and manage soft-deleted employees"),
    ("employees", "employees.employee.create", "Add an employee"),
    ("employees", "employees.employee.add_in_any_campus", "Add an employee outside my campus scope"),
    ("employees", "employees.employee.edit", "Edit an employee's details"),
    ("employees", "employees.employee.change_status", "Activate or deactivate an employee"),
    ("employees", "employees.employee.delete", "Soft-delete an employee"),
    ("employees", "employees.employee.provision_portal", "Create an employee's portal login"),

    ("employees", "employees.document.view", "See an employee's documents"),
    ("employees", "employees.document.add", "Upload a document for an employee"),
    ("employees", "employees.document.delete", "Delete an employee's document"),

    # Module D — Leaves
    # Module 8 — Leaves
    #
    # Applying is always for yourself: the on-behalf-of path is gone, so
    # there is no key for it. Approving and rejecting are separate in
    # both the leave and comp-off flows; being the applicant's manager
    # still authorises deciding their request with no key at all.
    #
    # Withdraw / cancel / holidays are deliberately absent — they were
    # dropped in the legacy PHP port and are not being re-added.
    ("leaves", "leaves.type.view", "See leave types"),
    ("leaves", "leaves.type.add", "Add a leave type"),
    ("leaves", "leaves.type.edit", "Edit a leave type"),
    ("leaves", "leaves.type.delete", "Deactivate a leave type"),

    ("leaves", "leaves.allocation.view", "See leave allocations"),
    ("leaves", "leaves.allocation.view_all_campuses", "See leave allocations for every campus, not just mine"),
    ("leaves", "leaves.allocation.add", "Allocate leave to employees"),
    ("leaves", "leaves.allocation.delete", "Delete an unconsumed allocation"),

    ("leaves", "leaves.application.view_all", "See every employee's leave applications"),
    ("leaves", "leaves.application.approve_any", "Approve any leave, not just my team's"),
    ("leaves", "leaves.application.reject_any", "Reject any leave, not just my team's"),

    ("leaves", "leaves.compoff.view_all", "See every employee's comp-off applications"),
    ("leaves", "leaves.compoff.approve_any", "Approve any comp-off, not just my team's"),
    ("leaves", "leaves.compoff.reject_any", "Reject any comp-off, not just my team's"),

    ("leaves", "leaves.report.view", "See the leave report for my campuses"),
    ("leaves", "leaves.report.view_all", "See the leave report for every campus"),
    ("leaves", "leaves.report.delete", "Delete a leave application"),

    # Module E.1 — Admissions + new masters
    *_writes("master", "master.academicyear", "academic years"),
    *_writes("master", "master.degree", "degrees"),
    *_writes("master", "master.course", "courses"),
    *_writes("master", "master.semester", "semesters"),
    *_writes("master", "master.batch", "batches"),

    # Module 3.1 — Admission › Students
    #
    # `admissions.student.edit` used to cover transfers, the registration
    # number, remarks, portal-password resets and the handbook email. It
    # is narrowed here to ordinary profile fields; every other action has
    # its own key.
    ("admissions", "admissions.student.create", "Add a student (from a promoted lead)"),
    ("admissions", "admissions.student.view", "See the students list and open a student"),
    ("admissions", "admissions.student.view_all_campuses", "See students from every campus, not just mine"),
    ("admissions", "admissions.student.view_sensitive", "See personal, family and address details"),
    ("admissions", "admissions.student.view_education", "See a student's education history"),
    ("admissions", "admissions.student.view_attendance", "See a student's attendance summary"),
    ("admissions", "admissions.student.view_fees", "See the fees section on a student's page"),

    ("admissions", "admissions.student.edit", "Edit a student's basic details"),
    ("admissions", "admissions.student.transfer", "Move a student to another institute, campus, program or course"),
    ("admissions", "admissions.student.set_registration_no", "Set or change a student's registration number"),
    ("admissions", "admissions.student.view_remarks", "Read admin remarks on a student"),
    ("admissions", "admissions.student.add_remark", "Add an admin remark to a student"),

    ("admissions", "admissions.student.promote", "Promote students to the next batch or semester"),
    ("admissions", "admissions.student.send_credentials", "Send portal credentials and reset the student's password"),
    ("admissions", "admissions.student.send_handbook", "Email the student handbook"),

    ("admissions", "admissions.document.view", "See a student's documents"),
    ("admissions", "admissions.document.add", "Upload a document for a student"),
    ("admissions", "admissions.document.delete", "Delete a student's document"),

    ("admissions", "admissions.enrollment.view", "See a student's enrolments"),
    ("admissions", "admissions.enrollment.add", "Enrol a student into a batch"),
    ("admissions", "admissions.enrollment.edit", "Edit an enrolment"),
    ("admissions", "admissions.enrollment.send_undertaking", "Email the fee undertaking PDF to a student"),

    # Module E.2 — Fees
    *_crud("master", "master.feetemplate", "fee templates"),

    # Module 3.2 — Admission › Fee Collection
    #
    # `fees.receipt.view` remains the door to the whole module (see
    # `apps.fees.permissions.FeeAccessPolicy`) and `view_all` remains the
    # campus scope for every list in it — including the day's collection
    # totals. The keys below carve up what used to ride on that gate:
    # installment reads, other fees and the balance figure.
    ("fees", "fees.receipt.view", "See fee receipts (required for any fee screen)"),
    ("fees", "fees.receipt.view_all", "See fee data from every campus, not just mine"),
    ("fees", "fees.receipt.create", "Record a fee payment"),
    ("fees", "fees.receipt.edit", "Correct a posted receipt"),
    ("fees", "fees.receipt.cancel", "Cancel a posted receipt"),

    ("fees", "fees.installment.view", "See a student's installment schedule"),
    ("fees", "fees.installment.add", "Add installments to a fee plan"),
    ("fees", "fees.installment.edit", "Edit an installment's amount or due date"),
    ("fees", "fees.installment.delete", "Delete an installment"),

    ("fees", "fees.otherfee.view", "See ad-hoc other fees"),
    ("fees", "fees.otherfee.add", "Add an ad-hoc other fee"),
    ("fees", "fees.otherfee.delete", "Delete an ad-hoc other fee"),

    ("fees", "fees.balance.view", "See a student's fee balance"),
    ("fees", "fees.concession.request", "Raise a concession request"),
    ("fees", "fees.concession.approve", "Approve or reject concession requests"),

    # Module 3.3 / 3.4 — Admission › Fee Reports + Concession Reports.
    # Deliberately one key per page rather than per action: both pages
    # only read the fee endpoints above, which already enforce their own
    # permissions and campus scope. These gate the menu entry and page.
    ("fees", "fees.report.view", "See the Fee Reports page"),
    ("fees", "fees.concession_report.view", "See the Concession Reports page"),

    # Module F — Lead Management Hardening
    ("leads", "leads.pool.view", "See counsellor pools"),
    ("leads", "leads.pool.add", "Create counsellor pools and add members"),
    ("leads", "leads.pool.edit", "Edit counsellor pools and members"),
    ("leads", "leads.pool.delete", "Remove members from a counsellor pool"),
    ("leads", "leads.escalation.receive", "Receive alerts about overdue hot leads"),

    # Lead reports — split so revenue and staff rankings are not on the
    # same checkbox as a duplicate-phone count.
    ("leads", "leads.report.funnel", "See the conversion funnel, summary and time-per-stage"),
    ("leads", "leads.report.leaderboard", "See the counsellor leaderboard"),
    ("leads", "leads.report.revenue", "See course-wise enrolments and revenue"),
    ("leads", "leads.report.quality", "See lost-lead and duplicate reports"),

    # Entrance Exams (Leads pipeline)
    ("leads", "leads.exam.create", "Create and edit entrance exams"),
    ("leads", "leads.exam.publish", "Publish, close and map entrance exams"),
    ("leads", "leads.exam.review", "Review short-answer exam responses"),
    ("leads", "leads.exam.view_all", "See every entrance exam, not just mine"),
    ("leads", "leads.exam.edit_any", "Edit anyone's entrance exam"),
    ("leads", "leads.exam.delete_any", "Delete anyone's entrance exam"),
    ("leads", "leads.exam.view_lead_attempts", "See a lead's entrance-exam attempts"),
    # Notifications has a NotificationTemplate model and a seeding
    # command, but no urls.py, no views.py, and is not mounted in
    # config/urls.py — so `notifications.template.*` and
    # `notifications.dispatch.view` were five checkboxes with nothing
    # behind them. Re-add them alongside the API if a templates admin
    # screen is ever built.

    # Module G.1 — Course Scheduling
    *_writes("master", "master.subject", "subjects"),
    *_writes("master", "master.classroom", "classrooms"),
    *_writes("master", "master.timeslot", "time slots"),
    # Module 5 — Slot
    #
    # The timetable used to be readable by any logged-in user
    # (`ScheduleAccess` allowed every GET); staff now need
    # `schedule.view`. Students and instructors still reach their own
    # sessions through /schedule/me, which stays ungated.
    ("academics", "academics.schedule.view", "See the timetable and calendar"),
    ("academics", "academics.schedule.view_all", "See the timetable for every campus, not just mine"),
    ("academics", "academics.schedule.add", "Create slots and publish timetables"),
    ("academics", "academics.schedule.edit", "Edit a scheduled slot"),
    ("academics", "academics.schedule.delete", "Cancel a scheduled slot"),
    ("academics", "academics.schedule.override_conflict", "Publish a slot despite a classroom clash"),

    # Module G.2 — Attendance
    # Module 6.2 — Academics > Attendance
    #
    # The slot roster used to be readable by any authenticated user, and
    # the batch report accepted plain campus membership in place of a
    # permission. Both are closed here. An instructor keeps implicit
    # rights over their OWN slot (view roster, mark, freeze) without
    # holding any of these keys.
    ("academics", "academics.attendance.view_roster", "See a slot's attendance roster"),
    ("academics", "academics.attendance.mark", "Mark attendance for any slot"),
    ("academics", "academics.attendance.edit_frozen", "Edit attendance after it is frozen"),
    ("academics", "academics.attendance.notify_absent", "Send absence alerts to students"),
    ("academics", "academics.attendance.freeze", "Freeze and unfreeze attendance"),
    ("academics", "academics.attendance.view_report", "See attendance reports"),
    ("academics", "academics.attendance.view_instructor_log", "See the per-instructor teaching log"),
    ("academics", "academics.attendance.view_all_campuses", "See attendance reports for every campus, not just mine"),
    # Module 6.3 — Academics > Batch Report
    #
    # The roster returns each student's personal, family and address
    # details for a whole batch at once, which bypassed
    # `admissions.student.view_sensitive`. It is now a separate key AND
    # the sensitive columns are withheld unless the caller also holds
    # that Students-module permission.
    ("academics", "academics.batch_report.view", "See the batch list and headcounts"),
    ("academics", "academics.batch_report.view_roster", "See a batch's full student roster"),
    ("academics", "academics.batch_report.view_all_campuses", "See batches from every campus, not just mine"),
    ("academics", "academics.batch_report.edit_feedback", "Set and enable a batch's feedback link"),
    # Module 6.4 — Academics > Closing Report
    #
    # Unlike the Batch Report roster this sheet carries no personal
    # contact data — just name, application id, attendance % and the
    # three editable award columns — so it needs no `view_sensitive`
    # interaction. Campus scoping matches the other Academics reports.
    ("academics", "academics.closing_report.view", "See a batch's closing report"),
    ("academics", "academics.closing_report.view_all_campuses", "See closing reports for every campus, not just mine"),
    ("academics", "academics.closing_report.edit", "Edit awards, portfolio and remarks on a closing report"),

    # Module G.3 — Assignments + Marks
    # Module 4 — LMS
    #
    # The assignment and lesson lists used to be open to any logged-in
    # user, and their campus scope was borrowed from
    # `academics.schedule.view_all`. Both now carry their own keys.
    # Owners keep implicit rights over what they created — the keys
    # below govern other people's work.
    ("academics", "academics.assignment.view", "See assignments"),
    ("academics", "academics.assignment.view_all_campuses", "See assignments from every campus, not just mine"),
    ("academics", "academics.assignment.create", "Create and edit my own assignments"),
    ("academics", "academics.assignment.edit_any", "Edit anyone's assignment"),
    ("academics", "academics.assignment.delete_any", "Delete anyone's assignment"),
    ("academics", "academics.assignment.view_submissions", "See student submissions on any assignment"),
    ("academics", "academics.assignment.grade", "Grade a submission on any assignment"),

    ("academics", "academics.lesson.view", "See lesson plans"),
    ("academics", "academics.lesson.view_all", "See lesson plans from every campus, not just mine"),
    ("academics", "academics.lesson.create", "Create and edit my own lesson plans"),
    ("academics", "academics.lesson.edit_any", "Edit anyone's lesson plan"),
    ("academics", "academics.lesson.delete_any", "Delete anyone's lesson plan"),

    ("academics", "academics.marks.view", "See marks"),
    ("academics", "academics.marks.enter", "Enter and edit draft marks"),
    ("academics", "academics.marks.edit_published", "Edit marks after they are published"),
    ("academics", "academics.marks.publish", "Publish marks to students"),
    ("academics", "academics.marks.unpublish", "Retract published marks"),
    ("academics", "academics.transcript.view_any", "See any student's transcript"),
    ("academics", "academics.transcript.view_drafts", "Include unpublished marks in transcripts"),

    # Module G.5 — Certificates + Alumni
    # Module 6.5 — Academics > Records (Certificates + Alumni)
    #
    # Graduating a student is neither an enrolment edit nor a
    # certificate issue, so it gets its own key — the per-enrolment and
    # whole-batch endpoints previously disagreed about which permission
    # they wanted. Rejecting a request is split from issuing it.
    ("academics", "academics.certificate.view_all", "See every student's certificates"),
    ("academics", "academics.certificate.view_all_campuses", "See certificates from every campus, not just mine"),
    ("academics", "academics.certificate.request_for_others", "Raise a certificate request for a student"),
    ("academics", "academics.certificate.issue", "Issue a certificate"),
    ("academics", "academics.certificate.reject", "Reject a certificate request"),
    ("academics", "academics.certificate.override_eligibility", "Issue a certificate that fails the eligibility check"),
    ("academics", "academics.certificate.graduate", "Graduate a student and create their alumni record"),
    ("academics", "academics.alumni.view_all", "See every alumni record"),
    ("academics", "academics.alumni.view_all_campuses", "See alumni from every campus, not just mine"),
    ("academics", "academics.alumni.edit", "Edit any alumni record"),

    # Module G.4 — Online Tests
    ("academics", "academics.test.view", "See tests"),
    ("academics", "academics.test.view_all", "See everyone's tests, not just mine"),
    ("academics", "academics.test.create", "Create and edit my own tests"),
    ("academics", "academics.test.publish", "Publish, close and map anyone's test"),
    ("academics", "academics.test.review", "Review short-answer responses on anyone's test"),
    ("academics", "academics.test.edit_any", "Edit anyone's test"),
    ("academics", "academics.test.delete_any", "Delete anyone's test"),

    # Module H — Auditor / Reports
    # Faculty daily report — auditors get read-only visibility of every
    # faculty's report here. Filling one's OWN report lives under the
    # Dashboard module (dashboard.daily_report.submit) instead.
    ("audit", "audit.faculty_daily.view_all", "See every faculty daily report"),
    ("audit", "audit.faculty_daily.edit_any", "Edit anyone's faculty daily report"),
    ("audit", "audit.faculty_daily.delete_any", "Delete anyone's faculty daily report"),
    # Admin daily report — auditors get read-only view of everyone's here;
    # filling one's OWN lives under Dashboard (dashboard.admin_daily.submit).
    ("audit", "audit.admin_daily.view_all", "See every admin daily report"),
    ("audit", "audit.admin_daily.edit_any", "Edit anyone's admin daily report"),
    ("audit", "audit.admin_daily.delete_any", "Delete anyone's admin daily report"),
    # Audit > Periodic Reports (Course-End + Batch-Mentor).
    #
    # Neither report could be edited or deleted by anyone, including
    # superusers — there were no PATCH / DELETE endpoints at all, so a
    # typo was permanent. The *_any keys back the new endpoints.
    #
    # Approving and returning-for-rework are split: sending a report
    # back to its author is a different act from signing it off.
    ("audit", "audit.course_end.view_all", "See every course-end report"),
    ("audit", "audit.course_end.submit", "Submit a course-end report"),
    ("audit", "audit.course_end.approve", "Approve a course-end report"),
    ("audit", "audit.course_end.return", "Return a course-end report for rework"),
    ("audit", "audit.course_end.edit_any", "Edit anyone's course-end report"),
    ("audit", "audit.course_end.delete_any", "Delete anyone's course-end report"),

    ("audit", "audit.batch_mentor.view_all", "See every batch-mentor report"),
    ("audit", "audit.batch_mentor.submit_for_others", "Submit a batch-mentor report for a batch I don't mentor"),
    ("audit", "audit.batch_mentor.edit_any", "Edit anyone's batch-mentor report"),
    ("audit", "audit.batch_mentor.delete_any", "Delete anyone's batch-mentor report"),
    # Zero-Hour report — filled under Academics, reviewed under Audit.
    # Module 6.6 — Academics > 0-Hour Form
    #
    # Filling and reading are split across two modules by design: this
    # key covers your OWN reports (Academics), while
    # `audit.zero_hour.view_all` gives auditors read-only sight of
    # everyone's (Audit). Editing or deleting someone else's report used
    # to require a superuser account; the *_any keys make it delegable.
    ("academics", "academics.zero_hour.submit", "Fill in and edit my own 0-Hour reports"),
    ("academics", "academics.zero_hour.delete", "Delete my own 0-Hour report"),
    ("academics", "academics.zero_hour.edit_any", "Edit anyone's 0-Hour report"),
    ("academics", "academics.zero_hour.delete_any", "Delete anyone's 0-Hour report"),
    ("audit", "audit.zero_hour.view_all", "View all 0-Hour reports"),
    # Audit > Feedback.
    #
    # Student feedback is anonymous to the instructor — the API exposes
    # only aggregates (see `audit.report.instructor_feedback`). This key
    # is what de-anonymises it, so the label says so rather than reading
    # like an ordinary list permission.
    ("audit", "audit.feedback.view_all", "See student feedback with the student's name attached"),
    ("audit", "audit.feedback.edit_any", "Edit anyone's student feedback"),
    ("audit", "audit.feedback.delete_any", "Delete anyone's student feedback"),

    ("audit", "audit.self_appraisal.view_own", "See my own self-appraisal"),
    ("audit", "audit.self_appraisal.view_all", "See every faculty self-appraisal"),
    ("audit", "audit.self_appraisal.submit", "Submit my own self-appraisal"),
    ("audit", "audit.self_appraisal.review", "Record auditor remarks on a self-appraisal"),
    ("audit", "audit.self_appraisal.edit_any", "Edit anyone's self-appraisal"),
    ("audit", "audit.self_appraisal.delete_any", "Delete anyone's self-appraisal"),
    # Audit > Flags & Stars.
    #
    # One key covers both polarities: raising a flag (a compliance
    # concern) and awarding a star (recognition) are the same grant, and
    # `view` shows both lists.
    #
    # Nothing could previously be edited or removed, by anyone — a flag
    # raised against the wrong colleague stayed on their record forever,
    # and a star is by design never resolved. The *_any keys back the
    # new detail endpoint.
    ("audit", "audit.compliance.view", "See flags and stars raised against staff"),
    ("audit", "audit.compliance.flag", "Raise a flag or award a star"),
    ("audit", "audit.compliance.resolve", "Resolve a compliance flag"),
    ("audit", "audit.compliance.edit_any", "Edit anyone's flag or star"),
    ("audit", "audit.compliance.delete_any", "Delete anyone's flag or star"),
    # Audit > Dashboards — one key used to open all five. The
    # per-instructor feedback summary and the live-faculty tracker are
    # views of a named colleague's activity, so they carry their own
    # keys (same reasoning as `academics.attendance.view_instructor_log`
    # and `leads.report.leaderboard`).
    ("audit", "audit.report.consolidated", "See the consolidated monthly and batch-progression dashboards"),
    ("audit", "audit.report.live_faculty", "See live faculty tracking and timetable adherence"),
    ("audit", "audit.report.instructor_feedback", "See an instructor's student-feedback summary"),
    # Audit > Forms.
    #
    # `audit.form.view` is a *manager* key, not a plain read: it bypasses
    # both the PUBLISHED check and role targeting, so a holder sees and
    # can preview drafts aimed at other roles. Everyone else reaches a
    # form through `_can_access_form` — published + targets a role they
    # hold — which needs no key. The label says so rather than the key
    # being renamed, which would cost a migration for no behaviour gain.
    #
    # Publishing pushes a form to a whole role's worth of staff, so it
    # is split from editing its questions.
    ("audit", "audit.form.view", "See every form, including drafts and ones not targeting me"),
    ("audit", "audit.form.add", "Create an audit form"),
    ("audit", "audit.form.edit", "Edit an audit form's questions and target roles"),
    ("audit", "audit.form.publish", "Publish or close an audit form"),
    ("audit", "audit.form.delete", "Delete an audit form (only while it has no responses)"),
    ("audit", "audit.submission.view_all", "See every user's form submissions"),

    # Module 9 — Tasks
    #
    # Tasks are self-service: anyone can create one and assign it, see
    # the ones they created or were assigned, edit their own fields and
    # complete what is assigned to them — all without a permission.
    #
    # `tasks.view_all` was already checked in `apps.tasks.views._scope_for`
    # but was missing from this catalogue entirely, so it could never be
    # granted and the Tasks Report was superuser-only in practice.
    ("tasks", "tasks.view_all", "See every user's tasks (Tasks Report)"),
    ("tasks", "tasks.delete_any", "Delete anyone's task"),

    # Module 1 — Dashboard
    #
    # One key per card on the dashboard home page, so each tile can be
    # switched on independently. These are presentation gates: the
    # underlying endpoints still enforce their own data permissions, so
    # granting a card without the matching feature perm shows an empty
    # tile rather than leaking anything.
    ("dashboard", "dashboard.sessions.view", "See my sessions for today"),
    ("dashboard", "dashboard.sessions.view_all", "See everyone's sessions for today"),
    ("dashboard", "dashboard.leads.view", "See lead stats and the priority review list"),
    ("dashboard", "dashboard.enrollments.view", "See the active enrolments count"),
    ("dashboard", "dashboard.students.view", "See the total students count"),
    ("dashboard", "dashboard.engagement.view", "See the engagement metrics chart"),
    ("dashboard", "dashboard.my_work.view", "See my reports and plans feed"),
    ("dashboard", "dashboard.daily_report.submit", "Fill in my daily report"),
    ("dashboard", "dashboard.admin_daily.submit", "Fill in my admin daily report"),

    # Module HR — Relieving (exit workflow + experience letter)
    ("hr", "hr.relieving.submit_for_others", "Submit relieving on behalf of others"),
    ("hr", "hr.relieving.view_all", "View all relieving applications"),
    ("hr", "hr.relieving.finalize", "HR finalizes relieving + generates letters"),
    ("hr", "hr.relieving.override", "Override approval sequence (skip levels)"),

    # Student & Parent Portal
    ("courseware", "courseware.view", "See courseware topics"),
    ("courseware", "courseware.add", "Publish a courseware topic"),
    ("courseware", "courseware.edit", "Edit a courseware topic and its attachments"),
    ("courseware", "courseware.delete", "Delete a courseware topic or attachment"),
    # Module 6.7 — Academics > Student Leaves
    #
    # The mentor console is self-service and deliberately needs no key:
    # a batch mentor is identified by `batch_mentor_email`, and the
    # queue is empty for anyone who mentors nothing. The keys below
    # widen that (view_all) or authorise an action on it.
    #
    # Approving and rejecting are separate, and both are scoped to the
    # batches you mentor unless you also hold `view_all`.
    ("student_leaves", "student_leaves.view_all", "See every student leave, not just my batches"),
    ("student_leaves", "student_leaves.approve", "Approve a student leave"),
    ("student_leaves", "student_leaves.reject", "Reject a student leave"),
    ("student_leaves", "student_leaves.report.view", "See the student leave report for my campuses"),
    ("student_leaves", "student_leaves.report.view_all", "See the student leave report for every campus"),
    ("student_leaves", "student_leaves.delete", "Delete a student leave application"),
    # Module 6.8 — Academics > Document Requests
    #
    # Students request institute-issued documents (TC, Bonafide, Study
    # Certificate, Bank Letter, LOR) from the portal; staff decide and
    # attach the issued file. Approving and rejecting are separate, and
    # the list is campus-scoped unless `view_all` is held.
    ("student_documents", "student_documents.view", "See document requests for my campuses"),
    ("student_documents", "student_documents.view_all", "See document requests from every campus"),
    ("student_documents", "student_documents.approve", "Approve a document request and attach the issued file"),
    ("student_documents", "student_documents.reject", "Reject a document request"),
    # Module 6.9 — Academics > Appointments
    #
    # Students book a meeting with a team or a named faculty member.
    # A faculty member reaching their OWN queue is self-service and
    # needs no key — the list is empty for anyone nothing is addressed
    # to. `view_all` widens that to every colleague's requests.
    #
    # Confirming, declining and completing are separate: the first two
    # authorise the meeting, the third records that it happened.
    ("appointments", "appointments.view_all", "See every student appointment request"),
    ("appointments", "appointments.confirm", "Confirm an appointment and set the date, time and venue"),
    ("appointments", "appointments.decline", "Decline an appointment request"),
    ("appointments", "appointments.complete", "Mark an appointment as completed"),
    ("admissions", "admissions.parent.view", "See a student's parent account"),
    ("admissions", "admissions.parent.add", "Create a parent account for a student"),
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
    # Baseline dashboard tiles: own sessions + own reports feed. Every
    # other tile (leads / enrolments / students / engagement) is granted
    # explicitly from the Roles page.
    "dashboard.sessions.view",
    "dashboard.my_work.view",
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
