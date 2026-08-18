# 5 — Admissions (`admissions`)

Mounted at `/api/admissions/` plus the unauthenticated
`/api/public/application/<uuid:token>/`. Frontend under `src/pages/students/`,
`src/pages/enrollments/`, `src/pages/admission/`, and the public
`src/pages/public/ApplicationFormPage.tsx`.

---

## 5.1 Purpose

Turns a lead into a student, captures the full application, and manages
enrolments — the join between a student and a batch that the whole academic and
fee side hangs off.

**The central distinction:** a `Student` is a *person record*. An `Enrollment`
is a *lifecycle state* — a student joining a specific batch in a specific
program/campus/year/semester. A student can exist with no enrolment (applied
but not yet admitted) and can hold several over time (promotions across
semesters).

## 5.2 Models

### `Student`

Mirrors the legacy PHP `student_master`. Field groups:

| Group | Fields |
|---|---|
| Identifiers | `application_form_id` (auto, unique, `{INSTITUTE}-{YYYY}-{seq:05d}`), `registration_number` (set by hand by HR; shown in place of the form id on the profile) |
| Identity | `student_name`, `father_name`, `mother_name`, `gender`, `dob`, `category`, `study_medium`, `nationality`, `blood_group` |
| Placement | `institute`, `campus`, `program`, `course`, `academic_year` (→ `master`) |
| Addresses | current + permanent: `address`, `city`, `state`, `pincode` |
| Contacts | `student_mobile`, `father_mobile`, `mother_mobile`, `student_email`, `father_email`, `mother_email`, `institute_email`, occupations |
| Media | `photo` |
| Links | `user_account` (1:1 → `User`), `parent_user_account` (1:1 → `User`), `lead_origin` (1:1 → `Lead`), `portal_temp_password` |

Phones are validated against `^\+?[1-9]\d{7,14}$` (international format).

### `StudentDocument`

Educational certificates and scanned IDs (legacy `extradata`). One row per
`header`: `SSLC`, `PUC`, `DIPLOMA`, `UG`, `PG`, `AADHAAR`, `PASSPORT`, `PAN`,
`PHOTO`, `OTHER` — with `regno_yearpassing`, `school_college`,
`university_board`, `certificate_no`, `percent_obtained`, and the `file`.

**Upsert semantics:** `_upsert_documents` keys on `(student, header)`, so a
re-submitted application replaces the row under that header instead of
appending a duplicate.

### `StudentRemark`

Free-form admin notes. Append-only from the UI so context is never lost.

### `Enrollment`

| Field | Notes |
|---|---|
| `student`, `program`, `course`, `semester`, `campus`, `batch`, `academic_year` | All `PROTECT` |
| `status` | `1 PENDING` · `2 ACTIVE` · `3 PROMOTED` · `4 DROPPED` · `5 ALUMNI` |
| `elective_subjects` | free text |
| `entry_date`, `entry_user` | |

`status = ACTIVE` is what makes a student appear in an attendance roster, a
batch roster and a courseware publish. Changing it has wide effects — see
§5.9.

## 5.3 Two ways a student gets created

### A. Promotion from a lead (`services.promote_lead_to_student`)

Staff action, `POST /api/leads/<id>/promote/`. Atomic:

1. Refuses if the lead already has a `promoted_student`.
2. Resolves `institute` from `lead.campus.institute` — **errors if the campus
   has no parent institute**.
3. Picks the `AcademicYear` with `is_current=True` — **errors if none is set**.
4. Creates a `User` with a unique username derived from the lead's email
   local-part (or name) and a `secrets.token_urlsafe(12)` password; adds the
   lead's campus to `user.campuses`.
5. Creates the `Student` with a generated `application_form_id` and
   **placeholder values** — `gender=OTHER`, `dob="2000-01-01"`,
   `nationality=INDIAN`, `category=GENERAL`. These are meant to be replaced by
   the real application form.
6. Moves the lead to `application_submitted` and writes a status-history entry.
7. Returns credentials **once** — the response is the only place the plaintext
   password appears in that flow.

### B. Public self-fill application (`services.submit_application_from_lead`)

Student-facing, no auth, via `Lead.application_token`:

```
GET  /api/public/application/<uuid:token>/     → pre-fill (name, email, phone, campus, program)
POST /api/public/application/<uuid:token>/     → submit (JSON or multipart with photo + document files)
```

Behaviour:

- **Re-submits are allowed by design.** Students fill incrementally; the
  counsellor reviews and asks for the gaps. The same token stays valid.
- **Empty values never overwrite existing data** (`_apply_payload_to_student`).
- The student may override `campus` and `program`, but the program must be
  offered at that campus or the submit is rejected.
- If `lead.application_locked_for_student` is True → `PermissionError` → 403.
  GET still works.
- First submit creates the `Student` + `User` and returns temporary
  credentials; later submits return an empty `creds` dict.
- Changing `student_email` mirrors onto the linked `User.email` so portal login
  keeps working.
- Documents arrive as a JSON array (a string when sent multipart) index-aligned
  with the uploaded files.

## 5.4 Access control

`apps/admissions/permissions.py`:

- `StudentAccessPolicy` — HR-facing endpoints need `admissions.student.view`;
  object access requires the student's campus to be in `user.campuses` unless
  the caller holds `admissions.student.view_all_campuses`.
- `filter_visible(qs, user)` applies the same scope to lists.
- `is_self_student(user, student)` backs the `me/` endpoints.

