# 2 — Platform Foundations

Apps: **`accounts`**, **`roles`**, **`audit`**, **`common`**.

These four carry no business domain of their own but every other module depends
on them. Read this chapter before any other.

---

## 2.1 `accounts` — identity and authentication

### Purpose

Owns the single `User` model used by staff, students and parents alike, plus
all authentication and password flows.

### Model — `accounts.User` (`db_table = "accounts_user"`)

Custom `AbstractBaseUser` + `PermissionsMixin`.

| Field | Notes |
|---|---|
| `username` | unique, the `USERNAME_FIELD` |
| `email` | unique |
| `full_name` | display name |
| `is_active`, `is_staff`, `is_superuser` | `is_superuser` bypasses **every** permission check in the app |
| `campuses` | M2M to `master.Campus`. **The basis of campus scoping across the whole system.** Empty = no campus scope |
| `is_available`, `unavailable_reason` | Counsellor availability. `False` makes the lead round-robin skip this user |
| `date_joined` | |

Reverse one-to-ones added by other apps:

- `user.student` → `admissions.Student` (this user *is* a student)
- `user.parent_of_student` → `admissions.Student` (this user is that student's parent)
- `user.employee` → `employees.Employee`
- `user.roles` → M2M from `roles.Role`

A user is a "student", "parent" or "employee" purely by which of these links
exists. There is no type column.

### Authentication

- **Backends** (`AUTHENTICATION_BACKENDS`, in order):
  `axes.backends.AxesStandaloneBackend` → `UsernameOrEmailBackend` →
  Django's `ModelBackend`.
- `UsernameOrEmailBackend` (`apps/accounts/backends.py`) lets the single login
  field accept **either** the username or the email, case-insensitively.
- **django-axes** locks out after `AXES_FAILURE_LIMIT` (5) failures per
  `(ip_address, username)` for `AXES_COOLOFF_MINUTES` (15). Resets on success.
  Disabled for the Django admin (`AXES_ENABLE_ADMIN = False`).

### JWT

`rest_framework_simplejwt`, configured in settings:

| Setting | Value |
|---|---|
| Access token lifetime | 15 min (`ACCESS_TOKEN_MINUTES`) |
| Refresh token lifetime | 45 min (`REFRESH_TOKEN_MINUTES`) |
| `ROTATE_REFRESH_TOKENS` | `True` |
| `BLACKLIST_AFTER_ROTATION` | `True` — old refresh tokens are blacklisted on use |
| Algorithm / signing key | HS256, signed with `SECRET_KEY` |
| Header | `Authorization: Bearer <access>` |

Effective session length is 45 minutes of inactivity; the frontend refreshes
transparently (see [chapter 12](12-frontend.md) §12.3).

### Endpoints

| Method + path | Permission | Notes |
|---|---|---|
| `POST /api/auth/login/` | open, throttled `login` (10/min per IP) | Body `{identifier, password}`. Returns `{tokens: {access, refresh}, user: {...}}`. Records an `AuthLog` row. Clears the student's plaintext temp password |
| `POST /api/auth/refresh/` | open, throttled `login` | SimpleJWT rotation |
| `POST /api/auth/logout/` | authenticated | Blacklists the supplied refresh token, logs the event |
| `GET/PATCH /api/auth/me/` | authenticated | Current user + permissions + modules |
| `POST /api/auth/change-password/` | authenticated, throttled `password_change` (5/min) | Self-service |
| `POST /api/auth/forgot-password/` | open, throttled `forgot_password` (5/hour per IP) | Emails a reset link |
| `POST /api/auth/reset-password/` | open | Consumes the uid+token from the email |
| `GET/POST /api/users/` | `accounts.user.view` / `.add` | |
| `GET/PATCH/DELETE /api/users/<id>/` | `accounts.user.*` | See the split below |
| `POST /api/users/<id>/reset-password/` | `accounts.user.reset_password` | Admin resets someone else's password |

### The `/api/auth/me/` payload

This is the contract the entire frontend is built on. `UserSerializer` returns:

```jsonc
{
  "id": 1, "username": "...", "email": "...", "full_name": "...",
  "is_active": true, "is_superuser": false,
  "campuses": [1, 2],                  // campus ids
  "is_student": false, "is_parent": false, "is_employee": true,
  "employee_id": 12,
  "roles":       ["HR Manager"],
  "permissions": ["employees.employee.view", "leaves.report.view", ...],
  "modules":     ["employees", "leaves", "dashboard"]
}
```

`permissions` and `modules` are computed from the user's roles.
**Superusers receive the entire catalogue**, so any frontend check passes.

### Privilege-escalation carve-outs

`accounts.user.edit` used to cover assigning roles, assigning campuses and
resetting passwords — a holder could grant themselves Admin. Those are now
separate keys and `UserDetailView.patch` checks each field group individually
via `apps.accounts.permissions.has_perm`:

| Key | Guards |
|---|---|
| `accounts.user.edit` | name, email, active status only |
| `accounts.user.assign_roles` | the `roles` M2M |
| `accounts.user.assign_campuses` | the `campuses` M2M — and therefore every `*_all_campuses` fallback in the app |
| `accounts.user.reset_password` | resetting another user's password |

**Do not merge these back together.**

### `portal_temp_password` — a deliberate plaintext store

`Student.portal_temp_password` and `Employee.portal_temp_password` hold the
**last issued plaintext password**, mirrored by
`apps/accounts/password_mirror.py::mirror_plaintext_password` from every code
path that sets a password (admin reset, self change, forgot/reset flow).

This is intentional parity with the legacy PHP system: HR wanted to re-share a
password without forcing a rotation. It is cleared by
`apps.admissions.services.clear_temp_password_for` on the student's first
successful login and on a self-service password change.

**Treat these columns as sensitive.** They are visible in the API to holders of
the relevant student/employee permissions and in Django admin. If security
requirements tighten, this is the first thing to remove — but confirm with the
institute first, because the operational workflow depends on it.

---

## 2.2 `roles` — the permission system

### Purpose

A flat, application-defined permission catalogue with roles as the grouping
mechanism. It deliberately does **not** use `django.contrib.auth.Permission`.

### Models

```
Permission                        Role
  key     (unique)   ◀────M2M────  name (unique)
  label                            description
  module                           is_system      (cannot be deleted)
  description                      permissions ──▶ M2M Permission
                                   users       ──▶ M2M accounts.User
```

`Permission.module` is the grouping used by the frontend sidebar (`modules` in
the `/me` payload).

### The catalogue — `apps/roles/seed.py`

`CATALOGUE` is a list of `(module, key, label)` tuples and is the **single
source of truth**. Admins never mint their own keys. Two helpers generate the
common shapes:

- `_crud(module, base, noun)` → `.view` / `.add` / `.edit` / `.delete`
- `_writes(module, base, noun)` → `.add` / `.edit` / `.delete` only, for
  reference lists whose **reads are open to any authenticated user** (states,
  cities, academic years, degrees, courses, semesters, batches, subjects,
  classrooms, time slots — they feed dropdowns everywhere).

Roughly 260 keys across these modules: `accounts`, `roles`, `master`, `leads`,
`employees`, `leaves`, `admissions`, `fees`, `academics`, `audit`, `tasks`,
`dashboard`, `hr`, `courseware`, `student_leaves`, `student_documents`,
`appointments`.

**`seed_permissions()` prunes.** Any `Permission` row whose key is absent from
`CATALOGUE` is deleted, cascading the role assignments with it. That makes
re-seeding fully reconciling on a fresh database — and destructive on an
existing one. Use `manage.py migrate_permissions` there instead; see
[chapter 1](01-getting-started.md) §1.5.

### Enforcement — `apps/accounts/permissions.py`

Two mechanisms, both bypassed by `is_superuser`:

```python
class MyView(APIView):
    permission_classes = [IsAuthenticated, HasPerm]
    required_perm = "fees.receipt.cancel"      # one fixed key, any method

class MyCrudView(APIView):
    permission_classes = [IsAuthenticated, HasPerm]
    perm_base = "master.campus"                # resolved per method:
    # GET/HEAD/OPTIONS → master.campus.view
    # POST             → master.campus.add
    # PUT/PATCH        → master.campus.edit
    # DELETE           → master.campus.delete
```

For finer control inside a handler (different keys for different fields), use
the module-level helper:

```python
from apps.accounts.permissions import has_perm
if not has_perm(request.user, "admissions.student.transfer"):
    ...
```

A view with **neither** `required_perm` nor `perm_base` and `HasPerm` attached
allows any authenticated user — `_resolve` returning `None` means "no
requirement". Be deliberate about that.

### Permission patterns you will meet repeatedly

| Suffix | Meaning |
|---|---|
| `.view` | See the list/detail, scoped to the caller's campuses |
| `.view_all` / `.view_all_campuses` | Drop the campus scope. Some modules use one name, some the other — check the module chapter |
| `.edit_any` / `.delete_any` | Act on records you did not create. Owners always retain implicit rights over their own |
| `.approve_any` / `.reject_any` | Decide requests outside your own reporting line. Being the applicant's manager authorises a decision with **no key at all** |
| `.submit` / `.submit_for_others` | File your own vs. file on someone else's behalf |

### Seeded roles

| Role | Contents |
|---|---|
| `Admin` | Every permission. `is_system=True`. `seed_admin_role()` re-`set`s it to the full catalogue on every run |
| `Faculty` | The minimal baseline attached to every freshly-provisioned employee. Keys in `FACULTY_PERMISSION_KEYS`: `leaves.report.view`, `audit.course_end.submit`, `dashboard.daily_report.submit`, `dashboard.sessions.view`, `dashboard.my_work.view`, `audit.self_appraisal.view_own`, `audit.self_appraisal.submit` |

The Faculty set is chosen for its **sidebar side-effects** as much as for the
endpoints: `leaves.report.view` unlocks the Leaves menu group,
`audit.course_end.submit` unlocks the Audit group.

`Designation.role` lets HR attach a default role per designation — provisioning
an employee's portal account applies it automatically
([chapter 8](08-hr.md) §8.1).

### Endpoints

| Method + path | Permission |
|---|---|
| `GET /api/permissions/` | `roles.role.view` — the whole catalogue, for the role editor |
| `GET/POST /api/roles/` | `roles.role.view` / `.add` |
| `GET/PATCH/DELETE /api/roles/<id>/` | `roles.role.*`. System roles cannot be deleted |

### Adding a new permission — checklist

1. Add the tuple to `CATALOGUE` in `apps/roles/seed.py`.
2. Reference it from a view (`required_perm` / `perm_base` / `has_perm`).
3. Reseed every environment — `seed_permissions` on a fresh DB,
   `migrate_permissions` on an existing one.
4. Grant it to the relevant roles from the Roles page.
5. Gate the sidebar entry and page in `jd-erp-web`
   ([chapter 12](12-frontend.md) §12.4).
6. Tell users to log out and back in — `permissions` is cached in
   `localStorage`.
7. Run `python manage.py check_permissions` to confirm code and catalogue agree.

---

## 2.3 `audit` — logging

Two independent trails.

### `audit.AuthLog` — authentication & access-control events

Written by helpers in `apps/audit/events.py`, called from the accounts views.
Captures `event`, `actor`, `target`, `identifier` (for failed logins where the
actor is unknown), `ip_address` (honours `X-Forwarded-For`), `user_agent`,
free-form `metadata`, `created_at`.

Events: `login_success`, `login_failure`, `logout`, `password_change`,
`password_reset`, `password_reset_requested`, `password_reset_completed`,
`role_create`, `role_update`, `role_delete`, `lockout`.

### django-auditlog — row-level data changes

Registered per model via each app's `signals.py`. `accounts.User` is registered
with `exclude_fields=["password", "last_login"]`. The
`auditlog.middleware.AuditlogMiddleware` attaches the acting user to each
change.

### Endpoints

| Path | Access |
|---|---|
| `GET /api/audit/auth-logs/` | **Superuser only, enforced in code.** There is no permission key and no frontend page |
| `GET /api/audit/data-logs/` | Same |

If you need to delegate audit-log access, add a key to the catalogue and check
it in `apps/audit/views.py`. The previously-existing `audit.log.view` key was
removed precisely because nothing checked it.

---

## 2.4 `common` — shared infrastructure

### `pagination.py`

`StandardPagination` — `PageNumberPagination`, default page 50,
`?page_size=` up to 200. Set as `DEFAULT_PAGINATION_CLASS`, but because every
list view is a plain `APIView` (which does not auto-paginate), views must opt
in:

```python
class MyView(PaginatedAPIViewMixin, APIView):
    def get(self, request):
        return self.paginate(Thing.objects.all(), ThingSerializer)
```

**Consequence:** some list endpoints return a bare array, others return
`{count, next, previous, results}`. The frontend handles both — check before
assuming a shape.

### `throttles.py`

Custom scopes layered on the DRF defaults. All use the Django cache
(`LocMemCache` by default — **per-process**, so with multiple gunicorn workers
the effective limits multiply by the worker count. Point `CACHES` at Redis in
production if throttling accuracy matters).

| Class | Scope | Keyed on |
|---|---|---|
| `LoginRateThrottle` | `login` | IP. Applied to login **and** refresh |
| `LeadIntakeThrottle` | `lead_intake` | `X-API-Key` + IP |
| `PasswordChangeThrottle` | `password_change` | authenticated user |
| `ForgotPasswordThrottle` | `forgot_password` | IP |

### `file_validation.py`

Magic-byte upload validation — see [chapter 1](01-getting-started.md) §1.7 for
installation. API:

```python
from apps.common.file_validation import (
    SecureFileField, IMAGE_MIMES, DOCUMENT_MIMES,
    validate_image, validate_pdf, validate_image_or_pdf, validate_document,
)

class MySerializer(serializers.Serializer):
    file = SecureFileField(allowed_mimes=DOCUMENT_MIMES, max_size_mb=25)
```

`SecureFileField` validates in `to_internal_value`, so an invalid upload never
touches storage. `DANGEROUS_MIMES` (executables, shell scripts, PHP, HTML,
SVG) are refused even if a profile would otherwise allow them.

**Any new upload field should use `SecureFileField`.** Several older fields
still use a plain `FileField` with an ad-hoc check — migrating them is safe,
low-risk cleanup.

### `views.py`

`UploadTestView` at `GET/POST /api/common/upload-test/` — a diagnostic endpoint
for verifying that libmagic detection works on a given host.
