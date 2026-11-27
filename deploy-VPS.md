# JD-ERP — VPS Deployment Guide

Everything needed to operate the JD-ERP backend on the Hostinger VPS:
access, layout, deploy commands, database, backups, SMS/WhatsApp, TLS,
and troubleshooting.

> **Secrets are NOT in this file** (it lives in a Git repo). All
> credentials live in `/var/www/jd-erp/.env` on the server (`chmod 600`,
> owned by `www-data`). Never commit `.env`.

---

## 1. At a glance

| Item | Value |
|---|---|
| Host | Hostinger VPS, **187.127.142.10**, Ubuntu 24.04 |
| Live URL | https://dkul.jediiians.com |
| Backend dir | `/var/www/jd-erp` |
| App service | systemd **`jd-erp.service`** → gunicorn on `127.0.0.1:8002` |
| Web server | nginx site **`jd-erp`** (reverse proxy + static/media) |
| Database | MySQL **`jd_erp_db`** (user `jd_erp`) |
| Repo | github.com/mahirsodagar/jd-erp, branch **`main`** |
| Frontend | React on **Netlify** (`https://jdsd.netlify.app`) — not on the VPS |
| Deploy command | `deploy-jd-erp` (on the VPS) |

**This is a shared VPS.** It also runs two unrelated production apps —
**`ucovy`** (`ucovyconnects.com`) and **`socialz`** (`socialzz.cfd`).
Do **not** touch their dirs, services, nginx sites, or databases. Ports
already in use by others: `5000` (ucovy node), `8000`/`8001` (socialz
gunicorn/daphne), `8080`, `3306` (MySQL). JD-ERP uses **`8002`**.

---

## 2. SSH access

