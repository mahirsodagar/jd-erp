# Leave Module — Scope

> Django REST app: `leaves` (with `LeaveType`, `LeaveAllocation`, `LeaveApplication`, `CompOffApplication`, `Holiday`).
> Replaces PHP `hr/leave_apply.php`, `hr/leave_balances.php`, `hr/leave_report.php`, `hr/assign_leaves.php`, `hr/compoff_apply.php`, `hr/holiday_calender.php`, and the faculty variant `academics/leave_apply.php` — folding both into one module.
> Stack: **DRF + SimpleJWT** APIs; audit via `django-auditlog`; emails via Celery + `django-anymail`.

---

## 1. Goals

A. **Allocate** leaves (HR, bulk per session/academic-year, per leave-type).
B. **Apply** for leave (employee), with overlap detection, balance check, and manager email.
C. **Approve / reject** leaves (manager) with remarks; status transitions tracked.
D. **Apply for comp-off** (employee earns days from weekend/holiday work) → manager approves → adds to comp-off balance.
E. **View balances** (granted / availed / pending / balance) per leave type per session.
F. **Run reports** (HR) with date/department/campus/status filters.
G. **Maintain holiday calendar** per campus, used by leave-day calculation.

---

## 2. Leave Type Catalog

Seeded fixture matches today's `leave_types` table; admin can add more.

| id | code | name | category | accrual | half-day allowed | notes |
|---|---|---|---|---|---|---|
| 1 | `CASUAL` | Casual Leave | LEAVE | allocated | yes | most common |
| 2 | `COMP_OFF` | Comp-Off | LEAVE | accrual (from comp-off apps) | yes | balance computed from approved CompOffApplication, not from `LeaveAllocation` |
| 3 | `VISIT` | Visits | ON_DUTY | unlimited | yes | doesn't deplete balance |
| 4 | `EXAM_DUTY` | Examination Duty | ON_DUTY | unlimited | yes | |
| 5 | `OTHERS` | Others | ON_DUTY | unlimited | yes | |
| 6 | `SATURDAY_OFF` | Saturday Off | LEAVE | allocated | no | special weekend |
| 7 | `PERMISSION` | Permission (short) | LEAVE | allocated | session-only | only sessions 3 or 4 (1.5h slots) |

**Categories:**
- `LEAVE` — depletes balance.
- `ON_DUTY` — recorded, doesn't deplete balance, still routes for manager visibility.

**Sessions / half-day codes:**
| code | meaning | applies to |
|---|---|---|
| 1 | First half (morning) | types 1, 6 |
| 2 | Full day | types 1, 6 |
| 3 | Permission slot 1 (9:30 – 11:00) | type 7 |
| 4 | Permission slot 2 (16:00 – 17:30) | type 7 |

---

## 3. Data Model

### 3.1 `LeaveType`
| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `code` | Char(20), unique | enum-like (`CASUAL`, `COMP_OFF`, …) |
| `name` | Char(60) | |
| `category` | Char(10) | `LEAVE` / `ON_DUTY` |
| `half_day_allowed` | Bool | |
| `is_active` | Bool | |

### 3.2 `Session` *(a.k.a. leave-allocation period)*
Today the PHP just stores a string `session_id` like `"22"`. We make it a real entity.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `code` | Char(10), unique | e.g. `2024-25` |
| `start_date` | Date | |
| `end_date` | Date | |
| `is_current` | Bool | exactly one row per campus may be current; enforced in clean() |

### 3.3 `LeaveAllocation`  *(legacy `emp_leave_master`)*
Yearly grant per employee, per leave type, per session.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `employee` | FK → `Employee` | |
| `session` | FK → `Session` | |
| `leave_type` | FK → `LeaveType` | only `category=LEAVE` types are allocatable |
| `count` | Decimal(5,1) | days, allows `0.5` |
| `start_date` | Date | session window for this grant |
| `end_date` | Date | |
| `created_by` | FK → User (SET_NULL) | |
| `created_on` | DateTime | |

**Unique:** `(employee, session, leave_type, start_date, end_date)` — prevents double-grants.
**Indexes:** `(employee, session)`, `(leave_type, start_date)`.

