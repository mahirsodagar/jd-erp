# JD Institute ERP — System Documentation

This is the maintainer's manual for the JD Institute ERP. It is written for a
developer or technical team member who has **not** worked on the codebase
before and needs to run, operate, extend and hand over the system without
further assistance.

---

## 1. What the system is

A single-tenant ERP for JD Institute (JD Institute of Fashion Technology /
JD School of Design). It covers the whole student lifecycle plus the staff-side
operations that surround it:

```
Marketing lead  →  Counsellor follow-up  →  Application fee  →  Application form
      →  Student record  →  Enrolment in a batch  →  Fee schedule + receipts
      →  Timetable, attendance, assignments, marks, tests
      →  Certificates / graduation / alumni
```

Around that spine sit HR (employees, leaves, exit/relieving), an audit &
compliance reporting suite, a student/parent portal, and a multi-channel
notification layer (email / SMS / WhatsApp).

## 2. The two deliverables

| Repo | Stack | Role |
|---|---|---|
| `jd-erp/` | Python 3.13, Django 5.2, Django REST Framework, SimpleJWT | The API and the entire domain model. No server-rendered UI apart from Django admin. |
| `jd-erp-web/` | React 19, TypeScript, Vite, TanStack Query, Zustand, Tailwind 4 | Two SPAs served from one bundle: the **staff CRM/ERP** and the **student & parent portal**. |

They are deployed independently: the API on a VPS behind nginx + gunicorn, the
frontend as a static bundle (Netlify at time of writing). The only contract
between them is the JSON REST API under `/api/`.

## 3. How to read this documentation

Start here, then read in order — each chapter assumes the ones before it.

| # | Document | Covers |
|---|---|---|
| 1 | [Getting started & operations](01-getting-started.md) | Local setup, environment variables, seed commands, deployment, day-2 runbook |
| 2 | [Platform foundations](02-platform-foundations.md) | `accounts`, `roles`, `audit`, `common` — auth, JWT, the permission system, throttling, file-upload validation |
| 3 | [Master data](03-master-data.md) | `master` — institutes, campuses, programs, courses, batches, subjects, fee templates and every other reference list |
| 4 | [Leads / CRM](04-leads-crm.md) | `leads` — intake, dedup, counsellor pools, follow-ups, application & fee links, entrance exams, reports |
| 5 | [Admissions](05-admissions.md) | `admissions` — students, the public application form, enrolments, promotion, portal provisioning |
| 6 | [Fees](06-fees.md) | `fees` — installments, receipts, concessions, other fees, balances, PDFs, reminders |
| 7 | [Academics](07-academics.md) | `academics`, `courseware` — timetable, attendance, assignments, marks, tests, lessons, certificates, alumni, batch & closing reports |
| 8 | [HR](08-hr.md) | `employees`, `leaves`, `relieving`, `tasks` |
| 9 | [Audit & reports](09-audit-reports.md) | `audit_reports` — daily logs, periodic reports, feedback, appraisals, flags & stars, the dynamic form builder, dashboards |
| 10 | [Student & parent portal](10-student-portal.md) | `portal`, `student_leaves`, `student_documents`, `appointments` |
| 11 | [Notifications](11-notifications.md) | `notifications` — the queue, template registry, and the MSG91 / BulkSMS / XIRCLS / SMTP transports |
| 12 | [Frontend](12-frontend.md) | `jd-erp-web` — routing, auth store, API layer, permission gating, page inventory |
| 13 | [Cross-module map & change impact](13-cross-module-map.md) | Dependency graph, data flow, "if I change X, what breaks" |

> **Looking for the end-user manual?** Non-technical instructions for the
> people who *use* the software — counsellors, admissions, accounts, faculty,
> HR, auditors, students and parents — are in
> [`docs/user-guide/`](../user-guide/README.md). This set is for developers.

Two older, feature-specific documents also exist and remain accurate:
[`scope_employee.md`](scope_employee.md) and
[`scope_leave.md`](scope_leave.md). The frontend repo carries
`BATCH_REPORT_DOCUMENTATION.md`, `CLOSING_REPORT_DOCUMENTATION.md` and
`LEAVE_MODULE_DOCUMENTATION.md` for those three screens.
Deployment specifics live in [`../../deploy-VPS.md`](../../deploy-VPS.md).

---

## 4. Architecture at a glance

```
                      ┌──────────────────────────────────────────┐
   Browser (staff) ───▶│  jd-erp-web  (React SPA, hash router)    │
   Browser (student)──▶│  /#/...  staff  ·  /#/portal/...  portal │
                      └───────────────┬──────────────────────────┘
                                      │ JSON + JWT Bearer
                                      ▼
                     ┌────────────────────────────────────────┐
                     │  Django REST API   (config/urls.py)    │
                     │  ┌──────────────────────────────────┐  │
   Public, tokenised │  │ /api/public/application/<uuid>/  │  │
   (no auth) ───────▶│  │ /api/public/exam/<uuid>/         │  │
                     │  └──────────────────────────────────┘  │
                     │  /api/<module>/…  (21 Django apps)     │
                     └───────┬───────────────┬────────────────┘
                             │               │
                    ┌────────▼──────┐  ┌─────▼─────────────────────┐
                    │ DB            │  │ apps.notifications        │
                    │ SQLite (dev)  │  │  queue → transports       │
                    │ MySQL (prod)  │  │  MSG91 · BulkSMS · XIRCLS │
                    └───────────────┘  │  · SMTP (per-domain)      │
                                       └───────────────────────────┘
```

