# 3 — Master Data (`master`)

Mounted at `/api/master/`. Frontend pages under `src/pages/master/`, all built
on the shared `_MasterShell.tsx`.

---

## 3.1 Purpose

Every reference list the rest of the system points at. Almost all foreign keys
in the domain apps terminate here, mostly with `on_delete=PROTECT`. **This app
has no business logic — but it constrains everything.**

## 3.2 The organisational hierarchy

```
Institute            JD Institute of Fashion Technology (JDIFT)
  │                  JD Educational Trust / School of Design (JDSD)
  ├── Campus         BLR, GOA, …   (code is used in generated IDs)
  │     ├── Classroom
  │     ├── Batch ───────────┐
  │     └── (M2M) Program ───┤
  │                          │
  ├── Program                │   category: REGULAR | SHORT | NEW
  │     └── Course           │   degree_type: "B.Des" / "Diploma" / …
  │                          │
  └── AcademicYear ──────────┘   is_current drives several defaults
        ├── TimeSlot             (timings can shift year to year)
        └── FeeTemplate
```

Independent lists: `State` → `City`, `Degree`, `Semester`, `Subject`,
`LeadSource`.

## 3.3 Model reference

| Model | Key fields | Consumed by |
|---|---|---|
| `Institute` | `name`, `code` (unique), `logo`, `email_domain` | `Student.institute`, `Employee.institute`, certificate/ID-card headers, `application_form_id` prefix |
| `Campus` | `name`, `code`, `institute` (nullable for legacy rows), `city`, `state` | **Campus scoping everywhere** via `User.campuses`; `emp_code` and `receipt_no` prefixes |
| `Program` | `name`, `code`, `degree_type`, `category`, `certification`, `duration_months`, `campuses` M2M | Lead routing (category → counsellor pool), email sender domain (`degree_type` → diploma vs degree), fee templates, batches |
| `Course` | `name`, `code`, `program`, `duration_months` | `Student.course`, `Enrollment.course`, optional `FeeTemplate.course` |
| `AcademicYear` | `code` ("26-27"), `full_name`, `start_date`, `end_date`, `is_current` | Almost every report filter; `promote_lead_to_student` **fails** if no row has `is_current=True` |
| `Semester` | `name`, `number` (unique) | `Enrollment.semester`, `MarksEntry.semester` |
| `Batch` | `name`, `short_name`, `program`, `campus`, `academic_year`, `mentor` (→ `Employee`), `feedback_link`, `feedback_link_enabled` | The central academic grouping — schedule, attendance, assignments, lessons, courseware, reports. Unique on (name, program, campus, academic_year) |
| `Subject` | `name`, `code` (unique), `credits` | Schedule slots, assignments, marks, tests, courseware. **Stand-alone** — there is no explicit Program↔Subject curriculum table; the link is implicit through `ScheduleSlot.batch → program` |
| `Classroom` | `name`, `code`, `campus`, `capacity` | `ScheduleSlot.classroom`; conflict detection |
| `TimeSlot` | `label`, `start_time`, `end_time`, `academic_year`, `sort_order` | `ScheduleSlot.time_slot`; the weekly grid publisher |
| `FeeTemplate` | `name`, `academic_year`, `campus`, `program`, optional `course`, `application_fee`, `course_fee`, `other_fee`, `total_fee` | `enrollment_balance()`, the lead fee-link amount |
| `State` / `City` | `name`, `code`, `is_union_territory`; City→State FK | Student and employee addresses |
| `Degree` | `code`, `name` | Reference list (UG/PG/Diploma/Certificate) |
| `LeadSource` | `name`, `slug` (auto), `sort_order` | `Lead.source` |

### Notes that matter

- **`FeeTemplate.total_fee` is stored, not computed.** It is deliberately not
  `application_fee + course_fee + other_fee` so admins can override after
  discounts. Do not "fix" this.
- **`Batch.mentor`** is what makes a person a batch mentor. It drives the
  student-leave mentor console, batch-mentor reports and 0-Hour reports.
