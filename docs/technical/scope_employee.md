# Employee Module — Scope

> Django REST app: `employees` (with `Employee`, `Department`, `Designation`).
> Replaces PHP `hr/employees.php` (2727 lines) + `hr/hrget.php` + `hr/hrsave.php` + `hr/department.php` + `hr/designation.php`.
> Stack: **DRF + SimpleJWT** APIs consumed by a separate frontend (CORS-allowed); audit via `django-auditlog`; brute-force protection on auth via `django-axes`.

---

## 1. Goals

A. **List** employees with filtering, search, pagination, multi-campus scoping.
B. **Add** a new employee (HR-driven), with photo upload, auto QR generation, and optional portal-user creation.
C. **Update** an existing employee with field-level audit trail.
D. **Activate / deactivate** (soft status), and full **relieving** flow (out of scope here — handled by a separate `Relieving` module per the master scope).
E. **Generate ID card / QR** on demand.

Out of scope for this doc: leave allocation, comp-off, holiday calendar, relieving workflow, exp-letter PDF.

---

## 2. Data Model

### 2.1 `Employee`

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | UUID PK | — | UUID4 (replaces legacy `pk_id` int) |
| `emp_code` | Char(20), unique | yes | Legacy `emp_id`. **Improvement:** auto-generated as `{CAMPUS}-{YYYY}-{seq}` if blank, manual override allowed. |
| `first_name` | Char(60) | yes | |
| `middle_name` | Char(60) | no | |
| `family_name` | Char(60) | no | |
| `dob` | Date | yes | Must be in the past, age ≥ 18. |
| `nationality` | Char(40) | yes | Choices: `INDIAN`, `OTHERS`. |
| `blood_group` | Char(5) | yes | Choices: `A+`, `A-`, `B+`, `B-`, `O+`, `O-`, `AB+`, `AB-`. |
| `gender` | Char(1) | yes | Choices: `M`, `F`, `O`. |
| `qualification` | Char(120) | no | |
| `employment_type` | SmallInt | yes | `1` = Full-time, `2` = Part-time. |
| `date_of_appointment` | Date | yes | |
| `date_of_joining` | Date | yes | Must be ≥ `date_of_appointment`. |
| `designation` | FK → `Designation` | yes | |
| `department` | FK → `Department` | yes | |
| `campus` | FK → `masters.Campus` | yes | Drives multi-tenant scoping. |
| `institute` | FK → `masters.Institute` | yes | (a.k.a. legacy `entity`) |
| `reporting_manager_1` | FK → self (PROTECT) | yes | L1 manager. |
| `reporting_manager_2` | FK → self (SET_NULL) | no | |
| `reporting_manager_3` | FK → self (SET_NULL) | no | |
| `reporting_manager_4` | FK → self (SET_NULL) | no | |
| `current_address` | Text | yes | |
| `current_city` | FK → `masters.City` | yes | |
| `current_state` | FK → `masters.State` | yes | |
| `permanent_address` | Text | yes | Form has "same as current" toggle. |
| `permanent_city` | FK → `masters.City` | yes | |
| `permanent_state` | FK → `masters.State` | yes | |
| `mobile_primary` | Char(15) | yes | E.164 / IN format validator. |
| `mobile_alternate` | Char(15) | no | |
| `email_primary` | Email, unique | yes | |
| `email_alternate` | Email | no | |
| `photo` | ImageField | no | Storage: `employees/{id}/photo.jpg`, max 2 MB, JPEG/PNG. |
| `qr_code` | ImageField (read-only) | auto | Generated post-save: PNG of the employee `id`. Re-generated on update. |
| `status` | SmallInt | yes | `0` = Active, `1` = Inactive (relieved). Soft state. |
| `is_deleted` | Bool | yes | Soft-delete flag (default False). |
| `created_by` | FK → `User` (SET_NULL) | yes | Auto-set from request. |
| `created_on` | DateTime | yes | `auto_now_add`. |
| `updated_by` | FK → `User` (SET_NULL) | no | Auto-set on save. |
| `updated_on` | DateTime | yes | `auto_now`. |

**Indexes:** `emp_code`, `email_primary`, `(campus, status)`, `(department, status)`.

**Auditing:** registered with `auditlog.registry.register(Employee)` — every CUD captures field-level diffs.

### 2.2 `Department` & `Designation`
Both: `id` UUID, `name` Char(120) unique, `is_active` Bool, timestamps. Plain CRUD.

### 2.3 Relation to `User`
- `EmployeeProfile` is **not** the auth model. Authentication uses `accounts.User`.
- A nullable `OneToOneField(User, related_name='employee')` lives on `Employee.user_account`.
- Portal access is a separate action: `POST /api/v1/employees/{id}/portal-account/` — creates a `User`, attaches it to the employee, sends initial credentials by email.

---

## 3. REST API

Base path: `/api/v1/employees/`. All endpoints require `Authorization: Bearer <jwt>` (SimpleJWT).

