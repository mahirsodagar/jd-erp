# 13 — Cross-Module Map & Change Impact

How the modules depend on each other, how data flows between them, and what
breaks when you change something. **Read this before your first change.**

---

## 13.1 Dependency layers

Modules only depend downward. A cycle here would be a design error.

```
  ┌─────────────────────────────────────────────────────────────────┐
  │ L4  READ-SIDE / DERIVED                                         │
  │     audit_reports        (aggregates everything below)          │
  │     portal               (student/parent view of everything)    │
  │     leads.reports                                               │
  └──────────────────────────┬──────────────────────────────────────┘
  ┌──────────────────────────▼──────────────────────────────────────┐
  │ L3  DOMAIN                                                      │
  │     academics · courseware · fees · leaves · relieving ·        │
  │     tasks · student_leaves · student_documents · appointments   │
  └──────────────────────────┬──────────────────────────────────────┘
  ┌──────────────────────────▼──────────────────────────────────────┐
  │ L2  ENTITY                                                      │
  │     admissions (Student, Enrollment) ·  employees (Employee)    │
  │     leads (Lead)                                                │
  └──────────────────────────┬──────────────────────────────────────┘
  ┌──────────────────────────▼──────────────────────────────────────┐
  │ L1  FOUNDATION                                                  │
  │     master · accounts · roles · audit · common · notifications  │
  └─────────────────────────────────────────────────────────────────┘
```

`notifications` sits in L1 but is called *from* every layer — it is a leaf
dependency, not an orchestrator. It imports nothing from the domain apps
except inside function bodies (deliberately, to avoid import cycles).

## 13.2 The hub models

Five models are referenced by nearly everything. Changing them is expensive.

| Model | Referenced by |
|---|---|
| `accounts.User` | Every audit trail (`created_by`, `decided_by`, `submitted_by`…), `Student.user_account` / `.parent_user_account`, `Employee.user_account`, `Lead.assign_to`, `Task.assignee`, `Role.users`, `User.campuses` |
| `master.Campus` | Campus scoping in *every* module, `Student`, `Employee`, `Lead`, `Batch`, `Classroom`, `Enrollment`, `FeeTemplate` |
| `master.Batch` | `ScheduleSlot`, `Assignment`, `Lesson`, `MarksEntry`, `CoursewareTopic`, `Enrollment`, `ClosingAward`, `CourseEndReport`, `BatchMentorReport`, `ZeroHourReport`, `StudentFeedback`, `ComplianceFlag`, `AlumniRecord` |
| `admissions.Student` | `Enrollment`, `Attendance`, `AssignmentSubmission`, `MarksEntry`, `TestAttempt`, `Certificate`, `AlumniRecord`, `CoursewareMapping`, `StudentLeaveApplication`, `DocumentRequest`, `StudentAppointment`, `StudentFeedback`, `ClosingAward`, `ComplianceFlag` |
| `employees.Employee` | `ScheduleSlot.instructor`, `Batch.mentor`, `Lesson.hod`/`.class_mentor`, `LeaveApplication`, `CompOffApplication`, `RelievingApplication`, `RelievingApproval`, every `audit_reports` model that names a faculty |

## 13.3 The main data flow, end to end

```
 1. Lead created (intake API or staff)
      └─► leads.services.create_lead
            ├─► dedup against existing leads              [leads]
            ├─► round-robin over Counsellor              [leads + employees]
            └─► signal: lead_welcome_email / _wa          [notifications]

 2. Follow-ups logged, each with an outcome
      └─► signal: outcome drip (hot / cold / enrolled …)  [notifications]

 3. Send fee link  →  payment received  →  mark fee paid  [leads]
            uses INSTITUTE_PAYMENT_DETAILS + FEE_LINK_URLS

 4. Send application link  (GATED on step 3)
      └─► tokenised public form                          [admissions.public_views]
            └─► submit_application_from_lead
                  ├─► creates Student + User             [admissions + accounts]
                  ├─► upserts StudentDocument rows
                  └─► lead.status = application_submitted [leads]

 5. Enrollment created into a Batch                      [admissions + master]
      ├─► Installments (schedule)                        [fees]
      ├─► fee undertaking PDF emailed                    [fees + notifications]
      └─► student now appears in batch rosters           [academics, courseware]

 6. Fee receipts recorded                                [fees]
      ├─► signal: payment confirmation SMS ×2            [notifications]
      └─► enrollment_balance() reads FeeTemplate         [master]

 7. Timetable published                                  [academics + master]
      └─► attendance marked per slot                     [academics]
            └─► absentee alerts (5 messages per absentee)[notifications]

 8. Assignments / marks / tests / lessons / courseware   [academics, courseware]
      └─► visible to the student                         [portal]

 9. Certificates issued, student graduated               [academics]
      └─► AlumniRecord created, enrollment → ALUMNI

10. Everything above is aggregated                       [audit_reports]
```

