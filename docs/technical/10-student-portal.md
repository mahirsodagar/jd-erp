# 10 — Student & Parent Portal (`portal`, `student_leaves`, `student_documents`, `appointments`)

Mounted at `/api/portal/`, `/api/student-leaves/`, `/api/student-documents/`,
`/api/appointments/`. Frontend under `src/pages/portal/` inside `PortalLayout`,
reached at `/#/portal/...` — the same bundle as the staff app but a separate
layout, sidebar and login page.

---

## 10.1 The identity model

There is no separate student user table. A portal user is an ordinary
`accounts.User` that some `Student` row points at:

- `Student.user_account` → this user **is** the student
- `Student.parent_user_account` → this user is that student's **parent**

`apps/portal/helpers.py::resolve_portal_context(user)` is the single source of
truth. It returns a `PortalContext`:

```python
@dataclass
class PortalContext:
    student: Student
    is_parent: bool
    enrollment: Enrollment | None   # the ACTIVE one, else the most recent of any status
```

Every portal endpoint calls this through a permission class, which also stashes
the result on `request.portal_ctx` so the view does not resolve it twice.

## 10.2 Two permission classes

| Class | Allows | Used for |
|---|---|---|
| `IsStudentOrParent` | Both | Profile, dashboard, attendance, timetable, lessons |
| `IsStudentOnly` | Students only (rejects parents) | Assignments, courseware, tests, leaves, document requests, appointments, feedback, qualifications, change-password |

**Parents get read-only visibility of the academic picture and nothing that
acts on the student's behalf.** If you add a portal endpoint, pick the class
deliberately — `IsStudentOrParent` on a write endpoint would let a parent
submit an assignment.

Note that portal access needs **no permission key at all**. Being linked to a
`Student` row is the entire authorisation.

## 10.3 Portal endpoints (`/api/portal/`)

| Path | Class | Notes |
|---|---|---|
| `me/` | OrParent | Profile + enrolment context |
| `change-password/` | StudentOnly | Also clears `portal_temp_password` |
| `dashboard/` | OrParent | Headline tiles |
| `attendance/calendar/`, `attendance/report/` | OrParent | |
| `timetable/` | OrParent | From `ScheduleSlot` for the active batch |
| `assignments/subjects/`, `assignments/`, `assignments/<id>/submit/` | StudentOnly | Submission creates/updates `AssignmentSubmission` |
| `courseware/subjects/`, `courseware/` | StudentOnly | Filtered by `CoursewareMapping` |
| `tests/subjects/`, `tests/`, `tests/<id>/`, `tests/<id>/submit/`, `tests/<id>/result/` | StudentOnly | Drives `TestAttempt` / `TestResponse` |
| `leaves/` | StudentOnly | Creates `StudentLeaveApplication` |
| `document-requests/` | StudentOnly | Creates `DocumentRequest` |
| `appointments/`, `appointments/faculty/`, `appointments/<id>/cancel/` | StudentOnly | |
| `lessons/` | OrParent | Only lesson plans where `is_visible_to_students` |
| `feedback-link/`, `feedback/options/` | StudentOnly | The batch's external feedback link + the subject/instructor options for in-app feedback |
| `qualifications/` | StudentOnly | Educational documents (`StudentDocument`) |

Fee visibility for students lives in the fees app: `GET /api/fees/me/`,
`/me/receipts/`, `/me/receipts/<id>/pdf/`.

`ProvisionParentView` also lives here but is mounted on the admissions side at
`POST /api/admissions/students/<id>/parent/` (keys `admissions.parent.view` /
`.add`). It creates the parent `User` and links it via `parent_user_account`.

---

## 10.4 `student_leaves` — the staff side of student leave

`StudentLeaveApplication` — distinct from the employee `LeaveApplication`.

| Field | Notes |
|---|---|
| `student`, `leave_date`, `leave_edate`, `student_remarks` | A DB check constraint enforces `leave_edate >= leave_date` |
| `status` | SUBMITTED / APPROVED / REJECTED |
| `batch_mentor_email` | **Snapshotted at submission.** This is what routes the request |
| `module_mentor_email`, `cc_emails` (JSON list) | |
| `approver_remarks`, `decided_by`, `decided_at` | |
| `days` (property) | `(edate − date).days + 1` |

**The mentor console is self-service and needs no key.** A batch mentor is
identified by matching `batch_mentor_email`; the queue is simply empty for
anyone who mentors nothing. Keys widen or authorise:

| Key | Effect |
|---|---|
| `student_leaves.view_all` | Every student leave, not just your batches |
| `student_leaves.approve` / `.reject` | Separate keys; scoped to your batches unless you also hold `view_all` |
| `student_leaves.report.view` / `.view_all` | The report page, campus-scoped |
| `student_leaves.delete` | Delete an application |