Login is **key-based, no password** (your Mac's `~/.ssh/id_ed25519`).

```bash
ssh root@187.127.142.10
```

Optional shortcut — add to `~/.ssh/config` on your Mac:

```
Host jd
    HostName 187.127.142.10
    User root
    IdentityFile ~/.ssh/id_ed25519
```

Then just `ssh jd`.

**Server → GitHub:** the VPS has its own SSH key (`/root/.ssh/id_ed25519`)
registered on the GitHub account, so `git pull` over SSH works
non-interactively. Repo remote is `git@github.com:mahirsodagar/jd-erp.git`.

---

## 3. Deploying (the normal path)

A single command on the VPS does everything:

```bash
ssh root@187.127.142.10
deploy-jd-erp
```

`/usr/local/bin/deploy-jd-erp` runs:

1. `git pull origin main`
2. `pip install -r requirements.txt`
3. `manage.py migrate --noinput`
4. `manage.py collectstatic --noinput`
5. `chown -R www-data:www-data /var/www/jd-erp` + `chmod 600 .env`
6. `systemctl restart jd-erp.service`

> **Anything you change locally must be committed and pushed to `main`
> first** — the deploy only pulls what's on GitHub.

### 2026-11-25 release — System Emails (template management)

Migrations `notifications.0026` + `0027` create the template tables.
Two new permission keys (`comms.system_email.view` / `.manage`) must be
seeded after the deploy — the deploy script does **not** do it:

```bash
cd /var/www/jd-erp && source venv/bin/activate
python manage.py migrate_permissions --dry-run   # then without --dry-run
```

Roles that hold `comms.template.manage` receive `manage`; bulk-email
managers receive `view`. Nothing else changes until an admin edits a
template: every mail keeps its previous wording as the code default.

### Recommended deploy flow (when a migration is involved)

Migrations run against the **production database** (real data). Snapshot
first:

```bash
# 1. snapshot the DB (on the VPS)
ssh root@187.127.142.10 'TS=$(date +%Y%m%d-%H%M%S); \
  mysqldump --single-transaction --routines --triggers jd_erp_db \
  | gzip > /root/backups/jd_erp_db_${TS}.sql.gz'

# 2. from your Mac: push code
git push origin main

# 3. deploy
ssh root@187.127.142.10 deploy-jd-erp
```

Before pushing schema changes, sanity-check locally:

```bash
python manage.py makemigrations --check --dry-run   # must say "No changes detected"
python manage.py check
```

---

## 4. Server layout

```
/var/www/jd-erp/                 # the Django project (this repo)
├── venv/                        # Python virtualenv
├── .env                         # secrets/config (chmod 600, NOT in git)
├── staticfiles/                 # collectstatic output (served by nginx)
├── media/                       # uploads (served by nginx)
└── manage.py
/usr/local/bin/deploy-jd-erp     # deploy script
/usr/local/bin/test-jd-sms       # SMS test wrapper
/etc/systemd/system/jd-erp.service
/etc/nginx/sites-available/jd-erp
/root/backups/                   # DB snapshots
/root/pa_data.json               # one-time PythonAnywhere import backup
```

Runtime user is **`www-data`** (matches the other apps on this box).
Management commands that write files should run as `www-data` so the
`chmod 600 .env` stays readable, e.g.:

```bash
sudo -u www-data /var/www/jd-erp/venv/bin/python /var/www/jd-erp/manage.py <cmd>
```

---

## 5. The gunicorn service

`/etc/systemd/system/jd-erp.service` runs gunicorn (`config.wsgi`) on
`127.0.0.1:8002`, 3 workers, as `www-data`.

```bash
systemctl status jd-erp.service
systemctl restart jd-erp.service
journalctl -u jd-erp.service -n 100 --no-pager   # app logs / tracebacks
```

---

## 6. Nginx

Site config: `/etc/nginx/sites-available/jd-erp` (symlinked in
`sites-enabled/`). It is **backend-only**:

- `/static/` → `/var/www/jd-erp/staticfiles/`
- `/media/`  → `/var/www/jd-erp/media/`
- everything else → `proxy_pass http://127.0.0.1:8002` (Django: `/api/`, `/admin/`, root)
- HTTPS via Let's Encrypt; HTTP (`:80`) 301-redirects to HTTPS

```bash
nginx -t                 # validate (also checks the other sites)
systemctl reload nginx
```

> You'll see harmless `conflicting server name "ucovyconnects.com"`
> warnings — those come from a pre-existing `default.bak` file in
> `sites-enabled`, not from the JD-ERP site. Leave them.

---

## 7. Database (MySQL)

- DB: `jd_erp_db`, user `jd_erp` — credentials in `/var/www/jd-erp/.env`
  (`DATABASE_URL=mysql://...`).
- `root` connects via socket auth (no password) for admin tasks:

```bash
mysql jd_erp_db                  # interactive
mysql -e "SHOW TABLES;" jd_erp_db
```

### Backups

```bash
# create a snapshot
TS=$(date +%Y%m%d-%H%M%S)
mysqldump --single-transaction --routines --triggers jd_erp_db \
  | gzip > /root/backups/jd_erp_db_${TS}.sql.gz

# list snapshots
ls -lh /root/backups/

# restore a snapshot (DESTRUCTIVE — overwrites current data)
gunzip < /root/backups/jd_erp_db_YYYYMMDD-HHMMSS.sql.gz | mysql jd_erp_db
```

### Data was migrated from PythonAnywhere (SQLite → MySQL)

Done once via `dumpdata`/`loaddata` (engine-agnostic). To repeat:

```bash
# export from a sqlite file on the VPS
DATABASE_URL="sqlite:////path/db.sqlite3" \
  venv/bin/python manage.py dumpdata --natural-foreign --natural-primary \
  --exclude contenttypes --exclude auth.permission --exclude admin.logentry \
  --exclude sessions.session --exclude axes --exclude token_blacklist \
  --indent 2 -o /root/pa_data.json
# load into MySQL (flush first to clear seed rows)
venv/bin/python manage.py flush --no-input
venv/bin/python manage.py loaddata /root/pa_data.json
```

---

## 8. Environment (`.env`)

Lives at `/var/www/jd-erp/.env`. Key VPS-specific values (full secrets on
the server only):

```
DEBUG=False
ALLOWED_HOSTS=dkul.jediiians.com,187.127.142.10
DATABASE_URL=mysql://jd_erp:***@127.0.0.1:3306/jd_erp_db
CORS_ALLOWED_ORIGINS=...,https://jdsd.netlify.app   # + localhost dev ports
CSRF_TRUSTED_ORIGINS=https://dkul.jediiians.com,https://jdsd.netlify.app,...
FRONTEND_BASE_URL=https://jdsd.netlify.app
SMS_PROVIDER=bulksms
ZEPTOMAIL_SMTP_TOKEN=***        # the ONLY mail credential (see §10a)
# BulkSMS, DLT templates, XIRCLS, payment gateways, etc.
```

After editing `.env`: `systemctl restart jd-erp.service`.

> Adding a local dev origin? Append it to `CORS_ALLOWED_ORIGINS`
> (and `CSRF_TRUSTED_ORIGINS`) and restart. Vite defaults to port 5173.

---

## 9. HTTPS / TLS

Certificate issued by Let's Encrypt (certbot), auto-renews via a systemd
timer.

```bash
certbot certificates           # show cert + expiry
certbot renew --dry-run        # test renewal
```

Cert path: `/etc/letsencrypt/live/dkul.jediiians.com/`.
DNS for `dkul.jediiians.com` is managed on **cPanel** (A record →
187.127.142.10). If you add a subdomain, point its A record here, then
`certbot --nginx -d <subdomain>`.

---

## 10. SMS

Provider is selected by `SMS_PROVIDER` (`bulksms` in prod). Test live
sends from the VPS:

```bash
test-jd-sms 9XXXXXXXXX                       # default template, real queue path
test-jd-sms 9XXXXXXXXX --raw                 # hit gateway directly
test-jd-sms 9XXXXXXXXX --template lead.application_link.sms \
            --var name=Ayush --var url=https://tinyurl.com/xxxx
test-jd-sms --show                           # recent SMS dispatch-log rows
```

Notes:
- `SENT` = the gateway **accepted/billed** it; final delivery is in the
  DLR (BulkSMS panel). Indian **DLT** silently drops messages whose body
  or **URL** doesn't match the approved template.
- URLs in SMS must use a DLT-whitelisted domain. The app shortens links
  via **TinyURL** (`tinyurl.com/...`) to match the approved templates —
  always send a `tinyurl.com` link, never a raw URL.
- Some "installment paid" SMS templates may be unregistered; seed them:
  `python manage.py seed_notification_templates`.

---

## 10a. Email (ZeptoMail)

All outbound mail goes through ZeptoMail SMTP From `no-reply@dkul.in`
(client rule since 2026-11-18: no other mailbox for auth or From).
The only prod `.env` key needed:

```bash
ZEPTOMAIL_SMTP_TOKEN=<ZeptoMail → Mail Agents → dkul.in → SMTP → token>
```

Host/port/user/From default correctly in `settings.py`
(`smtp.zeptomail.in:465` SSL, user `emailapikey`). Remove the old
`EMAIL_HOST*`, `SMTP_JDINDIA_*`, `MSG91_AUTHKEY`, `DEFAULT_FROM_EMAIL`
lines from the prod `.env` so they cannot override the defaults, then
`systemctl restart jd-erp.service`.

Test from the VPS:

```bash
test-jd-mail you@example.com                                   # plain test mail
test-jd-mail you@example.com --reply-to leave@jdinstitute.edu.in
test-jd-mail you@example.com --template student.portal_credentials.email
```

Replies land per trigger via Reply-To (`EMAIL_REPLY_TO_POLICY`); the
fallback is `EMAIL_DEFAULT_REPLY_TO` (webmaster@dkul.in).

---

## 11. WhatsApp (XIRCLS)

Transport is wired but **gated off** by `WHATSAPP_ENABLED` (default
`False`) — WA notifications stay `QUEUED` until enabled. To activate:

1. In `.env` set:
   ```
   WHATSAPP_ENABLED=True
   XIRCLS_API_KEY=<XIRCLS Profile → Global Settings → API Key>
   XIRCLS_WHATSAPP_PROJECT_KEY=<WhatsApp by XIRCLS → Settings → Projects → Token>
   XIRCLS_TRIGGER_LEAD_WELCOME=<trigger name created in XIRCLS>
   # ...other XIRCLS_TRIGGER_* per template
   ```
2. If your XIRCLS template parameter names differ from `name`/`program`/
   `date`/`subject`, adjust `XIRCLS_WA_PARAM_MAP` in `config/settings.py`.
3. `systemctl restart jd-erp.service`
4. Test:
   ```bash
   sudo -u www-data /var/www/jd-erp/venv/bin/python \
     /var/www/jd-erp/manage.py send_test_wa 9XXXXXXXXX \
     --template lead_welcome_wa --var name=Ayush
   # or: ... send_test_wa --show
   ```

Trigger/template must be **active** in XIRCLS or the API returns
`Campaign not active`.

---

## 12. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `502 Bad Gateway` | gunicorn down → `systemctl status jd-erp.service`; `journalctl -u jd-erp.service` |
| `400 Bad Request` | host not in `ALLOWED_HOSTS` → add it to `.env`, restart |
| Browser shows the wrong site | client DNS/cache, or SNI mismatch → hard refresh / incognito; verify with `curl --resolve dkul.jediiians.com:443:187.127.142.10 https://dkul.jediiians.com/` |
| CORS error from frontend | origin missing from `CORS_ALLOWED_ORIGINS` → add it, restart |
| Deploy pulled nothing | local changes not pushed → `git push origin main` first |
| `W036 ... MySQL does not support unique constraints with conditions` | harmless warning; those partial-unique constraints aren't enforced on MySQL (enforce in app logic if needed) |
| App tracebacks | `journalctl -u jd-erp.service -n 200 --no-pager` |

---

## 13. First-time / rebuild setup (reference)

If the box is ever rebuilt, recreate in this order:

1. `apt install` python venv, nginx, git, MySQL client libs:
   `build-essential pkg-config default-libmysqlclient-dev python3-dev python3-venv libmagic1 libjpeg-dev zlib1g-dev`
2. Create MySQL `jd_erp_db` + user `jd_erp`, grant privileges.
3. Generate `/root/.ssh/id_ed25519`, add the public key to GitHub.
4. `git clone git@github.com:mahirsodagar/jd-erp.git /var/www/jd-erp`
5. `python3 -m venv venv && venv/bin/pip install -r requirements.txt`
6. Create `/var/www/jd-erp/.env` (see §8).
7. `migrate`, `collectstatic`, create superuser (or `loaddata` a backup).
8. Install `jd-erp.service`, `enable --now`.
9. Install the nginx site, `nginx -t`, `reload`.
10. `certbot --nginx -d dkul.jediiians.com`.
11. `chown -R www-data:www-data /var/www/jd-erp`.

---

## 15. Lead inbox poller (email → lead)

Leads → Email Inbox reads `leads@jdinstitute.edu.in` over IMAP
(Google Workspace, app password) and creates leads from website form
notifications, tawk.to chats and portal mails. Code:
`apps/leads/mail_fetch.py`, `mail_parsers.py`, `mail_intake.py`.

**.env** (no inline comments!):

```
LEAD_MAIL_IMAP_HOST=imap.gmail.com
LEAD_MAIL_IMAP_PORT=993
LEAD_MAIL_IMAP_USER=leads@jdinstitute.edu.in
LEAD_MAIL_IMAP_PASSWORD=<google app password>
LEAD_MAIL_IMAP_FOLDER=INBOX
LEAD_MAIL_DUP_WINDOW_HOURS=24
```

**First deploy** (release 2026-11-27):

```bash
cd /var/www/jd-erp
sudo -u www-data venv/bin/python manage.py migrate                      # leads.0020
sudo -u www-data venv/bin/python manage.py migrate_permissions --dry-run # leads.mail.* keys
sudo -u www-data venv/bin/python manage.py migrate_permissions
sudo -u www-data venv/bin/python manage.py seed_lead_mail_rules         # website / tawk / ignore rules
sudo -u www-data venv/bin/python manage.py fetch_lead_emails            # parks the cursor at the newest mail
```

Then grant `leads.mail.view` / `leads.mail.manage` / `leads.mail.rules`
to the admissions roles from Admin → Roles (new keys start unassigned).

**Cron** (as www-data) — the only scheduled job on this box so far:

```bash
sudo -u www-data crontab -e
*/5 * * * * cd /var/www/jd-erp && venv/bin/python manage.py fetch_lead_emails >> /var/www/jd-erp/logs/lead_mail.log 2>&1
```

Create `/var/www/jd-erp/logs/` (owned by www-data) first. The first
run only parks the cursor; later runs read mail newer than that.
`--backfill-days N` imports older mail once (every mail is stored
exactly once, so re-running is safe). `--reprocess` re-reads stored
mails that failed, after fixing a rule or a WebsiteValueMap row.

Health shows on the Email Inbox page (last checked, last error) and in
Django admin → Lead mail sync states. A Google "Security alert" mail
after the first login from the VPS IP is expected.

## 14. Seeding employees (one-time, campus-wise)

The legacy Employee Master exports (Bengaluru, Goa, Hyderabad,
Vijayawada, Cochin) are bundled in `apps/employees/seed_data/`.
Run `seed_states` and `seed_institutes` first (cities are created on
the fly), then:

```bash
cd /var/www/jd-erp
sudo -u www-data venv/bin/python manage.py seed_employees           # dry-run, read the report
sudo -u www-data venv/bin/python manage.py seed_employees --apply
sudo -u www-data venv/bin/python manage.py backfill_employee_users --apply   # portal logins
```

Idempotent on `emp_code`: re-running leaves existing employees alone
(`--update` overwrites them from the CSV). The report lists skipped
rows (test accounts, rows without email/DOB, the same person exported
under two campuses) and reporting-manager names that match nobody, so
HR can fix those in HR → Employees. Campuses HYD / BZA / COK are
created if missing.

---

## 16. Security hardening (2026-11-27 pass)

Changes from the audit against `React_Django_ERP_Security_Testing_Plan.md`.
Everything here is backend-only; the web repo only gained
`public/_headers` (Netlify security headers) and an `npm audit fix`.

### Deploy steps for this release

```bash
cd /var/www/jd-erp
sudo -u www-data venv/bin/pip install -r requirements.txt      # PyJWT / sqlparse / urllib3 pins
sudo -u www-data venv/bin/python manage.py check --deploy
sudo -u www-data venv/bin/python manage.py createcachetable       # only if CACHE_URL=dbcache://... below
systemctl restart jd-erp.service
```

### `.env` additions / checks

| Key | Why |
|---|---|
| `BULK_SMS_PASSWORD=...` | **REQUIRED.** The in-source default was removed (it was a secret in git). Without it SMS sends fail with "not configured". Rotate it on the BulkSMS dashboard and put the new value here. |
| `CACHE_URL=dbcache://jd_erp_cache` | DRF throttles + login buckets live in Django's cache; LocMem is per gunicorn worker (3×), so set a shared store. Run `createcachetable` once. `redis://127.0.0.1:6379/1` also works if the `redis` package is installed. |
| `DRF_NUM_PROXIES=1` (default) | Throttle IPs are read from the LAST `X-Forwarded-For` hop. Confirm the nginx site has `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;` and `proxy_set_header X-Forwarded-Proto $scheme;`. If nginx does NOT set XFF, set `DRF_NUM_PROXIES=0`. |
| `SECURE_SSL_REDIRECT=True` (optional) | Django-side HTTPS redirect backstop. Only after confirming `X-Forwarded-Proto` is forwarded, else every request loops. |

### nginx checklist (verify on the box, `nginx -T`)

```nginx
server_tokens off;
client_max_body_size 60m;                      # matches DATA_UPLOAD_MAX_MEMORY_SIZE
location ~ /\.(env|git|ht) { deny all; }
location /media/ {
    alias /var/www/jd-erp/media/;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Content-Security-Policy "sandbox" always;   # uploaded files can't run script on this origin
    add_header Content-Disposition "attachment";           # optional: force download instead of render
}
```

### Private media (`/media/` is no longer public)

Stored files are reached only through signed, expiring links
(`/api/media/<token>/`, `apps/common/media_urls.py`, 2 h by default via
`MEDIA_LINK_TTL_SECONDS`). Django answers with `X-Accel-Redirect` and
nginx streams the bytes from an `internal` location. New uploads also get
random names (`apps/common/upload_paths.py`). The ONE public exception is
`/media/institute/logos/` — logos are embedded in outgoing e-mail.

`.env`: `MEDIA_ACCEL_PREFIX=/protected-media/`

nginx (replace the old `location /media/` block):

```nginx
# Public: institute logos only (e-mail embeds them).
location /media/institute/logos/ {
    alias /var/www/jd-erp/media/institute/logos/;
    add_header X-Content-Type-Options "nosniff" always;
}
# Everything else under /media/ is private — 404 to the outside world.
location /media/ { return 404; }
# Reached only via X-Accel-Redirect from /api/media/<token>/.
location /protected-media/ {
    internal;
    alias /var/www/jd-erp/media/;
    add_header X-Content-Type-Options "nosniff" always;
}
```

Then `nginx -t && systemctl reload nginx`. Check: `curl -I https://<host>/media/students/photos/<anything>` → 404, while a
photo on a student page still renders.

Migrations in this release (`manage.py migrate`): academics, admissions,
courseware, employees, leads 0021, master 0030, student_documents, tasks
(upload_to), payments 0008 (`PaymentOrder.review_note`). Then
`manage.py migrate_permissions` for the new `academics.marks.view_all_campuses`
key (back-filled onto roles holding certificate / student campus-wide keys
or transcript.view_any — review on Admin → Roles).

### Django admin

Recommendation: turn the raw model admin OFF in production
(`ADMIN_SITE_ENABLED=False`). The React app is the ERP's admin; the Django
admin is session-authenticated, has no 2FA, exposes every model, and is a
standing brute-force target at a guessable path. For the rare one-off use
`manage.py shell` over SSH. If it must stay on, set `ADMIN_URL_PATH` to a
random segment (e.g. `ADMIN_URL_PATH=ops-7f3a9c/`) and add 2FA
(`django-otp` + `django-otp-admin`) before exposing it.

### Behaviour changes to know about

- Uploads everywhere are validated by magic bytes (`apps/common/file_validation.py`).
  Office files sniff as zip and plain text as octet-stream when libmagic
  is missing, so **libmagic1 must stay installed on the VPS** (it is in §13).
- Courseware attachments no longer accept `.svg`.
- Deactivating a user (Admin → Users), a dropout, an admin password reset,
  a self-service password change and a forgot-password reset all revoke
  the account's refresh tokens (other devices are signed out; the
  change-password response hands the current session a fresh pair).