- **`Program.category`** decides which `CounsellorPool` a new lead is routed
  to. A program in a category with no pool gets no auto-assignment.
- **`Program.degree_type`** is free text matched by substring
  (`"diploma" in degree_type.lower()`) in
  `apps/notifications/sender.py::is_diploma`. Typos silently change which
  domain fee/admission emails are sent from.

## 3.4 Access control — an important asymmetry

`apps/master/views.py` uses two patterns:

**Gated CRUD** — `perm_base = "master.<resource>"`, so reads need `.view`:

`Institute`, `Campus`, `Program`, `LeadSource`, `FeeTemplate`.

**Open reads, gated writes** — these are `_writes(...)` resources in the
catalogue, with **no `.view` key at all**. Any authenticated user can list them
because they populate dropdowns across the app:

`State`, `City`, `AcademicYear`, `Degree`, `Course`, `Semester`, `Batch`,
`Subject`, `Classroom`, `TimeSlot`.

This is a design decision, documented in the `_writes()` docstring: a `.view`
checkbox that changes nothing is worse than no checkbox. If you tighten this,
you will break most dropdowns for non-admin users.

## 3.5 Delete semantics

`_MasterDetailMixin.delete` **does not delete** — it sets `is_active = False`.
The permission label reads "Deactivate" accordingly. Lists return everything by
default; pass `?active=1` to filter. Combined with `on_delete=PROTECT` on the
consuming FKs, master rows are effectively never removed.

## 3.6 Endpoints

Uniform pattern for every resource:

```
GET|POST   /api/master/<resource>/
GET|PATCH|DELETE /api/master/<resource>/<id>/
```

with these paths: `institutes`, `states` (note: **`POST /states/create/`**, not
`POST /states/` — `StateListView` is read-only and `StateManageView` handles
creation), `cities`, `campuses`, `programs`, `lead-sources`, `academic-years`,
`degrees`, `courses`, `semesters`, `batches`, `fee-templates`, `subjects`,
`classrooms`, `time-slots`.

One extra endpoint:

| Path | Purpose |
|---|---|
| `GET /api/master/campuses/<id>/programs/` | Programs offered at that campus. Any authenticated user. Used by the Add Lead form to filter the program dropdown after a campus is chosen |

## 3.7 Seeding

```bash
python manage.py seed_states           # then
python manage.py seed_indian_cities    # depends on states
python manage.py seed_institutes
python manage.py seed_degrees
python manage.py seed_programs         # depends on institutes/campuses
python manage.py seed_lead_sources
```

Campuses, academic years, batches, subjects, classrooms, time slots and fee
templates are entered through the UI — there is no seeder for them.

## 3.8 Change impact

Because nearly every FK into `master` is `PROTECT`, deleting a row through the
shell or admin will raise `ProtectedError` rather than cascade. That is the
intended safety net.

| If you change… | Watch out for |
|---|---|
| `Campus.code` | Historic `emp_code` (`{CAMPUS}-{YYYY}-{seq}`) and `receipt_no` (`RCP-{CAMPUS}-{YYYY}-{seq}`) already contain the old code. Sequence generators scan by prefix, so a code change restarts numbering |
| `Institute.code` | Same for `application_form_id` (`{INSTITUTE}-{YYYY}-{seq}`), and it is the key into `settings.INSTITUTE_PAYMENT_DETAILS` / `FEE_LINK_URLS`. A mismatch makes "Send fee link" raise |
| `AcademicYear.is_current` | Only one row should carry it. `promote_lead_to_student` picks the first `is_current=True` and errors if none exists |
| `Program.category` | Re-routes new leads to a different counsellor pool |
| `Program.degree_type` | Changes the From domain on fee/admission emails |
| Adding a `Batch` | Nothing else needed — schedule, attendance, assignments and reports all key off it |
| Deactivating a `TimeSlot` | Existing `ScheduleSlot` rows keep working (FK is PROTECT); only new scheduling is affected |
