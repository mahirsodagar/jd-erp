# 7 — Academics (`academics`, `courseware`)

Mounted at `/api/academics/` and `/api/courseware/`. The largest module in the
system: `views.py` alone is ~1,950 lines, split across several supporting
service and view files.

Frontend: `src/pages/schedule/`, `attendance/`, `assignments/`, `marks/`,
`tests/`, `lessons/`, `certificates/`, `alumni/`, `transcripts/`,
`courseware/`, `academics/`.

---

## 7.1 File map

| File | Contents |
|---|---|
| `models.py` | All 12 models |
| `views.py` | Schedule, attendance, assignments, marks, transcripts, lessons, certificates, alumni, tests |
| `services.py` | Timetable conflict detection + bulk weekly publish |
| `attendance_service.py` | Roster, bulk mark, freeze/unfreeze, absentee notifications, summaries |
| `attendance_reports.py` + `attendance_report_views.py` | The five-tab Attendance Report page |
| `batch_report.py` + `batch_report_views.py` | Batch list, roster, feedback link |
| `closing_report.py` + `closing_report_views.py` | Batch-closure completion sheet |
| `marks_service.py` | Transcript assembly |
| `test_service.py` | Online-test mapping, auto-grading, scoring |
| `lesson_service.py` | Lesson-plan dual approval |
| `cert_service.py` | Certificate eligibility, numbering, PDF |
| `permissions.py` | `ScheduleAccess`, `TimetableAccess`, helpers |

---

## 7.2 Timetable (`ScheduleSlot`)

One published class: `(batch, subject, instructor, classroom, time_slot, date)`
with `status` SCHEDULED / CANCELLED / COMPLETED. Legacy `timetable_pub`.

### Conflict rules (`services.detect_conflicts`)

| Clash | Severity |
|---|---|
| Same **instructor**, same date + time slot | **Hard error** — create rejected |
| Same **batch**, same date + time slot | **Hard error** |
| Same **classroom**, same date + time slot | **Soft warning** — allowed with `force=true`, which sets `classroom_conflict_overridden=True` and needs `academics.schedule.override_conflict` |

Both hard rules are additionally enforced by partial unique DB constraints
(`uniq_instructor_date_slot_active`, `uniq_batch_date_slot_active`, both
conditioned on `status='SCHEDULED'`). The service exists to give a friendly 409
before the database raises.

### Endpoints

| Path | Notes |
|---|---|
| `GET/POST /api/academics/schedule/` | |
| `GET/PATCH/DELETE /api/academics/schedule/<id>/` | DELETE cancels |
| `POST /api/academics/schedule/bulk-weekly/` | One slot per matching weekday in a date range (`weekday`: 0=Mon … 6=Sun) |
| `POST /api/academics/schedule/bulk-weekly-grid/` | Publish a whole week's grid |
| `POST /api/academics/schedule/conflict-check/` | Dry run |
| `GET /api/academics/timetable/me/` | **Ungated** — the caller's own sessions, whether they are an instructor or a student |

### Permissions

`TimetableAccess` gates staff reads on `academics.schedule.view`; mutations use
`ScheduleAccess` → `academics.schedule.{add,edit,delete}`. `/timetable/me/`
sits outside both classes on purpose — students and instructors reach their own
schedule without holding any key.

---

## 7.3 Attendance

`Attendance` — one row per `(schedule_slot, student)`, created on first mark.
Statuses: PRESENT, ABSENT, LATE, ON_DUTY, EXCUSED.

### Roster

`roster_for(slot)` = **active enrolments in `slot.batch`**, resolved live. The
roster is deliberately *not* snapshotted on the slot: students added or removed
from a batch show up in the next attendance view, while past attendance rows
persist unchanged.

`bulk_mark()` refuses any `student_id` outside that roster and any invalid
status, returning `{created, updated, skipped}` with a reason per skip. **It
does not check the freeze flag** — the caller does, so an admin holding the
right key can call the service directly.

### Freezing

`ScheduleSlot.attendance_frozen` + `_at` + `_by`. Once frozen, editing requires
`academics.attendance.edit_frozen`. Freeze/unfreeze needs
`academics.attendance.freeze`.

### Absentee notifications (`notify_absent_students`)

Needs `academics.attendance.notify_absent`. For each ABSENT row it queues, with
context `{name, subject, date, slot, campus, batch}`:

- `student_absent_email` → student email
- `parent_absent_email` → father's and mother's email (mother only if different)
- `student_absent_wa` → student mobile
- `attendance.student_absent_v2.sms` → student mobile
- `attendance.parent_absent_v2.sms` → father's mobile, and mother's **only if
  the number differs** (so a shared handset is not double-charged)

### Reports

