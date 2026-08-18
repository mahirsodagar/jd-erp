# 9 — Audit & Reports (`audit_reports`)

Mounted at `/api/audit-reports/`. Frontend under `src/pages/audit/` plus
`src/pages/MyDailyReportPage.tsx` and `src/pages/MyAdminDailyReportPage.tsx`.

Not to be confused with the `audit` app ([chapter 2](02-platform-foundations.md)
§2.3), which logs authentication events. This module is the institute's
**internal accountability and quality-assurance suite**.

---

## 9.1 What it contains

Nine independent report types plus a dynamic form builder and five dashboards.
Each report is its own model with its own submit/review lifecycle. They share
only the permission module (`audit`) and the dashboard aggregations.

| # | Model | Cadence | Filled by | Reviewed by |
|---|---|---|---|---|
| 1 | `FacultyDailyReport` | Daily | Faculty | Auditor |
| 2 | `AdminDailyReport` | Daily | Admin/HR staff | Auditor |
| 3 | `CourseEndReport` | Per (instructor, subject, batch) | Instructor | HOD |
| 4 | `BatchMentorReport` | Monthly | Batch mentor | Auditor |
| 5 | `StudentFeedback` | Mid- and end-of-course | Students | Auditor |
| 6 | `FacultySelfAppraisal` | Quarterly | Faculty | Auditor |
| 7 | `ComplianceFlag` | Ad hoc | Auditor | — |
| 8 | `AuditForm` + fields/submissions/answers | Ad hoc | Any targeted role | Auditor |
| 9 | `ZeroHourReport` | Per 0-Hour session | Class mentor (under **Academics**) | Auditor (under **Audit**) |

---

## 9.2 The daily logs

**`FacultyDailyReport`** — unique on `(faculty, date)`. Three
description + hours pairs per day: academic documentation, non-academic work,
others. Rendered as a monthly grid.

**`AdminDailyReport`** — unique on `(rep_date, user)`. Two free-text slots
(9:30–12:30, 1:30–5:30).

**A deliberate split you must understand:** filling *your own* daily report
lives under the **Dashboard** module (`dashboard.daily_report.submit`,
`dashboard.admin_daily.submit`), while reading *everyone's* lives under
**Audit** (`audit.faculty_daily.view_all`, `audit.admin_daily.view_all`).
The `Faculty` baseline role grants the former, not the latter.

`GET /api/audit-reports/faculty-daily-computed/` derives, from the timetable
and leave data, per-day scheduled class hours and leave hours for one faculty —
so an auditor can compare what was logged against what was scheduled. It skips
Sundays and does **not** net holidays.

---

## 9.3 Periodic reports

**`CourseEndReport`** — unique on `(instructor, subject, batch)`. Filed when an
instructor finishes a course: `summary`, `learning_outcomes`, `challenges`,
`suggestions`, plus `avg_attendance_pct` / `avg_marks_pct`. HOD review states:
PENDING / APPROVED / RETURNED.

**Approving and returning are separate keys** — sending a report back for
rework is a different act from signing it off.

**`BatchMentorReport`** — unique on `(batch, year, month)`. The class teacher's
monthly read-out: attendance/marks averages, behavioural notes, academic
concerns, dropout risks, initiatives.

Both gained `edit_any` / `delete_any` keys and endpoints late — before that
neither could be corrected by anyone, including superusers, so a typo was
permanent.

---

## 9.4 Student feedback

`StudentFeedback` — unique on `(student, subject, instructor, batch, type)`,
type MIDWAY or END. Four ratings (overall, clarity, engagement,
responsiveness) plus `what_worked` and `suggestions`.

**Feedback is anonymous to the instructor.** The API exposes only aggregates
(`audit.report.instructor_feedback` → the per-instructor summary). The key
`audit.feedback.view_all` is what **de-anonymises** it — its label says so
explicitly rather than reading like an ordinary list permission. Grant it
carefully.

Students submit feedback through the portal
(`/api/portal/feedback/options/`, and the external `Batch.feedback_link` when
`feedback_link_enabled`).

---

## 9.5 Self-appraisal and compliance

**`FacultySelfAppraisal`** — unique on `(faculty, year, quarter)`;
achievements, challenges, plans, `green_flags`, `red_flags`, plus
`auditor_remarks`. Keys split own (`view_own`, `submit`) from oversight
(`view_all`, `review`, `edit_any`, `delete_any`).

**`ComplianceFlag`** — one table, two polarities:

- **FLAG 🚩** — a negative anomaly (missed deadline, low attendance, pending
  submission). Has a `severity` (LOW/MEDIUM/HIGH) and is **resolvable**.
- **STAR ⭐** — a positive recognition. Carries a 1–5 `stars` rating and is a
  **permanent record, never resolved**.

Categories are partitioned into `FLAG_CATEGORIES` and `STAR_CATEGORIES`, and
the serializer rejects a star category on a flag and vice versa. A flag can
target a faculty, a batch, a student, or free text.

