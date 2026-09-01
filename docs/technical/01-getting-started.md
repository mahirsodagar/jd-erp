# 1 — Getting Started & Operations

Everything you need to run the system locally, configure it for a new
environment, seed a fresh database, deploy it, and keep it running.

---

## 1.1 Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.13 (3.11+ works) | The checked-in `venv/` was built on 3.13 |
| Node.js | 20+ | Vite 8 / React 19 |
| libmagic | any | Optional but strongly recommended — see §1.7 |
| MySQL | 8.x | Production only. Local dev uses SQLite |

## 1.2 Backend — local setup

```bash
cd jd-erp

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env         # then edit — see §1.4
python manage.py migrate
python manage.py seed_permissions          # permission catalogue + Admin/Faculty roles
python manage.py createsuperuser
python manage.py runserver                 # http://127.0.0.1:8000
```

`requirements.txt`:

```
Django>=5.2,<5.3            djangorestframework>=3.15
djangorestframework-simplejwt>=5.3         django-cors-headers>=4.4
django-axes>=7.0            django-auditlog>=3.0      django-environ>=0.11
Pillow>=10.4                qrcode[pil]>=7.4          fpdf2>=2.7
python-magic>=0.4.27        gunicorn>=22.0            mysqlclient>=2.2
```

- `Pillow` + `qrcode` — employee ID cards, QR codes, UPI payment QRs.
- `fpdf2` — fee receipts, certificates, relieving/experience letters, the fee
  undertaking.
- `python-magic` — magic-byte upload validation (§1.7).
- `mysqlclient` is only needed in production; on macOS it needs
  `brew install mysql-client` to build. Drop it from a local install if it
  fails and you are on SQLite.

## 1.3 Frontend — local setup

```bash
cd jd-erp-web
npm install
cp .env.example .env.local
# .env.local:
#   VITE_API_URL=http://127.0.0.1:8000
npm run dev            # http://localhost:5173
```

> **Note on `VITE_API_URL`.** `src/lib/env.ts` requires it and the API client
> appends `/api/...` itself (`${env.apiUrl}/api/auth/refresh/`). Set it to the
> API **origin without** a trailing `/api` and without a trailing slash. The
> committed `.env.example` shows `https://dkul.jediiians.com/api/`, which is
> the value that matches the deployed reverse-proxy layout — check what your
> nginx does before copying either form blindly.

Other frontend scripts: `npm run build` (tsc + vite build → `dist/`),
`npm run lint`, `npm run preview`.

## 1.4 Environment variables

`jd-erp/.env.example` is the annotated reference and is kept current — read it
alongside this section. `config/settings.py` reads it via `django-environ`.
The variables that matter most:

### Required

| Var | Meaning |
|---|---|
| `SECRET_KEY` | Django secret. Also the JWT signing key (`SIMPLE_JWT.SIGNING_KEY`). **Rotating it invalidates every issued token.** |
| `DEBUG` | `True` locally, `False` in production (turns on HSTS, secure cookies, `X-Frame-Options: DENY`) |
| `ALLOWED_HOSTS` | Comma-separated hostnames |
| `DATABASE_URL` | `sqlite:///db.sqlite3` or `mysql://user:pass@host/db` |
| `CORS_ALLOWED_ORIGINS` | The frontend origins. Without these the SPA gets CORS errors |
| `CSRF_TRUSTED_ORIGINS` | Frontend origins plus the API's own origin |

### Auth & rate limiting

`ACCESS_TOKEN_MINUTES` (15), `REFRESH_TOKEN_MINUTES` (45),
`AXES_FAILURE_LIMIT` (5), `AXES_COOLOFF_MINUTES` (15),
`THROTTLE_USER` (100/min), `THROTTLE_ANON` (60/min), `THROTTLE_LOGIN` (10/min),
`THROTTLE_PASSWORD_CHANGE` (5/min), `THROTTLE_FORGOT_PASSWORD` (5/hour),
`THROTTLE_LEAD_INTAKE` (120/hour).

### Public integration

| Var | Meaning |
|---|---|
| `LEAD_INTAKE_API_KEY` | Static key for `POST /api/leads/intake/`. **If unset, the endpoint refuses every request** (fail-closed) |
| `FRONTEND_BASE_URL` | Used to build the public application-form link put into SMS/email |
| `STUDENT_PORTAL_LOGIN_URL` | Link students get in the credentials email |

### Messaging

These are covered in depth in [chapter 11](11-notifications.md). The gates you
must know:

| Var | Effect |
|---|---|
| `SMS_PROVIDER` | `bulksms` (default) or `msg91` |
| `WHATSAPP_ENABLED` | **Master gate.** While `False`, WhatsApp notifications are queued and never transmitted |
| `EMAIL_BACKEND` | Defaults to the **console backend** — mail is printed to stdout and silently never delivered. Set the SMTP backend in every real environment |
| `EMAIL_SMTP_OUTBOUND_ENABLED` | `False` on hosts with no SMTP egress; SMTP-routed triggers then downgrade to MSG91 |
| `MSG91_AUTHKEY`, `MSG91_SENDER_EMAIL`, `MSG91_DOMAIN` | MSG91 transactional email |
| `MSG91_SMS_AUTHKEY`, `MSG91_FLOW_*` | MSG91 SMS flow IDs |
| `BULK_SMS_USER/PASSWORD/SENDER`, `DLT_TPL_*` | BulkSMS + DLT template IDs |
| `XIRCLS_API_KEY`, `XIRCLS_WHATSAPP_PROJECT_KEY` | WhatsApp via XIRCLS |
| `SENDER_JDINSTITUTE_EDU`, `SENDER_JDINDIA`, `SMTP_JDINDIA_*` | Per-domain sender routing |

> **Known trap.** `MSG91_FORCE_IPV4` (default `True`, read in
> `apps/notifications/msg91.py`) pins MSG91 calls to IPv4. MSG91's per-authkey
> "IP Security" whitelist is IPv4-only; on a dual-stack host the default
> resolver prefers IPv6 and every call comes back **HTTP 401 / apiError 418**.
> Leave this on.

### Credentials you will need from the client

Collect and store these in a password manager before handover:

- MSG91 dashboard login (email authkey, SMS authkey, template & flow IDs,
  verified sender domains).
- BulkSMS Gateway India login (`jdinstitute`) and the DLT/TRAI principal-entity
  account that owns the approved templates.
- XIRCLS platform login (API key, WhatsApp project key, trigger/campaign names).
- Google Workspace mailbox used for internal SMTP (`admin.a@jdinstitute.edu.in`)
  — an **app password**, not the account password.
- Zoho/other SMTP credentials for `jdindia.com` if that domain is activated.
- VPS SSH key, MySQL credentials, Netlify (or equivalent) account.

## 1.5 Seed data — order matters

Run these on a fresh database, in this order:

```bash
python manage.py seed_permissions        # roles.Permission catalogue + Admin & Faculty roles
python manage.py seed_states             # Indian states/UTs
python manage.py seed_indian_cities      # cities (depends on states)
python manage.py seed_institutes         # JDIFT / JDSD
python manage.py seed_degrees
python manage.py seed_programs           # depends on institutes/campuses
python manage.py seed_lead_sources
python manage.py seed_leave_types
python manage.py seed_notification_templates
```

> ### ⚠ `seed_permissions` is for a **fresh** database only
>
> The command itself warns about this. `seed_permissions()` **prunes** — it
> deletes every `Permission` row whose key is not in
> `apps/roles/seed.py::CATALOGUE` — and the command also calls
> `seed_admin_role()` and `seed_faculty_role()`, which **overwrite** the
> permission sets of the `Admin` and `Faculty` roles with `.set(...)`.
> On an existing install that strips access two ways: newer narrow keys exist
> but no role holds them, retired keys are pruned outright, and any hand-made
> customisation of the Faculty role is discarded.
>
> **On an existing database use `migrate_permissions` instead.** It snapshots
> every role's current key set *before* pruning, seeds the catalogue, refreshes
> Admin, and then grants each role the new keys implied by its old ones. It
> only ever adds permissions and is safe to re-run. It deliberately does **not**
> call `seed_faculty_role()` unless you pass `--with-faculty`.
>
> ```bash
> python manage.py migrate_permissions --dry-run   # always look first
> python manage.py migrate_permissions
> ```
>
> If you need finer control still, call the pieces directly in a shell:
>
> ```python
> from apps.roles.seed import seed_permissions, seed_admin_role
> seed_permissions()
> seed_admin_role()
> ```

Other maintenance commands:

| Command | Purpose |
|---|---|
| `check_permissions` | Consistency check between catalogue and code — keys checked in code but absent from the catalogue (can never be granted), keys in the catalogue that nothing checks (dead checkbox), and `*_any` write keys gated behind a read key they do not satisfy. **Exits non-zero**, so it can gate CI |
| `migrate_permissions` | The safe reseed for an existing database — seeds the catalogue and carries roles across using the map in `apps/roles/migrate_map.py`. Supports `--dry-run` and `--with-faculty` |
| `backfill_employee_users` | Creates portal `User` accounts for employees that lack one |
| `process_notifications` | Drains due `ScheduledNotification` rows — **must be on cron** |
| `escalate_overdue_hot_leads` | Alerts on hot leads past their follow-up date |
| `notify_installments_due` | Installment-due SMS to student + parent |
| `notify_fee_bulk_reminder` | Bulk fee-reminder SMS campaign |
| `send_test_mail` / `send_test_sms` / `send_test_wa` | One-shot transport smoke tests (also wrapped by `scripts/test-jd-*.sh`) |

## 1.6 Scheduled jobs (cron)

There is **no Celery**. Anything time-based is a management command that must
be scheduled by the host's cron. At minimum:

```cron
# Drain the notification queue — without this, every future-dated
# notification (drip campaigns, visit reminders) never fires.
*/10 * * * *  cd /srv/jd-erp && venv/bin/python manage.py process_notifications

# Daily, morning
0 9 * * *     cd /srv/jd-erp && venv/bin/python manage.py notify_installments_due
30 9 * * *    cd /srv/jd-erp && venv/bin/python manage.py escalate_overdue_hot_leads
```

`notify_fee_bulk_reminder` is a campaign — run it on demand, not on a schedule.

## 1.7 File uploads & libmagic

`apps/common/file_validation.py` validates uploads by **magic bytes**, not by
extension or the client-supplied `Content-Type`. It blocks executables, shell
scripts, PHP, HTML and SVG (all XSS or RCE risks when served from `/media/`).

If `libmagic` is missing it degrades to a small built-in signature table
(JPEG/PNG/WEBP/GIF/BMP/PDF/MP4) and **rejects everything else** — fail-closed
by design. Install it:

```
Debian/Ubuntu   apt-get install libmagic1
Alpine          apk add libmagic
RHEL/Fedora     yum install file-libs
macOS           brew install libmagic
Windows         pip install python-magic-bin
```

Size caps: request body ≤ 60 MB (`DATA_UPLOAD_MAX_MEMORY_SIZE`), in-memory
file ≤ 5 MB, then per-profile caps (image 5 MB, PDF 10 MB, documents 25 MB).

## 1.8 Deployment

Full instructions are in **`jd-erp/deploy-VPS.md`** — read it before your first
deploy. Summary of the production topology:

- Hostinger VPS, shared with two unrelated projects (`ucovy`, `socialz`).
  Do not assume the box is yours alone.
- gunicorn behind nginx, managed as a systemd unit.
- MySQL (data was migrated from the earlier PythonAnywhere SQLite database).
- TLS via certbot.
- Frontend built with `npm run build` and published as a static bundle.

Deploy flow when a migration is involved:

```bash
# 1. snapshot the DB on the VPS
# 2. push code from your machine
# 3. on the VPS: pip install -r requirements.txt
#                python manage.py migrate
#                python manage.py collectstatic --noinput
#                systemctl restart jd-erp
```

`deploy-VPS.md` §7 documents the snapshot/restore helper scripts.

## 1.9 Logging & diagnosis

`config/settings.py` configures one logger: `apps.notifications` at INFO to the
console (captured by journald under systemd). It logs the exact outbound
WhatsApp/SMS/email calls including masked credentials. Raise or lower it with
`NOTIFICATIONS_LOG_LEVEL`. Set `XIRCLS_LOG_FULL_KEYS=True` only for short
debugging sessions — it writes raw API keys to the log.

**First places to look when something "didn't send":**

1. `NotificationDispatchLog` (Django admin or shell) — every attempt lands
   here with `status` and the provider's verbatim `error`.
2. `ScheduledNotification` with `processed_at IS NULL` and a past `fire_at` —
   means `process_notifications` is not running.
3. `EMAIL_BACKEND` — if it is still the console backend, mail is being printed
   and thrown away while the log row may still read `SENT`.

**First places to look when a user "can't see a page":**

1. `GET /api/auth/me/` → the `permissions` and `modules` arrays. The sidebar
   and every page gate read these.
2. The user's `campuses` M2M — most lists are campus-scoped.
3. Whether the user re-logged in after a role change: `permissions` is
   persisted in `localStorage` under `jd-erp-auth` and only refreshes on login
   or a `/api/auth/me/` call.

## 1.10 Backups

At minimum, back up nightly:

- the MySQL database,
- the `media/` directory (student photos, documents, assignment submissions,
  employee documents, courseware attachments — **none of this is regenerable**),
- the `.env` file (contains every provider credential).