### 3.1 List — `GET /api/v1/employees/`

| Concern | Behaviour |
|---|---|
| Pagination | `page` + `page_size` (default 25, max 100). DRF `PageNumberPagination`. |
| Sorting | `?ordering=` over: `emp_code`, `first_name`, `date_of_joining`, `created_on` (asc/desc with `-`). |
| Search | `?search=` over: `emp_code`, `first_name`, `family_name`, `email_primary`, `mobile_primary`. |
| Filters | `campus`, `department`, `designation`, `institute`, `employment_type`, `status`, `gender`, `nationality`, `created_after`, `created_before`. |
| Tenancy | Auto-filtered by `request.user.campuses` unless user has `employees.view_all_campuses` perm. |
| Soft-deleted | Excluded by default; `?include_deleted=1` requires `employees.manage_deleted` perm. |
| Response shape | List serializer = compact (no addresses, no manager chain) — keeps payload small for tables. |

**Compact list item:**
```json
{
  "id": "uuid",
  "emp_code": "BLR-2026-0142",
  "full_name": "Asha R. Kumar",
  "designation": "Faculty",
  "department": "Fashion Design",
  "campus": "Bangalore",
  "email_primary": "asha@…",
  "mobile_primary": "+91…",
  "photo_url": "https://…/photo.jpg",
  "status": 0,
  "date_of_joining": "2024-08-12"
}
```

### 3.2 Retrieve — `GET /api/v1/employees/{id}/`
Returns the full detail serializer (every field above + nested department/designation/campus/manager objects). 404 if not visible to caller (campus scope).

### 3.3 Create — `POST /api/v1/employees/`

Permission: `employees.add_employee` (HR / Admin roles).

**Request (`multipart/form-data` to allow photo upload, or JSON without photo):**
```json
{
  "emp_code": "",                  // optional — auto-generated if blank
  "first_name": "Asha",
  "middle_name": "R.",
  "family_name": "Kumar",
  "dob": "1992-04-11",
  "nationality": "INDIAN",
  "blood_group": "O+",
  "gender": "F",
  "qualification": "M.Des",
  "employment_type": 1,
  "date_of_appointment": "2024-08-01",
  "date_of_joining": "2024-08-12",
  "designation_id": "uuid",
  "department_id": "uuid",
  "campus_id": "uuid",
  "institute_id": "uuid",
  "reporting_manager_1_id": "uuid",
  "reporting_manager_2_id": null,
  "current_address": "…",
  "current_city_id": "uuid",
  "current_state_id": "uuid",
  "permanent_address": "…",
  "permanent_city_id": "uuid",
  "permanent_state_id": "uuid",
  "mobile_primary": "+91…",
  "email_primary": "asha@…"
}
```

**Validation:**
- All `required: yes` fields present.
- `email_primary` unique across **non-deleted** employees.
- `emp_code` unique if provided.
- `dob` in past, age ≥ 18.
- `date_of_joining ≥ date_of_appointment`.
- `reporting_manager_1` cannot be the same as the employee being created (relevant on update).
- `campus_id` must be in caller's allowed campuses unless `employees.add_in_any_campus`.
- File: photo ≤ 2 MB, JPEG/PNG only.

**Side effects on success (transactional):**
1. Insert `Employee` row.
2. Generate QR PNG → save to `employee.qr_code`.
3. If photo uploaded → resized to 300×300 thumb + stored at `employees/{id}/photo.jpg`.
4. `auditlog` entry written automatically.
5. **Optional** (flag in payload `send_welcome_email: true`): enqueue Celery task to email the employee a welcome message + set-password link (deferred to Django when user creation is requested).

**Response:** `201 Created` with the full detail serializer body.

### 3.4 Update — `PATCH /api/v1/employees/{id}/`  (and `PUT` for full replace)

Permission: `employees.change_employee` (HR / Admin); employees may `PATCH` their own record but only against an allow-list (`mobile_alternate`, `email_alternate`, `permanent_address`, photo). Enforced by serializer split.

- `emp_code` is **read-only after create**.
- All other fields editable per the matrix above.
- If `photo` re-uploaded, old file is deleted from storage.
- QR is regenerated only if `id` changes (never) — so it doesn't, unless a `regenerate_qr=true` flag is passed.
- Audit: per-field diff captured by `django-auditlog`. Custom message stored in `LogEntry.additional_data` when status flips.

### 3.5 Status toggle — `POST /api/v1/employees/{id}/deactivate/` / `POST .../activate/`
Sets `status` to 1/0. Distinct from soft-delete. Body: `{"reason": "string"}` (required for deactivate, persisted on the audit entry).

### 3.6 Soft delete — `DELETE /api/v1/employees/{id}/`
Sets `is_deleted=True`, `deleted_at=now()`. Permission: `employees.delete_employee` (Admin only).

### 3.7 ID card — `GET /api/v1/employees/{id}/id-card.pdf`
Server-rendered PDF (WeasyPrint) sized 3.366" × 2.120" (CR-80) including: institute logo, photo, name, designation, department, QR. **Improvement over PHP**: real PDF (not browser-print HTML).