## 13.4 Cross-module coupling table

Non-obvious dependencies worth memorising:

| Consumer | Depends on | Why |
|---|---|---|
| `leads.send_links` | `master.FeeTemplate` | Resolves the application-fee amount |
| `leads.send_links` | `Program.degree_type` | Decides the email From domain |
| `leads.promote` | `admissions.permissions` | Needs **both** `leads.lead.promote` and `admissions.student.create` |
| `admissions.services` | `master.AcademicYear.is_current` | Hard-fails if none is marked current |
| `admissions.services` | `Campus.institute` | Hard-fails if the campus has no parent institute |
| `admissions.services_undertaking` | `fees.Installment`, `fees.Concession` | The undertaking's arithmetic |
| `fees.balance` | `master.FeeTemplate` | Resolved at read time, not snapshotted |
| `academics.attendance_service` | `admissions.Enrollment` (ACTIVE) | The roster is derived live |
| `academics.cert_service` | `fees` balance | NO_DUES eligibility |
| `academics.cert_service` | `MarksEntry` | COMPLETION / PROVISIONAL eligibility |
| `courseware` publish | `Enrollment` (ACTIVE) | Creates one mapping per active student |
| `leaves` | `Employee.reporting_manager_1` | Snapshotted into `manager_email` |
| `relieving` | `Employee.reporting_manager_1..4` | Snapshotted into `RelievingApproval` |
| `student_leaves` | `Batch.mentor` | Snapshotted into `batch_mentor_email` |
| `audit_reports.services` | `academics`, `leaves`, `fees`, `admissions` | Every dashboard is a cross-module read |
| `portal` | `Student.user_account` / `.parent_user_account` | The entire identity model |
| `notifications.sender` | `Program.degree_type` | Diploma vs degree domain routing |
| Almost everything | `User.campuses` | The default scope on nearly every list |

## 13.5 Snapshot-vs-live: the pattern that surprises people

Some relationships are **snapshotted at submission time** so that later
org-chart or master-data changes never reroute or rewrite history. Others are
**resolved live** so the current state always wins. Mixing them up is the most
common source of "why didn't this update".

| Snapshotted (frozen) | Resolved live |
|---|---|
| `LeaveApplication.manager_email` | Attendance roster (`Enrollment` ACTIVE) |
| `RelievingApproval.approver` | Batch roster, batch report |
| `StudentLeaveApplication.batch_mentor_email` | `enrollment_balance()` → `FeeTemplate` |
| `Certificate.snapshot` (JSON, at issue) | Transcript (from current `MarksEntry`) |
| `AlumniRecord.final_*` (at graduation) | Every `audit_reports` dashboard |
| `Lead.occurrence_number` | Portal context (`resolve_portal_context`) |

## 13.6 Signals — the automatic side effects

Four `post_save` receivers fire without any explicit call. Know them before you
bulk-create anything.

| Signal | File | Effect |
|---|---|---|
| `Lead` created | `notifications/signals.py` | Queues `lead_welcome_email` + `lead_welcome_wa` |
| `LeadFollowup` created with an outcome | `notifications/signals.py` | Queues the whole drip programme for that outcome |
| `FeeReceipt` created (ACTIVE) | `fees/notifications.py` | Two payment-confirmation SMS (student + parent) |
| Model changes | each app's `signals.py` | django-auditlog row |

> **Bulk-import warning.** Importing leads or receipts through the ORM fires
> these signals. A 5,000-row lead import would queue 10,000 notifications. Use
> `bulk_create` (which does not send `post_save`) or temporarily disconnect the
> receiver, and gate WhatsApp/SMS with the env flags first.

## 13.7 Delete behaviour cheat-sheet

| Model | Delete semantics |
|---|---|
| `master.*` | `_MasterDetailMixin.delete` sets `is_active=False`. Consuming FKs are `PROTECT`, so a real delete raises |
| `employees.Employee` | Soft delete (`is_deleted`), `emp_code` stays reserved |
| `fees.FeeReceipt` | Never deleted — cancelled (`status=CANCELLED`) |
| `admissions.Student` | Blocked by `PROTECT` from `Enrollment`, `Attendance`, `MarksEntry`, `Certificate`, submissions, test attempts. Documents, remarks, appointments, leaves, document-requests cascade |
| `academics.ScheduleSlot` | **Cascades to its `Attendance` rows.** Cancel (`status=CANCELLED`) instead |
| `leads.Lead` | Cascades follow-ups, history, communications, UTM, exam attempts. `Student.lead_origin` is `SET_NULL` |
| `audit_reports.AuditForm` | Only while it has no responses; fields and submissions cascade |
| `accounts.User` | Referenced everywhere as `SET_NULL`, so deleting one leaves anonymous audit trails. **Deactivate instead** (`is_active=False`) |

## 13.8 Change-impact playbook

### "I want to add a field to Student"