Keys are split finely — `admissions.student.edit` covers only ordinary profile
fields; everything else is separate:

| Key | Guards |
|---|---|
| `admissions.student.view` / `.view_all_campuses` | List / cross-campus |
| `admissions.student.view_sensitive` | Personal, family and address detail |
| `admissions.student.view_education` | Education history |
| `admissions.student.view_attendance` / `.view_fees` | Those profile sections |
| `admissions.student.create` | Add (from a promoted lead) |
| `admissions.student.edit` | Basic details only |
| `admissions.student.transfer` | Move institute / campus / program / course |
| `admissions.student.set_registration_no` | Registration number |
| `admissions.student.view_remarks` / `.add_remark` | Admin remarks |
| `admissions.student.promote` | Batch/semester promotion |
| `admissions.student.send_credentials` | Send portal credentials + reset the password |
| `admissions.student.send_handbook` | Handbook email |
| `admissions.document.view/add/delete` | Student documents |
| `admissions.enrollment.view/add/edit` | Enrolments |
| `admissions.enrollment.send_undertaking` | Email the fee-undertaking PDF |
| `admissions.parent.view` / `.add` | Parent portal account |

Note the cross-module rule: **promoting a lead requires both
`leads.lead.promote` and `admissions.student.create`.**

## 5.5 Endpoints

| Method + path | Purpose |
|---|---|
| `GET /api/admissions/students/` | Campus-scoped list |
| `GET/PATCH /api/admissions/students/<id>/` | Field-group permission checks inside `patch` |
| `GET/POST /api/admissions/students/<id>/documents/`, `DELETE /api/admissions/documents/<id>/` | |
| `GET/POST /api/admissions/students/<id>/remarks/` | |
| `GET/POST /api/admissions/students/<id>/parent/` | Provision the parent account (handled by `apps.portal.views.ProvisionParentView`) |
| `POST /api/admissions/students/<id>/send-portal-credentials/` | Resets the password, mirrors it to `portal_temp_password`, emails it |
| `POST /api/admissions/students/<id>/send-handbook/` | |
| `GET /api/admissions/me/`, `GET /api/admissions/me/documents/` | Student's own record |
| `GET/POST /api/admissions/enrollments/`, `GET/PATCH /api/admissions/enrollments/<id>/` | |
| `POST /api/admissions/enrollments/<id>/undertaking/` | Renders + emails the fee-undertaking PDF |
| `POST /api/admissions/batch-promote/` | Bulk promote a batch to the next semester/batch |
| `POST /api/admissions/batch-graduate/` | Bulk graduate (needs `academics.certificate.graduate`) |

## 5.6 The fee undertaking (`services_undertaking.py`)

A signed declaration of course, duration, fee, down payment and installment
schedule, rendered to PDF with fpdf2 and emailed. It is **not persisted** —
re-rendering is idempotent because the source data lives in the DB.

Its arithmetic mirrors the legacy PHP rule:

```
down payment  +  Σ remaining installments  +  approved concessions  =  total fee
```

Conventions it relies on, set by the React enrolment-create form:

- **Down payment = the installment with `sequence = 1` whose `description`
  starts with "Down payment"**. If absent, the lowest sequence is used.
- Concession = sum of `APPROVED` `Concession` rows on the enrolment.

If the frontend ever stops writing that description, the PDF silently treats
the first installment as the down payment. Keep the convention.

Unicode is transliterated to Latin-1 (`₹` → `INR `, smart quotes → ASCII)
because fpdf2's core fonts are Latin-1 only.

## 5.7 Portal provisioning (`services_portal_email.py`)

"Send portal credentials" resets the student's password, mirrors the plaintext
onto `Student.portal_temp_password`, and queues
`student.portal_credentials.email` with `{name, email, username, password,
institute, login_url}`. `login_url` comes from
`settings.STUDENT_PORTAL_LOGIN_URL`. The trigger routes to the `PORTAL` sender
domain (`mail.jdinstitute.com`).

`clear_temp_password_for(user)` wipes the mirror on the student's first
successful login and on a self-service password change.

## 5.8 Handbook (`services_handbook.py`)

Plain-text email, sent directly through `apps.notifications.email.send_email`
(not through the queue — so **it produces no `NotificationDispatchLog` row**).
There is a documented extension point: add a `handbook_pdf` FileField to
`Institute` and pass it via `attachments=[(name, content, "application/pdf")]`.

## 5.9 Change impact

| If you change… | Effect |
|---|---|
| `Enrollment.status` away from `ACTIVE` | The student disappears from attendance rosters (`roster_for`), batch rosters, courseware publishes and the portal's "current enrolment" resolution. Past attendance rows persist |
| `application_form_id` format | The sequence generator scans by prefix; a format change restarts numbering. Existing ids are unaffected |
| The placeholder values in `promote_lead_to_student` | Students promoted but never self-filling would carry `dob = 2000-01-01`. Any report on age or DOB should exclude them |
| Deleting a `Student` | Blocked by `PROTECT` from `Enrollment`, `Attendance`, `MarksEntry`, `Certificate`, submissions, test attempts. Documents, remarks, appointments, leaves and document-requests cascade |
| `Student.user_account` | The portal resolves the student *from* the user. Detaching it locks the student out and orphans the `User` |
| `AcademicYear.is_current` | Both creation paths fail with "No current AcademicYear is set" if none is marked |
| `Campus.institute` = null | Both creation paths fail. Legacy campuses may have it blank — check before go-live |