**Key architectural decisions you need to know before changing anything:**

1. **Everything is an `APIView`, not a `ViewSet`.** URLs are declared
   explicitly per app in `apps/<app>/urls.py`. Pagination is opt-in through
   `apps.common.pagination.PaginatedAPIViewMixin`, not automatic.
2. **Permissions are a custom key catalogue**, not Django's
   `auth.Permission`. See [chapter 2](02-platform-foundations.md). The
   catalogue in `apps/roles/seed.py` is the single source of truth and
   re-seeding *deletes* keys that are no longer in it.
3. **Business rules live in `services.py` / `services/` packages**, not in
   views or serializers, so the same rule can be reached from an API view, a
   management command and a signal.
4. **All outbound messaging goes through `queue_notification(...)`.** Nothing
   calls a provider SDK directly except the transport modules themselves. Every
   attempt leaves a `NotificationDispatchLog` row.
5. **Campus scoping is pervasive.** Most list endpoints filter by
   `request.user.campuses` unless the caller holds the matching
   `*.view_all` / `*.view_all_campuses` key.
6. **Two account types share one `User` model.** Staff, students and parents
   are all `accounts.User` rows; a student is a `User` with a `Student` row
   pointing at it via `user_account` (parents via `parent_user_account`). The
   portal endpoints resolve this through `apps/portal/helpers.py`.

## 5. Django app inventory

| App | Mounted at | Purpose |
|---|---|---|
| `accounts` | `/api/auth/…`, `/api/users/…` | Users, JWT login/refresh/logout, password flows |
| `roles` | `/api/roles/`, `/api/permissions/` | Permission catalogue + roles |
| `audit` | `/api/audit/` | Auth event log + django-auditlog data-change log |
| `master` | `/api/master/` | All reference/master data |
| `leads` | `/api/leads/` | CRM: leads, pools, follow-ups, entrance exams, reports |
| `admissions` | `/api/admissions/` | Students, documents, enrolments, promotion |
| `fees` | `/api/fees/` | Installments, receipts, concessions, balances |
| `academics` | `/api/academics/` | Timetable, attendance, assignments, marks, tests, lessons, certificates, alumni |
| `courseware` | `/api/courseware/` | Teaching material published to batches |
| `employees` | `/api/employees/` | Employee master, departments, designations, ID cards |
| `leaves` | `/api/leaves/` | Employee leave + comp-off |
| `relieving` | `/api/hr/relieving/` | Exit workflow + relieving/experience letters |
| `tasks` | `/api/tasks/` | Lightweight task assignment |
| `audit_reports` | `/api/audit-reports/` | Daily/periodic reports, feedback, appraisals, compliance, form builder, dashboards |
| `student_leaves` | `/api/student-leaves/` | Student leave applications (staff side) |
| `student_documents` | `/api/student-documents/` | Student document requests (staff side) |
| `appointments` | `/api/appointments/` | Student appointment requests (staff side) |
| `portal` | `/api/portal/` | The student & parent portal read/write surface |
| `notifications` | *not mounted* | Queue + transports. Library only — no HTTP API |
| `common` | `/api/common/` | Shared pagination, throttles, file validation |

## 6. Conventions used throughout the codebase

- **Permission key format** — `<module>.<resource>.<action>`, e.g.
  `fees.receipt.cancel`. Views declare either `required_perm = "<key>"` or
  `perm_base = "<module>.<resource>"` (which resolves the action from the HTTP
  method).
- **Soft delete** — only `employees.Employee` uses it (`is_deleted` +
  `EmployeeManager`; `all_objects` bypasses the filter). Everything else uses
  status fields or hard deletes.
- **Status snapshots** — approval workflows snapshot the approver at submission
  time (`LeaveApplication.manager_email`,
  `RelievingApproval.approver`) so later org-chart changes never reroute a
  pending request.
- **Money** — always `DecimalField`, serialized as strings.
- **Timezone** — `TIME_ZONE = "UTC"`, `USE_TZ = True`. Dates entered by staff
  are plain `DateField`s and are not converted.
- **Templates keys** — notification triggers are dotted keys ending in
  `.email` / `.sms` / `.wa`, e.g. `fees.receipt.email`. The suffix determines
  the channel when no `NotificationTemplate` row exists.

## 7. Where to start when you pick this up

1. Get it running locally — [chapter 1](01-getting-started.md).
2. Read [chapter 2](02-platform-foundations.md) end to end. The permission
   system touches every other module and is the most common source of
   "why can't this user see the page".
3. Read [chapter 13](13-cross-module-map.md) before your first change, to see
   what depends on what.
4. Then read only the chapter for the module you are working on.