`batch_attendance_summary` and `student_attendance_summary` compute
`present_pct = (PRESENT + LATE + ON_DUTY) / total_scheduled_slots`. Note the
denominator is **scheduled slots in range**, not marked entries — so unmarked
sessions drag the percentage down. `unmarked` is reported separately.

The five-tab Attendance Report page (`attendance_reports.py`) covers:
Activity, Remarks, Module grid, Batch-wise, Student-wise, Instructor log —
each with its own endpoint under `/api/academics/attendance/report/`.

### Permissions

| Key | Action |
|---|---|
| `academics.attendance.view_roster` | See a slot's roster |
| `academics.attendance.mark` | Mark any slot |
| `academics.attendance.edit_frozen` | Edit after freeze |
| `academics.attendance.freeze` | Freeze / unfreeze |
| `academics.attendance.notify_absent` | Send absence alerts |
| `academics.attendance.view_report` / `.view_instructor_log` / `.view_all_campuses` | Reports |

**An instructor keeps implicit rights over their own slot** — view the roster,
mark, freeze — without holding any of these keys.

---

## 7.4 Assignments

`Assignment` targets a `subject` plus **either** a specific `batch` **or** a
whole `program` (batch null ⇒ every batch in the program). Carries
`max_marks`, `due_date`, `attachment`, cover `image`, `is_published`.

`AssignmentSubmission` — one per `(assignment, student)`, with `file` and/or
`text_response`, `extended_due_date` (per-student deadline override),
`status` SUBMITTED / LATE / GRADED / RESUBMIT, `grade`, `feedback`.

Endpoints: list/create, detail, `/submissions/`, `/submit/`,
`/submissions/<id>/grade/`, and `assignments/me/` for students.

Keys: `academics.assignment.view`, `.view_all_campuses`, `.create` (own),
`.edit_any`, `.delete_any`, `.view_submissions`, `.grade`. Owners always retain
rights over what they created; the `_any` keys govern other people's work.

Notification: `academics.assignment_assigned.email` → MSG91 template
`assignment_assigned`.

---

## 7.5 Marks and transcripts

`MarksEntry` — unique on `(student, subject, semester)`, also carrying `batch`.
Split into internal (`ia_marks` / `ia_max`, default 20) and external
(`ea_marks` / `ea_max`, default 80) with computed `total_marks`, `total_max`,
`percentage`.

**Workflow:** faculty draft → HOD publishes. Once `published=True`, edits
require `academics.marks.edit_published`. `unpublish` retracts.

Transcripts (`marks_service.build_transcript`) are available at
`transcript/student/<id>/` (needs `academics.transcript.view_any`) and
`transcript/me/`. Unpublished marks are excluded unless the caller holds
`academics.transcript.view_drafts`.

---

## 7.6 Online tests

```
Test ── TestQuestion (MCQ | SHORT, options, answer_key, marks, sort_order)
  │
  └── TestAttempt (test, student, start_dt, end_dt, status, total_score)
          └── TestResponse (attempt, question, answer, marks_awarded, is_auto_graded)
```

`Test.status`: DRAFT → PUBLISHED → CLOSED. `total_marks` is auto-recomputed
from the sum of question marks. Faculty "map" a test to students, which creates
the `TestAttempt` rows with the availability window.

MCQ answers auto-grade against `answer_key` (the option index as a string);
SHORT answers need `POST /api/academics/responses/<id>/review/`
(`academics.test.review`).

Students take tests through the portal (`/api/portal/tests/...`), not these
endpoints.

This is the same shape as the leads Entrance Exam feature
([chapter 4](04-leads-crm.md) §4.8) — the difference is the subject
(`Student` vs `Lead`) and that exams use a public token because prospects have
no login.

---

## 7.7 Lesson plans

`Lesson` — a faculty-authored plan for a batch, with `unit`, `assignment`,
a submission deadline that may be a datetime **or** a free-text description
("after the 4th session"), module/semester-end projects, visits & workshops,
and an optional `display_date`.

**Dual approval.** Two reviewers, both `Employee` FKs: `hod` and
`class_mentor`. Each has its own `status` / `remarks` / `decided_at`.
`overall_status` aggregates:

- any `REJECTED` → REJECTED
- both `APPROVED` → APPROVED
- any `IMPROVE` → IMPROVE
- otherwise → SUBMITTED

`is_visible_to_students` requires APPROVED **and** `display_date` not in the
future. Students see approved plans at `/api/portal/lessons/`.

Keys: `academics.lesson.view`, `.view_all`, `.create`, `.edit_any`,
`.delete_any`. Review happens through `POST /api/academics/lessons/<id>/review/`.

---

## 7.8 Certificates and alumni

### `Certificate`

Six types with per-type eligibility rules (`cert_service.check_eligibility`):