1. Model + migration.
2. `apps/admissions/serializers.py` — decide which permission group it belongs
   to (basic / sensitive / education).
3. `apps/admissions/services.py::_STUDENT_TEXT_FIELDS` if the public
   application form should be able to fill it.
4. `src/api/endpoints/students.ts` type.
5. `StudentDetailPage` / `StudentEditPage` / `ApplicationFormPage`.
6. Check whether `apps/academics/batch_report.py` should expose it (and whether
   it counts as sensitive).

### "I want to add a new module"

1. New Django app under `apps/`, add to `INSTALLED_APPS`, mount in
   `config/urls.py`.
2. Add permission keys to `apps/roles/seed.py::CATALOGUE`; run
   `seed_permissions` everywhere.
3. Follow the module conventions: `models.py`, `serializers.py`, `views.py`
   (`APIView` + `HasPerm`), `permissions.py` with a `filter_visible` for campus
   scoping, `services.py` for business rules.
4. Register auditlog in `signals.py` if the data is sensitive.
5. Frontend: `api/endpoints/<module>.ts`, pages, `router.tsx`, sidebar entry.

### "I want to change a permission key"

1. Update `CATALOGUE` **and** every code reference.
2. Add the old→new mapping to `apps/roles/migrate_map.py`.
3. Run `migrate_permissions --dry-run`, then `migrate_permissions`, on every
   environment. (Use `seed_permissions` only on a fresh database.)
4. Update `Sidebar.tsx` `perms` and any `useCan` call sites.
5. Run `check_permissions` to confirm code and catalogue agree.
6. Tell users to log out and back in.

### "I want to change an SMS body"

You cannot, unilaterally. The body is registered with DLT/TRAI under the
principal entity. Re-register the template, obtain the new template id, then
update `BULK_SMS_TEMPLATE_IDS`, `MSG91_SMS_TEMPLATE_IDS` and
`MSG91_SMS_VAR_ORDER` together.

### "I want to change who can see student contact details"

The relevant keys are `admissions.student.view_sensitive` and
`academics.batch_report.view_roster`. The batch roster deliberately requires
**both** — it returns a whole batch's personal data at once. Do not relax that.

## 13.9 Known gaps and backlog

Recording these so they are not rediscovered as bugs:

1. **`notifications` has no HTTP API.** There is a `NotificationTemplate` model
   and a seeder, but no views and no admin screen beyond Django admin. The
   `notifications.template.*` permission keys were removed because nothing
   checked them. Re-add them alongside any templates-admin screen.
2. **HR Relieving has endpoints and permission keys but only a partial
   frontend.** Several actions are API-only. Tracked as a batch to build after
   the remaining sidebar modules.
3. **`LEAVES_EXCLUDE_HOLIDAYS_AND_WEEKENDS` is dead configuration** — the
   legacy-port `count_days` ignores it.
4. **The leave-year window is hard-coded** (`LEAVE_YEAR_START` /
   `LEAVE_YEAR_END` = 1 Jun 2025 – 31 May 2026 in
   `apps/leaves/services/balance.py`). It must be updated every year.
5. **WhatsApp is largely dormant.** `WHATSAPP_ENABLED=False` by default, most
   `XIRCLS_WA_TRIGGERS` are blank, and `lead.application_link.wa` is
   temporarily pointed at the trigger `"Test"`.
6. **Several `MSG91_FLOW_*` ids are unset**, so those SMS templates only work
   under `SMS_PROVIDER=bulksms`.
7. **`EMAIL_BACKEND` defaults to the console backend**, which reports success
   while delivering nothing. Every real environment must override it.
8. **Throttling uses LocMemCache by default**, which is per-process. With N
   gunicorn workers, effective limits are N× the configured rate.
9. **`GET /api/leads/` returns at most 500 rows, unpaginated.**
10. **`enrollment_balance()` ignores `FeeTemplate.course`**, so overlapping
    templates for the same (year, campus, program) resolve arbitrarily.
11. **Audit log endpoints are superuser-only in code** with no permission key
    and no UI.
12. **Some upload fields still use plain `FileField`** rather than
    `SecureFileField` — safe, low-risk cleanup.

## 13.10 Quick reference — where things live

| I need to… | Go to |
|---|---|
| Change who can do something | `apps/roles/seed.py` + the view's `required_perm` / `perm_base` |
| Change how a message is sent | `apps/notifications/` + the `settings.py` registries |
| Change a business rule | The module's `services.py` — not the view |
| Change campus scoping | The module's `permissions.py::filter_visible` |
| Add a scheduled job | A management command + the host's cron |
| Debug a failed message | `NotificationDispatchLog` |
| Debug a permission problem | `GET /api/auth/me/` → `permissions`, `modules`, `campuses` |
| Find an endpoint | `apps/<module>/urls.py` |
| Find a page | `jd-erp-web/src/router.tsx` |