### 3.8 QR code — `GET /api/v1/employees/{id}/qr.png`
Returns the stored PNG (or 404 if missing). Encodes the employee `id` (UUID).

### 3.9 Portal account — `POST /api/v1/employees/{id}/portal-account/`
Body: `{"username": "asha", "role_ids": ["uuid"], "send_credentials": true}`. Creates `User`, links via OneToOne, optionally emails credentials.

---

## 4. Permissions Matrix

| Action | Required perm | Notes |
|---|---|---|
| List (own campus) | `employees.view_employee` | All HR/Admin users |
| List (all campuses) | `employees.view_all_campuses` | Super-admin / Director |
| Retrieve | `employees.view_employee` (campus-scoped) | |
| Create | `employees.add_employee` | HR |
| Update (any) | `employees.change_employee` | HR |
| Update (own profile, allow-list) | implicit | Authenticated user, only their own record |
| Activate / deactivate | `employees.change_status` | HR Manager |
| Soft delete | `employees.delete_employee` | Admin |
| Download ID card | `employees.view_employee` | Self or HR |
| Create portal account | `accounts.add_user` + `employees.change_employee` | HR + Admin |

DRF `permission_classes` composed of `IsAuthenticated` + a custom `EmployeeAccessPolicy` that checks campus scope and self-vs-other.

---

## 5. Validation Rules (collected)

1. `emp_code`: max 20 chars, `^[A-Z0-9-]+$`, unique among non-deleted.
2. `email_primary`: standard email + unique among non-deleted.
3. `mobile_primary` / `mobile_alternate`: E.164 (`^\+?[1-9]\d{7,14}$`), normalized on save.
4. `dob`: past date, age ≥ 18 on `date_of_joining`.
5. `date_of_joining ≥ date_of_appointment`.
6. `reporting_manager_*` ≠ self.
7. `photo`: ≤ 2 MB, image/jpeg or image/png, decoded successfully.
8. `current_city.state == current_state` and same for permanent.
9. `campus` must be in caller's allowed campuses (unless override perm).
10. On status change to inactive: must accept a `reason` (≥ 5 chars).

---

## 6. Audit & Logging

- `django-auditlog` registered for `Employee`, `Department`, `Designation`. Captures who/what/when at field level.
- API access logged via DRF middleware → `RequestLog` (path, user, status, latency).
- `django-axes` watches login endpoints (5 failures → 30 min lockout per IP+username).

---

## 7. Improvements over the PHP version

(These are the "slight changes" mentioned in the master scope.)

1. **UUID PKs** — no exposed integer IDs in URLs or QR codes.
2. **Auto `emp_code` generation** with an editable override; no more manual collisions.
3. **Multi-campus scoping enforced** at queryset level — PHP today shows all campuses regardless of user.
4. **Real ID-card PDF** (WeasyPrint) instead of `window.print()` HTML.
5. **Photo stored properly** as a model `ImageField` with a thumbnail variant; PHP currently overwrites a file at `/uploads/employee_images/{pk_id}.jpg` with no validation.
6. **Reasoned deactivation** — `deactivate` requires a reason string captured in audit, instead of a silent `status` flip.
7. **Self-service profile edit** for the allow-listed fields — PHP has no employee self-edit at all.
8. **Soft delete + audit** uniformly — PHP `delete` actually removes rows.
9. **Unified user/employee model** — `EmployeeProfile` linked to Django `User` from day one (PHP keeps `users` and `emp_master` as parallel identities).
10. **Portal access is its own endpoint** rather than buried in a modal that posts to the same `hrsave.php`.

---

## 8. Out of Scope (this module)

- Leave allocation / leave application / comp-off → `leaves` app.
- Holiday calendar → `hr_calendar` app.
- Relieving workflow + experience letter PDF → `relieving` app.
- Salary structure / payroll → not built in PHP either; defer.
- Bulk import (CSV) — desirable, but slot it as a follow-up endpoint `POST /api/v1/employees/bulk-import/` once the single-record flow is stable.

---

## 9. Suggested File Layout (the `employees` app)

```
employees/
├── __init__.py
├── apps.py
├── admin.py
├── models.py            # Employee, Department, Designation
├── serializers.py       # List, Detail, Create, Update, SelfUpdate, IDCard
├── permissions.py       # EmployeeAccessPolicy
├── filters.py           # FilterSet for list endpoint
├── viewsets.py          # EmployeeViewSet, DepartmentViewSet, DesignationViewSet
├── services.py          # generate_emp_code(), generate_qr(), build_id_card_pdf()
├── tasks.py             # Celery: send_welcome_email, regenerate_qr_async
├── urls.py
├── tests/
│   ├── test_models.py
│   ├── test_api_list.py
│   ├── test_api_create.py
│   ├── test_api_update.py
│   └── test_permissions.py
└── migrations/
```