Endpoints: `GET /api/student-leaves/`, `GET /api/student-leaves/report/`,
`POST /api/student-leaves/<id>/decide/`, `DELETE /api/student-leaves/<id>/`.

Status emails use `leaves.application_status_student.email` → MSG91 template
`leave_application_status_student`, routed to the `HR` sender domain.

---

## 10.5 `student_documents` — institute-issued document requests

`DocumentRequest` — a student asks for a `TC`, `BONAFIDE`,
`STUDY_CERTIFICATE`, `BANK_LETTER`, `LOR` or `OTHER` (with a free-text
`doc_type_other`), giving a `purpose`. Staff decide and optionally attach the
issued file.

States SUBMITTED / APPROVED / REJECTED with `attachment`, `approver_remarks`,
`decided_by`, `decided_at`.

| Key | Effect |
|---|---|
| `student_documents.view` / `.view_all` | Campus-scoped list / all campuses |
| `student_documents.approve` | Approve **and attach the issued file** |
| `student_documents.reject` | Reject |

Endpoints: `GET /api/student-documents/`,
`POST /api/student-documents/<id>/decide/`. Students create requests at
`POST /api/portal/document-requests/`.

> This is distinct from `academics.Certificate`, which is the formal, numbered,
> snapshot-backed certificate flow with eligibility rules. `DocumentRequest` is
> the lightweight "student asks the office for a letter" path.

---

## 10.6 `appointments` — student meeting requests

`StudentAppointment` — a student requests a meeting with **either** a generic
office team **or** a named faculty member. Exactly one of `team` / `faculty` is
set, enforced in the service layer.

Teams: MANAGEMENT, ADMISSIONS, ACCOUNTS, ACADEMICS, EXAMINATION, PLACEMENT,
OTHER.

States: REQUESTED → CONFIRMED / DECLINED → COMPLETED, plus CANCELLED
(student-initiated).

### Service rules (`services.py`)

- `request_appointment` rejects both-or-neither targets, and **blocks a second
  open request against the same target** (one REQUESTED or CONFIRMED
  appointment per team/faculty per student).
- `decide_appointment` only acts on REQUESTED. Confirming **falls back to the
  student's proposed slot** when staff do not supply a new date/time — so
  "confirm as-is" needs no extra input.
- `complete_appointment` only acts on CONFIRMED.
- `cancel_appointment` only acts on REQUESTED or CONFIRMED.

**Notifications are in-app only** — the student sees the outcome in the portal.
Nothing is sent over WhatsApp, SMS or email. This is deliberate.

### Permissions

A faculty member reaching **their own** queue is self-service and needs no key
— the list is empty for anyone nothing is addressed to.

| Key | Effect |
|---|---|
| `appointments.view_all` | Every colleague's requests |
| `appointments.confirm` | Confirm + set date, time, venue |
| `appointments.decline` | Decline |
| `appointments.complete` | Record that the meeting happened |

Confirming/declining authorise the meeting; completing records it — hence three
keys.

Endpoints: `GET /api/appointments/`,
`POST /api/appointments/<id>/decide/`, `POST /api/appointments/<id>/complete/`.

---

## 10.7 Portal login and credentials

Students log in at `/#/portal/login` (`PortalLoginPage.tsx`) against the same
`POST /api/auth/login/` endpoint — there is no separate auth path. The frontend
routes them to `/portal` because `/api/auth/me/` returns `is_student: true`.

Credentials are issued by
`POST /api/admissions/students/<id>/send-portal-credentials/`, which resets the
password, mirrors it to `Student.portal_temp_password`, and emails
`student.portal_credentials.email` from `mail.jdinstitute.com`
([chapter 5](05-admissions.md) §5.7).

---

## 10.8 Change impact

| If you change… | Effect |
|---|---|
| `Student.user_account` | The portal resolves the student from the user — unlinking locks them out entirely |
| `Enrollment.status` | `resolve_portal_context` prefers the ACTIVE enrolment. With none active it falls back to the most recent of any status, so a dropped student still sees a stale context. Check this if portal data looks wrong |
| `Batch.mentor` / `batch_mentor_email` | Existing leave applications keep the **snapshotted** email, so re-assigning a mentor does not reroute pending requests |
| A portal endpoint's permission class | `IsStudentOrParent` on a write endpoint lets parents act as the student |
| `CoursewareMapping` rows | Portal courseware is driven entirely by these. A student enrolled after publication sees nothing until the topic is republished |
| `Lesson` approval state | Students only see plans where both reviewers approved **and** `display_date` has passed |
