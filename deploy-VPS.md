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
# MSG91 email/SMS, BulkSMS, Zoho/Gmail SMTP, DLT templates, etc.
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