One key covers both polarities (`audit.compliance.flag`) — raising a concern
and awarding recognition are the same grant. `audit.compliance.view` shows both
lists; `.resolve` closes a flag; `.edit_any` / `.delete_any` back the detail
endpoint added so a flag raised against the wrong colleague can be removed.

---

## 9.6 Zero-Hour report

`ZeroHourReport` — one per batch per `report_date`. Captures batch strength,
0-Hour attendance, first-half and month-end attendance averages, agenda,
outcome, activities, remarks, HOD/Principal discussion and action taken.

**Cross-module by design:** filled under Academics
(`academics.zero_hour.submit` / `.delete`, plus `.edit_any` / `.delete_any` to
make correcting someone else's report delegable), reviewed under Audit
(`audit.zero_hour.view_all`). Two frontend pages exist accordingly:
`src/pages/academics/ZeroHourFormPage.tsx` and
`src/pages/audit/ZeroHourReportsPage.tsx`.

---

## 9.7 The dynamic form builder

A generic, user-defined form system — the same shape as the entrance-exam
feature: definition → typed fields → per-user submission → one answer row per
field.

```
AuditForm (title, description, status DRAFT|PUBLISHED|CLOSED, roles M2M)
   ├── AuditFormField (label, field_type, options, required, help_text,
   │                    config, sort_order)
   └── AuditSubmission (form, submitted_by)
            └── AuditAnswer (submission, field, value JSON)
```

Field types: TEXT, TEXTAREA, RADIO, DROPDOWN, MULTISELECT, CHECKBOX, RATING,
DATE, TIME, DATETIME. `AuditAnswer.value` is normalised per type — a scalar for
text/choice/rating/date, a list for multi-select.

**Targeting.** `AuditForm.roles` limits who sees a form. Reaching a form through
`_can_access_form` — published **and** targeting a role you hold — needs **no
permission key**. That is why the Faculty baseline can fill forms without extra
grants.

`audit.form.view` is a **manager** key, not a plain read: it bypasses both the
PUBLISHED check and role targeting, so a holder can preview drafts aimed at
other roles. Publishing (`audit.form.publish`) is split from editing questions
(`audit.form.edit`) because publishing pushes a form to a whole role's worth of
staff. `audit.form.delete` only works while a form has no responses.

Endpoints: `forms/`, `forms/<id>/`, `forms/<id>/submit/`, `form-roles/`,
`submissions/`, `submissions/<id>/`.

Employees may submit the same form more than once.

---

## 9.8 Dashboards (`services.py`)

Cross-module aggregations, each behind its own key:

| Endpoint | Key | Content |
|---|---|---|
| `dashboards/live-faculty/` | `audit.report.live_faculty` | For every active faculty: today's load, attendance status, whether the daily report was submitted |
| `dashboards/timetable-adherence/` | `audit.report.live_faculty` | Over a window: how many SCHEDULED slots had attendance marked — a proxy for whether the class actually happened |
| `dashboards/batch/<id>/progression/` | `audit.report.consolidated` | Enrolment count, attendance average, marks publication rate, certification status |
| `dashboards/instructor/<id>/feedback-summary/` | `audit.report.instructor_feedback` | Aggregated ratings for one instructor |
| `dashboards/consolidated-monthly/` | `audit.report.consolidated` | Cross-module monthly headlines |

The per-instructor feedback summary and the live-faculty tracker carry their
own keys because they are views of a *named colleague's* activity — the same
reasoning as `academics.attendance.view_instructor_log` and
`leads.report.leaderboard`.

`faculty_daily_computed` uses a `WORKDAY_HOURS` constant to convert leave
day-fractions into hours.

---

## 9.9 Audit filter lookups

Three endpoints exist so the audit pages can build their cascade filters
without the auditor needing `master.*` permissions:

```
GET /api/audit-reports/filters/options/
GET /api/audit-reports/filters/employees/
GET /api/audit-reports/filters/admin-daily-authors/
```

They are audit-gated. If you add a filter dropdown to an audit page, extend
these rather than calling `/api/master/...` — otherwise you will re-introduce
the permission coupling they were built to remove.

---

## 9.10 Change impact

| If you change… | Effect |
|---|---|
| `audit.feedback.view_all` grants | Directly controls whether student feedback is anonymous. Treat as a privacy decision, not a convenience |
| `audit.form.view` grants | Holder can see every draft form, including ones targeting other roles |
| A report's `unique_together` | Existing rows may violate a tightened constraint. Check before migrating |
| `ComplianceFlag.Category` values | Must stay partitioned between `FLAG_CATEGORIES` and `STAR_CATEGORIES` or the serializer validation breaks |
| Attendance or timetable data | Feeds `timetable_adherence`, `batch_progression`, `live_faculty_tracking` and `faculty_daily_computed` — all are read-side derivations, so they change immediately |
| Deleting an `AuditForm` | Only permitted while it has no responses; fields and submissions cascade |
| `Batch.mentor` | Determines who is expected to file `BatchMentorReport` and `ZeroHourReport` rows |