### 3.4 `LeaveApplication`  *(legacy `emp_leaves_apply`)*

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `employee` | FK → `Employee` | |
| `leave_type` | FK → `LeaveType` | |
| `from_date` | Date | |
| `from_session` | SmallInt | one of 1/2/3/4 (see §2) |
| `to_date` | Date | `>= from_date` |
| `count` | Decimal(5,1) | server-computed, not trusted from client |
| `reason` | Text | |
| `manager_email` | Email | snapshot at apply-time (so changes to RM later don't reroute) |
| `cc_emails` | Char(255) | comma-separated; auto-prefixed with `leave@jdinstitute.edu.in` for HR-side requests |
| `status` | SmallInt | `1`=Pending, `2`=Approved, `3`=Rejected, `4`=Cancelled, `5`=Withdrawn |
| `approver_remarks` | Text | filled on approve/reject |
| `approved_by` | FK → Employee (SET_NULL) | the actual approver (may differ from `manager_email`) |
| `applied_on` | DateTime | `auto_now_add` |
| `decided_on` | DateTime | set when status leaves Pending |

**Indexes:** `(employee, status)`, `(from_date, to_date)`, `(manager_email)`.
**Constraints:** `to_date >= from_date`; `count > 0` for `LEAVE` category, `>= 0` for `ON_DUTY`.

### 3.5 `CompOffApplication`  *(legacy `emp_compoff_apply`)*

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `employee` | FK → `Employee` | |
| `worked_date` | Date | the weekend/holiday actually worked |
| `worked_session_1` | SmallInt | `0` not worked, `1` worked |
| `worked_session_2` | SmallInt | same |
| `count` | Decimal(3,1) | derived: `worked_session_1 + worked_session_2 = 2 → 1.0`; `1 → 0.5`; else invalid |
| `reason` | Text | |
| `status` | SmallInt | `1` Pending, `2` Approved, `3` Rejected |
| `approver` | FK → Employee (SET_NULL) | |
| `approver_remarks` | Text | |
| `applied_on` | DateTime | |
| `decided_on` | DateTime | |

**The comp-off balance is derived**: `sum(approved CompOffApplication.count) − sum(approved LeaveApplication.count where leave_type=COMP_OFF)`.

### 3.6 `Holiday`  *(legacy `holiday_calender_master`)*

| Field | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `date` | Date | |
| `name` | Char(120) | |
| `campus` | FK → `Campus` (nullable) | null = applies to all campuses |
| `is_optional` | Bool | optional / restricted holiday flag (new) |

**Unique:** `(date, campus)`.

---

## 4. REST API

Base: `/api/v1/leaves/`. JWT-required.

### 4.1 Leave Types
- `GET /api/v1/leaves/types/` — list (read-only for non-admins).
- `POST /api/v1/leaves/types/` — admin only.

### 4.2 Sessions
- `GET /api/v1/leaves/sessions/` — list, with `?is_current=1`.
- `POST /api/v1/leaves/sessions/` — HR/Admin.

### 4.3 Allocations  (`/allocations/`)
- `GET /` — list, filters: `employee`, `session`, `leave_type`, `campus`, `department`. Multi-campus scoped.
- `POST /` — single allocation. Permission: `leaves.add_allocation` (HR).
- `POST /bulk/` — **bulk allocate** to many employees:
  ```json
  {
    "session_id": "uuid",
    "leave_type_id": "uuid",
    "count": 12,
    "start_date": "2024-04-01",
    "end_date": "2025-03-31",
    "employee_ids": ["uuid", "uuid", ...],
    "skip_existing": true
  }
  ```
  Behaviour: per employee — if a row already exists for `(employee, session, leave_type, start_date, end_date)` → skip and report; else create. Wrapped in a transaction. Response: `{created: [...ids], skipped: [...ids]}`.
- `DELETE /{id}/` — HR only; allowed only if the allocation has not been consumed (no approved leave applications against it).

### 4.4 Leave Applications  (`/applications/`)
- `GET /` — list. Self by default; `?scope=team` for managers (returns `WHERE manager_email = me OR approved_by = me`); `?scope=all` requires `leaves.view_all`.
- `GET /{id}/` — detail.
- `POST /` — apply. See §5 for validation.
- `PATCH /{id}/withdraw/` — applicant only, while `status=Pending`. Sets `Withdrawn`.
- `PATCH /{id}/cancel/` — applicant, after approval but before `from_date`. Sets `Cancelled`. Restores balance.
- `PATCH /{id}/decision/` — manager: `{"status": 2|3, "remarks": "..."}`. Permission: caller's email matches `manager_email` OR has `leaves.approve_any`.
- `GET /balances/` — current employee's balance per leave type, optionally `?employee_id=` for HR. See §6.

### 4.5 Comp-Off  (`/comp-off/`)
- `GET /` — list (self / team / all).
- `POST /` — apply.
- `PATCH /{id}/decision/` — manager.
- `GET /balance/` — `{available, earned, used}` for current employee.

### 4.6 Holidays  (`/holidays/`)
- `GET /` — list. Filters: `year`, `month`, `campus`. Open to all authenticated users.
- `POST /` / `PATCH /{id}/` / `DELETE /{id}/` — HR only.

### 4.7 Reports  (`/reports/`)
- `GET /summary/` — date-range required. Filters: `campus`, `department`, `leave_type`, `status`. Returns rows for export.
- `GET /summary.csv` & `/summary.pdf` — download.

---

## 5. Apply-for-Leave Flow

### 5.1 Form / payload
```json
{
  "leave_type_id": "uuid",
  "from_date": "2024-09-12",
  "to_date":   "2024-09-13",
  "from_session": 2,
  "reason": "family function",
  "manager_email": "rm@jdinstitute.edu.in",   // optional; defaults to RM-1 of employee
  "cc_emails": "ops@…"                         // optional
}
```

### 5.2 Server-side count derivation
- If `from_date == to_date`:
  - `from_session in (1, 3, 4)` → `count = 0.5`
  - `from_session == 2` → `count = 1.0`
- Else: `count = (to_date − from_date).days + 1` (calendar days).
- **Improvement over PHP**: a feature flag `LEAVES_EXCLUDE_HOLIDAYS_AND_WEEKENDS` (default `True`) makes `count` skip Sundays + holidays for the employee's campus. Today's PHP counts all days equally — keep the PHP behaviour available for parity if needed.

### 5.3 Validation
1. `leave_type` exists and is allowed for the employee's role (faculty vs HR).
2. `from_session` legal for `leave_type` (e.g. type 7 only allows 3/4).
3. `to_date >= from_date`.
4. **No overlap**: reject if any non-`Cancelled`/`Rejected`/`Withdrawn` application of the same employee overlaps `[from_date, to_date]`.
5. **Balance check** (only for `category=LEAVE`):
   - For `COMP_OFF`: derived comp-off balance ≥ requested count.
   - Otherwise: sum(active allocations covering `from_date`) − sum(approved/pending applications) ≥ requested count.
   - **Improvement over PHP**: PHP skips this check; we enforce it but allow `force=true` for HR with `leaves.override_balance`.
6. `from_date >= today` (no back-dating); HR may back-date with `leaves.backdate_apply`.
7. `manager_email` is a valid email; if absent, defaults to the employee's `reporting_manager_1.email_primary`.

### 5.4 Side effects
- Status set to `Pending`. `applied_on=now()`.
- Celery task: send email via MSG91 template `employee_leave_application` to `manager_email` (TO) + `cc_emails` + `leave@jdinstitute.edu.in` (CC). Variables: employee name + code, type, dates, count, session, reason, link to approve.
- Audit entry via `django-auditlog`.

### 5.5 Approve / reject
- Manager hits `PATCH /applications/{id}/decision/` with `status=2 or 3` and `remarks`.
- Server sets `approved_by = caller's Employee`, `decided_on = now()`.
- For approval: deduct the consumed days from the employee's effective balance (computed, not stored).
- Email applicant with the decision (Celery, anymail).
- For rejection: balance untouched.

### 5.6 Cancel / withdraw
- `Withdraw` (Pending only): just flips status; no balance impact.
- `Cancel` (Approved, before `from_date`): flips status; balance recompute restores days.
- Both require an audit `reason` (≥ 5 chars).

---

## 6. Balances

For an employee + session:

```text
LEAVE category, type T:
  granted   = sum(LeaveAllocation.count where leave_type=T, session=S)
  pending   = sum(LeaveApplication.count where leave_type=T, status=Pending, applied within S window)
  availed   = sum(LeaveApplication.count where leave_type=T, status=Approved, applied within S window)
  balance   = granted − pending − availed

COMP_OFF (special):
  earned  = sum(CompOffApplication.count where status=Approved)
  used    = sum(LeaveApplication.count where leave_type=COMP_OFF, status in (Pending, Approved))
  balance = earned − used
```

API: `GET /applications/balances/?session_id=…` returns one entry per leave type for the active employee:
```json
[
  {"leave_type": "Casual", "granted": 12, "pending": 1, "availed": 4, "balance": 7},
  {"leave_type": "Comp-Off", "earned": 3, "used": 1, "balance": 2}
]
```

---

## 7. Permissions Matrix

| Action | Required perm | Notes |
|---|---|---|
| Apply for self | authenticated | own employee record |
| Withdraw / cancel own | authenticated | own + status rules |
| Approve / reject (assigned manager) | implicit (email match OR `approved_by`) | enforced by `LeaveAccessPolicy` |
| Approve any | `leaves.approve_any` | HR override |
| Bulk allocate | `leaves.add_allocation` | HR |
| Delete allocation | `leaves.delete_allocation` | HR + only if unconsumed |
| Override balance / back-date | `leaves.override_balance`, `leaves.backdate_apply` | HR + Admin |
| Manage holidays | `leaves.change_holiday` | HR |
| View reports (campus) | `leaves.view_report` | HR within own campuses |
| View reports (all) | `leaves.view_report_all` | Director |

---

## 8. Notifications

| Event | Channel | Template | To / CC |
|---|---|---|---|
| Leave applied | Email (MSG91) | `employee_leave_application` | manager_email; CC cc_emails + leave@… |
| Leave approved | Email (MSG91) | `employee_leave_decision` | applicant; CC manager |
| Leave rejected | Email (MSG91) | `employee_leave_decision` | applicant; CC manager |
| Leave cancelled by employee | Email | `employee_leave_cancelled` | manager |
| Comp-off applied | Email | `employee_compoff_application` | manager |
| Comp-off decision | Email | `employee_compoff_decision` | applicant |

All sent through Celery; failures retried with exponential backoff; logged in `notifications.EmailDispatchLog`.

---

## 9. Audit & Reporting

- `LeaveAllocation`, `LeaveApplication`, `CompOffApplication`, `Holiday` registered with `auditlog` — every CUD captures field-level diffs and the actor.
- `RequestLog` middleware captures API access for the report endpoints.
- `leaves/reports/summary` endpoint hits a denormalized read-side query (joined with `Employee`, `Department`, `LeaveType`) and supports CSV / PDF export (DRF renderers).

---

## 10. Improvements over the PHP version

1. **Balance check enforced** at apply time — PHP omits it.
2. **Holiday + weekend exclusion** in day count (configurable feature flag).
3. **Snapshot manager email** stored on the application — RM changes don't reroute already-pending leaves.
4. **Cancel after approval** + auto-restored balance — PHP only allows pending-leave delete.
5. **Real Session entity** — PHP stores `session_id` as a free-text varchar; no validity dates.
6. **`Withdrawn` and `Cancelled` are distinct from `Rejected`** — PHP collapses them.
7. **Consistent comp-off balance formula** — PHP computes inconsistently between `leave_balances.php` and `compoff_apply.php`.
8. **`leave_type=COMP_OFF` deducts only from comp-off pool**, not from any allocation.
9. **Permission-gated overrides** for HR back-dating / balance override (today the SQL silently allows it).
10. **Audit history** built-in via `django-auditlog`; no separate `logs` table writes scattered across handlers.
11. **Reports as proper API endpoints** with CSV/PDF renderers — not DataTables HTML scraping.
12. **One module covers HR + faculty leave**; today the duplicate `academics/leave_apply.php` is a near-clone with subtle drift.

---

## 11. Out of Scope (this module)

- Salary impact / loss of pay calculation — payroll module (not in PHP).
- Calendar feed (ICS) for approved leaves — nice-to-have, defer.
- Slack / Teams notifications — defer.
- Mobile push.

---

## 12. Suggested File Layout (the `leaves` app)

```
leaves/
├── apps.py
├── admin.py
├── models.py             # LeaveType, Session, LeaveAllocation, LeaveApplication, CompOffApplication, Holiday
├── serializers.py
├── permissions.py        # LeaveAccessPolicy
├── filters.py
├── viewsets.py
├── services/
│   ├── balance.py        # compute_balance(employee, leave_type, session)
│   ├── day_count.py      # working-day count w/ holiday + weekend exclusion
│   └── notifications.py  # email dispatch wrappers
├── tasks.py              # Celery: send_leave_email, send_decision_email
├── urls.py
├── tests/
│   ├── test_models.py
│   ├── test_balance.py
│   ├── test_apply.py
│   ├── test_overlap.py
│   ├── test_decision.py
│   └── test_compoff.py
└── migrations/
```