| Type | Requires |
|---|---|
| `BONAFIDE` | Enrolment ACTIVE |
| `PROVISIONAL` | Enrolment ALUMNI; marks exist (may be unpublished) |
| `COMPLETION` | Enrolment PROMOTED or ALUMNI; marks exist; every published mark ≥ 40 % of total_max |
| `TRANSFER` | Enrolment DROPPED or ALUMNI |
| `CHARACTER` | Any enrolment |
| `NO_DUES` | Fee balance is zero |

`academics.certificate.override_eligibility` issues despite a failed check.

States REQUESTED → ISSUED / REJECTED / REVOKED. On issue, a `certificate_no` is
stamped and a **`snapshot` JSON is frozen** onto the row, so later edits to the
student or program never change an already-issued artefact. The PDF is rendered
on demand from that snapshot.

Keys: `.view_all`, `.view_all_campuses`, `.request_for_others`, `.issue`,
`.reject`, `.override_eligibility`, `.graduate`.

### `AlumniRecord`

1:1 with `Student`, created at graduation. Snapshot of `graduation_year`,
`final_program`, `final_batch`, `final_percentage`, plus a living profile
(`current_status`, `workplace`, `job_title`, `linkedin_url`, last known
contacts).

Graduation happens at `POST /api/academics/enrollments/<id>/graduate/`
(`academics.certificate.graduate`) or in bulk via
`POST /api/admissions/batch-graduate/`. Both set the enrolment to ALUMNI and
create the alumni record.

---

## 7.9 Batch Report and Closing Report

Two batch-level sheets, documented in more depth in the frontend repo
(`BATCH_REPORT_DOCUMENTATION.md`, `CLOSING_REPORT_DOCUMENTATION.md`).

**Batch Report** (`/api/academics/batch-report/`) — batch list with headcounts,
a full student roster, and the batch feedback link.

> Security note: the roster returns personal, family and address details for a
> whole batch at once, which used to bypass
> `admissions.student.view_sensitive`. It now needs its own
> `academics.batch_report.view_roster` key **and** withholds the sensitive
> columns unless the caller *also* holds `admissions.student.view_sensitive`.
> Keep both checks if you touch this endpoint.

**Closing Report** (`/api/academics/closing-report/<batch>/`) — the
batch-closure completion sheet. Carries no contact data (name, application id,
attendance %, and three editable columns), so it needs no `view_sensitive`
interaction. Backed by `ClosingAward`, one row per `(student, batch)` with
`awards` / `portfolio` / `remarks`, each upserted independently on blur.

Keys: `academics.batch_report.{view,view_roster,view_all_campuses,edit_feedback}`
and `academics.closing_report.{view,view_all_campuses,edit}`.

---

## 7.10 0-Hour report

`ZeroHourReport` lives in `audit_reports` but is **filled** under Academics
(`academics.zero_hour.submit` / `.delete` / `.edit_any` / `.delete_any`) and
**reviewed** under Audit (`audit.zero_hour.view_all`). See
[chapter 9](09-audit-reports.md) §9.6.

---

## 7.11 Courseware (`courseware`)

Teaching material published to a batch. Replaces legacy `courseware_master`.

```
CoursewareTopic (subject, batch, name, description, image, is_published)
   ├── CoursewareAttachment  (name, file)   — many per topic
   └── CoursewareMapping     (topic, student) — per-student visibility
```

When staff publish a topic to a batch, **one `CoursewareMapping` row is created
per active student in that batch**. Students added to the batch afterwards do
not retroactively get mappings — republish, or add mappings manually, if that
matters.

Endpoints: `topics/` (list/create), `topics/<id>/`, `topics/<id>/attachments/`,
`attachments/<id>/`. Keys: `courseware.view/add/edit/delete`.
Students read it at `/api/portal/courseware/`.

---

## 7.12 Change impact

| If you change… | Effect |
|---|---|
| `Enrollment.status` off ACTIVE | Student drops out of attendance rosters, batch rosters and future courseware publishes. Existing attendance and mappings persist |
| Cancel a `ScheduleSlot` | Frees the instructor/batch unique constraint for that date+slot. Existing `Attendance` rows cascade-delete with the slot if the slot is deleted outright (`CASCADE`) — cancel instead |
| Delete a `ScheduleSlot` | **Cascades to its attendance rows.** Prefer `status=CANCELLED` |
| Publish marks | Makes them visible in the student transcript and portal; further edits need `edit_published` |
| Issue a certificate | Freezes `snapshot` — later student edits will not appear on a re-render |
| Change `Batch.mentor` | Re-routes student-leave approvals, batch-mentor reports and 0-Hour reports |
| Add a `Subject` | Immediately available to schedule, assignments, marks, tests, courseware — there is no curriculum table to update |
| `PASS_PERCENTAGE` in `cert_service` | Changes COMPLETION certificate eligibility for everyone |