- Browser tokens live in sessionStorage: a new tab needs a fresh login.
- Enrollment edit can no longer change `status` / `campus` / `student`
  (Drop Out / Transfer actions only). Students cannot change name, DOB,
  Aadhaar or gender once enrolled.
- Marks are campus-scoped (new key `academics.marks.view_all_campuses`).
- Gateway-settled receipts: money fields and reference are locked;
  Lead "mark fee paid" / "clear" refuse when a gateway payment exists.
- Payments: an order paid on a CANCELLED request, with a different amount,
  or as a second payment on a PAID request is NOT booked — it is flagged
  on the order (`review_note`, visible under the lead's online payments)
  for Accounts. Refund / void events cancel the receipt and reopen the fee.
- Tasks: staff accounts only (students / parents can't create or be assigned).
- Entrance exam: server enforces duration (+2 min grace).
- Application form link: locked at enrolment; expires
  `APPLICATION_LINK_VALID_DAYS` (90) after last send / re-open.
- Portal-account provisioning with roles and Designation→role links need
  `accounts.user.assign_roles` (grant it to the HR role if HR does this).
- `/api/auth/me/` refuses an email that belongs to any Employee record.
- Lead intake + website webhook are throttled per IP before the API key
  check (bad keys are throttled too).
- New auditlog coverage: OtherFee, PaymentOrder status, EntranceExam(+Attempt),
  DailyReportAccess, RelievingManager, Role permissions/users m2m, User.campuses.
