"""Django settings for the jd-erp project (single-tenant)."""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])


# --- Logging ------------------------------------------------------------
# Send app logs to the console (gunicorn/journald captures them on the
# VPS; the terminal shows them locally). apps.notifications logs the exact
# outbound WhatsApp/SMS/email calls at INFO — see apps/notifications/*.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "loggers": {
        "apps.notifications": {
            "handlers": ["console"],
            "level": env("NOTIFICATIONS_LOG_LEVEL", default="INFO"),
            "propagate": False,
        },
    },
}


# --- Apps ---------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "axes",
    "auditlog",

    "apps.accounts",
    "apps.roles",
    "apps.audit",
    "apps.master",
    "apps.leads",
    "apps.employees",
    "apps.leaves",
    "apps.admissions",
    "apps.fees",
    "apps.notifications",
    "apps.academics",
    "apps.audit_reports",
    "apps.relieving",
    "apps.common",
    "apps.courseware",
    "apps.student_leaves",
    "apps.student_documents",
    "apps.appointments",
    "apps.portal",
    "apps.tasks",
]


# --- Middleware ---------------------------------------------------------

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "axes.middleware.AxesMiddleware",
    "auditlog.middleware.AuditlogMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# --- Database -----------------------------------------------------------

DATABASES = {"default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")}


# --- Auth ---------------------------------------------------------------

AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "apps.accounts.backends.UsernameOrEmailBackend",
    "django.contrib.auth.backends.ModelBackend",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# --- DRF + JWT ----------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.StandardPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        # Authenticated users: ~100 requests/minute is plenty for normal
        # SPA traffic (page loads fanout to ~5 endpoints + react-query
        # dedupes); attackers / runaway scripts trip it long before
        # they can do damage.
        "user": env("THROTTLE_USER", default="100/min"),
        # Anonymous (unauthenticated) callers — same target.
        "anon": env("THROTTLE_ANON", default="60/min"),
        # Auth-sensitive endpoints (login, refresh) — tight bucket per IP.
        "login": env("THROTTLE_LOGIN", default="10/min"),
        # Password-change per user — tighter than the general user rate.
        "password_change": env("THROTTLE_PASSWORD_CHANGE", default="5/min"),
        # Forgot/reset password — anonymous, per IP. Conservative cap
        # because each request can dispatch an email.
        "forgot_password": env("THROTTLE_FORGOT_PASSWORD", default="5/hour"),
        # Public lead intake — per (API key, IP).
        "lead_intake": env("THROTTLE_LEAD_INTAKE", default="120/hour"),
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("ACCESS_TOKEN_MINUTES", default=15)),
    "REFRESH_TOKEN_LIFETIME": timedelta(minutes=env.int("REFRESH_TOKEN_MINUTES", default=45)),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}


# --- CORS / CSRF --------------------------------------------------------

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])


# --- django-axes --------------------------------------------------------

# --- Lead intake API key ------------------------------------------------

LEAD_INTAKE_API_KEY = env("LEAD_INTAKE_API_KEY", default="")


# --- Leave module -------------------------------------------------------

LEAVES_EXCLUDE_HOLIDAYS_AND_WEEKENDS = env.bool(
    "LEAVES_EXCLUDE_HOLIDAYS_AND_WEEKENDS", default=True,
)
LEAVES_HR_INBOX = env("LEAVES_HR_INBOX", default="leave@jdinstitute.edu.in")


# --- Frontend / public links --------------------------------------------

# Used to build the public application form URL embedded in SMS/email.
# Should point at the React app's host root (no trailing slash).
FRONTEND_BASE_URL = env(
    "FRONTEND_BASE_URL", default="https://jdsd.netlify.app",
)

# Where students land when they click a "log in to portal" link in an
# email (portal credentials, password resets, etc.). Different from the
# staff frontend — the student SPA is hosted separately.
STUDENT_PORTAL_LOGIN_URL = env(
    "STUDENT_PORTAL_LOGIN_URL",
    default="https://jdsd.netlify.app/#/portal/login/",
)

# Per-institute short payment URLs used by the fee-link flow. Defaults
# match the legacy PHP project's DLT-approved short links so we don't
# need fresh approvals from BulkSMS. Override per environment via env
# vars when you have new short URLs.
FEE_LINK_URLS = {
    "JDIFT": env("FEE_LINK_URL_JDIFT", default="https://9cfb.short.gy/jdinst"),
    "JDSD":  env("FEE_LINK_URL_JDSD",  default="https://9cfb.short.gy/jdsd"),
}


# --- Application-fee payment instructions ------------------------------

# Per-institute UPI / bank-account details rendered into the fee-link
# email (with a generated QR). Override via env vars (JSON) when prod
# values land. Each entry: vpa, payee_name, ac_name, ac_no, ifsc,
# bank, branch, default_amount.
INSTITUTE_PAYMENT_DETAILS = env.json(
    "INSTITUTE_PAYMENT_DETAILS",
    default={
        "JDIFT": {
            "vpa": "jdift@hdfc",
            "payee_name": "JD Institute of Fashion Technology",
            "ac_name": "JD INSTITUTE OF FASHION TECHNOLOGY",
            "ac_no": "00000000000000",
            "ifsc": "HDFC0000000",
            "bank": "HDFC Bank",
            "branch": "Bengaluru",
            "default_amount": "1000",
        },
        "JDSD": {
            "vpa": "jdsd@hdfc",
            "payee_name": "JD Educational Trust",
            "ac_name": "JD EDUCATIONAL TRUST",
            "ac_no": "00000000000000",
            "ifsc": "HDFC0000000",
            "bank": "HDFC Bank",
            "branch": "Bengaluru",
            "default_amount": "1000",
        },
    },
)


# --- SMS provider selection --------------------------------------------

# Which gateway to use for outbound SMS:
#   "msg91"   — control.msg91.com /api/v5/flow/  (works on PA free; uses
#               a separate authkey + per-template flow IDs)
#   "bulksms" — api.bulksmsgateway.in            (blocked on PA free's
#               outbound proxy; only works on paid PA plans)
SMS_PROVIDER = env("SMS_PROVIDER", default="bulksms")


# --- SMS — Bulk SMS Gateway India (legacy / fallback) ------------------

# https://www.bulksmsgateway.in — DLT-compliant transactional SMS.
# Templates MUST be pre-registered with TRAI/DLT operators; the keys
# below map our notification template_keys to the registered IDs.
# Defaults mirror what the legacy PHP project used so the integration
# works out of the box; override via env for any new environment.
BULK_SMS_USER = env("BULK_SMS_USER", default="jdinstitute")
BULK_SMS_PASSWORD = env("BULK_SMS_PASSWORD", default="JDInstitute321!")
BULK_SMS_SENDER = env("BULK_SMS_SENDER", default="JDEDUC")
BULK_SMS_TEMPLATE_IDS = {
    "lead.application_link.sms": env(
        "DLT_TPL_APPLICATION_LINK", default="1307167852052800815",
    ),
    "lead.fee_link.sms": env(
        "DLT_TPL_FEE_LINK", default="1307168958796572350",
    ),
    "attendance.student_absent.sms": env(
        "DLT_TPL_STUDENT_ABSENT", default="1307167524495832485",
    ),
    "attendance.parent_absent.sms": env(
        "DLT_TPL_PARENT_ABSENT", default="1307167525522133170",
    ),
    "attendance.student_absent_v2.sms": env(
        "DLT_TPL_STUDENT_ABSENT_V2", default="1307168612006682942",
    ),
    "attendance.parent_absent_v2.sms": env(
        "DLT_TPL_PARENT_ABSENT_V2", default="1307168611999645882",
    ),
    "fees.installment_due_student.sms": env(
        "DLT_TPL_INSTALLMENT_DUE_STUDENT", default="1307167525346509509",
    ),
    "fees.installment_due_parent.sms": env(
        "DLT_TPL_INSTALLMENT_DUE_PARENT", default="1307167525541582049",
    ),
    "fees.installment_paid_student.sms": env(
        "DLT_TPL_INSTALLMENT_PAID_STUDENT", default="1307167525451487583",
    ),
    "fees.installment_paid_parent.sms": env(
        "DLT_TPL_INSTALLMENT_PAID_PARENT", default="1307167525469517516",
    ),
    "fees.bulk_reminder.sms": env(
        "DLT_TPL_FEE_BULK_REMINDER", default="1707177090290548299",
    ),
}


# --- SMS — MSG91 v5 flow API ------------------------------------------

# Separate authkey from the email one; MSG91 lets you mint per-purpose
# keys ("SMS" row in the dashboard). Falls back to MSG91_AUTHKEY if the
# SMS-specific key isn't set.
MSG91_SMS_AUTHKEY = env("MSG91_SMS_AUTHKEY", default="")
MSG91_SMS_SENDER_ID = env("MSG91_SMS_SENDER_ID", default="JDEDUC")

# Map our internal template_key → the MSG91 *flow ID* (24-char hex from
# the MSG91 dashboard after a DLT template has been linked). MSG91
# stores the DLT-approved body on their side; we just send variables.
# Leave a key empty until the corresponding flow is registered on the
# MSG91 dashboard — `send_sms` will then return a clear "not configured"
# error in the dispatch log instead of a 4xx from the provider.
MSG91_SMS_TEMPLATE_IDS = {
    "lead.application_link.sms":       env("MSG91_FLOW_APPLICATION_LINK", default=""),
    "lead.fee_link.sms":               env("MSG91_FLOW_FEE_LINK", default=""),
    "attendance.student_absent.sms":   env("MSG91_FLOW_STUDENT_ABSENT", default=""),
    "attendance.parent_absent.sms":    env("MSG91_FLOW_PARENT_ABSENT", default=""),
    "attendance.student_absent_v2.sms": env("MSG91_FLOW_STUDENT_ABSENT_V2", default=""),
    "attendance.parent_absent_v2.sms":  env("MSG91_FLOW_PARENT_ABSENT_V2", default=""),
    "fees.installment_due_student.sms":   env("MSG91_FLOW_INSTALLMENT_DUE_STUDENT", default=""),
    "fees.installment_due_parent.sms":    env("MSG91_FLOW_INSTALLMENT_DUE_PARENT", default=""),
    "fees.installment_paid_student.sms":  env("MSG91_FLOW_INSTALLMENT_PAID_STUDENT", default=""),
    "fees.installment_paid_parent.sms":   env("MSG91_FLOW_INSTALLMENT_PAID_PARENT", default=""),
    "fees.bulk_reminder.sms":             env("MSG91_FLOW_FEE_BULK_REMINDER", default=""),
}

# Positional variable mapping per template. The template body
# registered on MSG91's dashboard uses `{#var#}` placeholders which
# become `var1`, `var2`, … on the wire. Order must match the order in
# the DLT-approved body. Keys reference our context dict; missing keys
# render as empty strings.
MSG91_SMS_VAR_ORDER = {
    "lead.application_link.sms": ["name", "url"],
    "lead.fee_link.sms":         ["short_name", "url"],

    # Attendance — student/parent (legacy variant; matches DLT body)
    # "Dear {name}, You have been marked absent for {date} for module {subject}..."
    "attendance.student_absent.sms": ["name", "date", "subject"],
    # "Dear Parent, Please be informed {name}, of {batch} is absent on {date}..."
    "attendance.parent_absent.sms":  ["name", "batch", "date"],

    # Attendance v2 — newer DLT variants ("JD Academic Team" footer)
    "attendance.student_absent_v2.sms": ["name", "date", "subject"],
    "attendance.parent_absent_v2.sms":  ["name", "batch", "date"],

    # Fees — installment due
    # Student: "Dear {name},{registration_no}, {installment} Installment
    #          of INR {amount}, for the course {course}, is due on {due_date}..."
    "fees.installment_due_student.sms": [
        "name", "registration_no", "installment", "amount", "course", "due_date",
    ],
    # Parent: "Dear Parent, {installment} Installment of INR {amount} of
    #         your ward, {ward_name} {registration_no} for the course
    #         {course}, is due on {due_date}..."
    "fees.installment_due_parent.sms": [
        "installment", "amount", "ward_name", "registration_no",
        "course", "due_date",
    ],

    # Fees — installment paid
    # Student: "Dear {name},{registration_no}, Thank you for the payment
    #          of INR {amount} towards your {installment} installment..."
    "fees.installment_paid_student.sms": [
        "name", "registration_no", "amount", "installment",
    ],
    # Parent: "Dear Parent, Thank you for the payment of INR {amount}
    #         towards the {installment} installment, of your ward
    #         {ward_name},{registration_no}, for the course {course}..."
    "fees.installment_paid_parent.sms": [
        "amount", "installment", "ward_name", "registration_no", "course",
    ],

    # Fees — bulk reminder. Static body, no vars.
    "fees.bulk_reminder.sms": [],
}


# --- WhatsApp — XIRCLS trigger API ------------------------------------
#
# XIRCLS bridges to the WhatsApp Business API. Each send references a
# pre-configured *trigger* (campaign) on the XIRCLS platform plus named
# *parameters* that fill the approved template. See
# apps/notifications/whatsapp.py for the client.
#
# Master gate: WA-channel notifications stay queue-only (no transport)
# until this is True — flip it on AFTER the triggers/keys below are set,
# so enabling the integration doesn't suddenly message every new lead.
WHATSAPP_ENABLED = env.bool("WHATSAPP_ENABLED", default=False)

XIRCLS_API_URL = env(
    "XIRCLS_API_URL",
    default="https://api.xircls.com/talk/api/v1/send_trigger_message/",
)
# Api-key: XIRCLS Profile → Global Settings → Generate API Key.
XIRCLS_API_KEY = env("XIRCLS_API_KEY", default="")
# Whatsapp-Project-Key: WhatsApp by XIRCLS → Settings → Projects → Token.
XIRCLS_WHATSAPP_PROJECT_KEY = env("XIRCLS_WHATSAPP_PROJECT_KEY", default="")
XIRCLS_DEFAULT_COUNTRY_CODE = env("XIRCLS_DEFAULT_COUNTRY_CODE", default="91")
XIRCLS_TIMEOUT = env.int("XIRCLS_TIMEOUT", default=10)
# When True, whatsapp.py logs the raw Api-key / Project-Key values (else
# they're masked). Turn on only for short debugging sessions.
XIRCLS_LOG_FULL_KEYS = env.bool("XIRCLS_LOG_FULL_KEYS", default=False)

# our template_key → XIRCLS trigger (campaign) name as created on the
# XIRCLS platform. Trigger names aren't secrets — they're campaign
# identifiers, one per message type — so they live here (not in .env).
# Leave a value "" until that campaign is approved/active on XIRCLS; a
# blank trigger yields a clear "not mapped" error in the dispatch log
# rather than a provider rejection. Fill each in as its template is
# approved. These are the WHATSAPP-channel keys queued across the app
# (signals.py, attendance_service.py, send_links.py, seeder).
XIRCLS_WA_TRIGGERS = {
    "lead_welcome_wa":          "",   # welcome message
    "hot_followup_reminder":    "",   # hot-lead follow-up
    "campus_visit_reminder":    "",   # campus visit reminder
    "post_visit_thanks_wa":     "",   # post-visit thanks
    "not_answered_followup":    "",   # missed-call follow-up
    "enrolled_confirmation_wa": "",   # enrollment confirmation
    "student_absent_wa":        "",   # attendance absentee
    # Application-form link — sent alongside the SMS/email legs in
    # apps/leads/send_links.send_application_link. TEMP: on the active
    # "Test" trigger until "application_form_2026" is approved on XIRCLS.
    "lead.application_link.wa": "Test",
    # Fee-payment link — sent alongside the SMS/email legs in
    # apps/leads/send_links.send_fee_link. Blank until its fee-link
    # template is approved on XIRCLS (then put the trigger name here).
    "lead.fee_link.wa": "",
}

# our template_key → {xircls_param_name: our_context_key}. The LEFT side
# is the parameter name as configured in that XIRCLS template; the RIGHT
# side is the key in the context dict we queue with. Adjust the left-hand
# names to match each XIRCLS template. A template_key absent here sends
# the whole context dict as-is (param names == context keys).
XIRCLS_WA_PARAM_MAP = {
    "lead_welcome_wa":          {"name": "name", "program": "program"},
    "hot_followup_reminder":    {"name": "name"},
    "campus_visit_reminder":    {"name": "name"},
    "post_visit_thanks_wa":     {"name": "name"},
    "not_answered_followup":    {"name": "name"},
    "enrolled_confirmation_wa": {"name": "name", "program": "program"},
    "student_absent_wa":        {"name": "name", "date": "date", "subject": "subject"},
    # Application-form link. TEMP: mapped to the active "Test" trigger,
    # whose only variable is `test` (the student name). Swap back to the
    # real params (e.g. {parameter_1: name, parameter_2: url}) once the
    # "application_form_2026" template is approved on XIRCLS.
    "lead.application_link.wa": {"test": "name"},
    # Fee-payment link. Placeholder param names — confirm against the
    # approved XIRCLS fee-link template before its trigger goes live.
    "lead.fee_link.wa": {"parameter_1": "name", "parameter_2": "url"},
}


# --- Email — MSG91 v5 transactional -----------------------------------

# Legacy PHP project posts to https://control.msg91.com/api/v5/email/send
# with hardcoded credentials. We default to the same values so the
# template-based mails (`student_invoice_copy`, `assignment_assigned`,
# `application_fee_receipt` etc.) keep working through the migration.
# Override via env per environment — see apps/notifications/msg91.py.
MSG91_AUTHKEY = env(
    "MSG91_AUTHKEY", default="411327AvSZtxr9aUFW6669485dP1",
)
MSG91_SENDER_EMAIL = env(
    "MSG91_SENDER_EMAIL", default="admin@mail.jdinstitute.com",
)
MSG91_DOMAIN = env(
    "MSG91_DOMAIN", default="mail.jdinstitute.com",
)
MSG91_TIMEOUT = env.int("MSG91_TIMEOUT", default=10)

# Routing policy:
#
#   * MSG91 (mail.jdinstitute.com) — transactional mail to EXTERNAL
#     recipients (leads, students, parents). Anything in this dict
#     goes through the MSG91 v5 email API.
#
#   * SMTP (admin.a@jdinstitute.edu.in via Workspace) — INTERNAL
#     mail to faculty / employees (HR workflows, leave notifications
#     to employees, task assignments, staff password resets, etc.).
#     Any template NOT listed below falls through to plain SMTP via
#     apps.notifications.email.send_email.
#
# Don't bypass this policy by adding internal-staff templates here —
# the two domains have different reputations + branding for a reason.
MSG91_EMAIL_TEMPLATES = {
    # Fees — to students / parents
    "fees.receipt.email":                  "student_invoice_copy",
    "fees.application_fee_receipt.email":  "application_fee_receipt",

    # Academics — to students
    "academics.assignment_assigned.email": "assignment_assigned",

    # Leaves — STUDENT leave status (employee leave stays on SMTP).
    "leaves.application_status_student.email": "leave_application_status_student",

    # Student portal credential + reset (student-facing).
    "student.portal_credentials.email": "student_portal_credentials",

    # Lead / CRM — to leads (external prospects).
    "lead.application_link.email": "lead_application_link",
    "lead.fee_link.email":         "lead_fee_link",
    "lead.welcome.email":          "lead_welcome",
}

# --- Email — per-trigger sender domain routing ------------------------
#
# The From *domain* varies by trigger, and for fee / admission mail it
# varies by the student's course type (institute spec):
#
#   Diploma courses        → jdinstitute.edu.in
#   Degree / Bachelors     → jdindia.com
#   student password reset → mail.jdinstitute.com
#   HR / leave / relieving → jdinstitute.edu.in
#
# See apps/notifications/sender.py for the resolver. The provider
# (MSG91 / SMTP) split above is orthogonal: it decides the *transport*,
# this decides the *From domain*.
# Whether this host can open outbound SMTP connections. PythonAnywhere
# *free* accounts block all non-HTTP egress, so SMTP (Zoho 465 / Gmail
# 587) can't connect there — set this False on such hosts and the
# dispatcher downgrades SMTP-routed triggers to MSG91 (HTTPS) when a
# template exists, keeping mail flowing. Set True on any host with full
# outbound (local dev, paid PA, a VPS) to use the proper From domains.
EMAIL_SMTP_OUTBOUND_ENABLED = env.bool("EMAIL_SMTP_OUTBOUND_ENABLED", default=True)

EMAIL_DOMAIN_DIPLOMA = env("EMAIL_DOMAIN_DIPLOMA", default="jdinstitute.edu.in")
EMAIL_DOMAIN_DEGREE = env("EMAIL_DOMAIN_DEGREE", default="jdindia.com")
EMAIL_DOMAIN_PORTAL = env("EMAIL_DOMAIN_PORTAL", default="mail.jdinstitute.com")
EMAIL_DOMAIN_HR = env("EMAIL_DOMAIN_HR", default="jdinstitute.edu.in")

# trigger template_key → routing token. COURSE = pick diploma/degree by
# course type; PORTAL / HR = fixed domain; any other value = literal
# domain. Triggers absent here keep the provider's default From.
EMAIL_SENDER_DOMAIN_POLICY = {
    # Fees + admission, to students/parents — domain by course type.
    "lead.fee_link.email":                "COURSE",
    "lead.application_link.email":         "COURSE",
    "fees.receipt.email":                 "COURSE",
    "fees.application_fee_receipt.email":  "COURSE",
    "admissions.form_submitted.email":     "COURSE",  # "admission form filled"
    "fees.installment_undertaking.email":  "COURSE",  # installment pattern / undertaking
    "fees.installment_pending.email":      "COURSE",  # installment-pending reminder
    # Student credentials / password reset → mail.jdinstitute.com.
    "student.portal_credentials.email":    "PORTAL",
    # HR / leave / relieving workflows → jdinstitute.edu.in.
    "leaves.application_employee.email":          "HR",
    "leaves.application_status_employee.email":   "HR",
    "leaves.application_status_student.email":    "HR",
    "hr.relieving.application.email":             "HR",
    "hr.relieving.application_rejected.email":     "HR",
    "hr.relieving.experience_letter.email":        "HR",
    "hr.relieving.letter.email":                   "HR",
}

# From-address to use for each sending domain. ONLY list domains that
# are actually verified with the transport (MSG91 cross-checks the From
# domain against its registered senders; SMTP must be authorised to send
# as the address). Domains absent here resolve to a blank From and the
# dispatcher falls back to the provider default — so the routing policy
# above can ship before jdinstitute.edu.in / jdindia.com are verified on
# MSG91. Add the verified From-address here to make a domain live.
EMAIL_SENDER_BY_DOMAIN = {
    "mail.jdinstitute.com": env(
        "SENDER_MAIL_JDINSTITUTE", default="admin@mail.jdinstitute.com",
    ),
    # Pending MSG91 domain verification — set the env var to go live:
    "jdinstitute.edu.in": env("SENDER_JDINSTITUTE_EDU", default=""),
    "jdindia.com":        env("SENDER_JDINDIA", default=""),
}

# Per-domain dedicated SMTP servers. Some sending domains (e.g.
# jdindia.com) deliver through their *own* mailbox/host rather than
# MSG91 or the default internal Gmail relay. When a trigger resolves
# (via EMAIL_SENDER_DOMAIN_POLICY) to a domain listed here, the
# dispatcher opens a dedicated SMTP connection with these credentials —
# this TAKES PRECEDENCE over the MSG91 registry for that domain.
#
# A domain is only active when its *_HOST env var is set; until then the
# entry is omitted and routing falls back to MSG91 / default SMTP.
EMAIL_SMTP_BY_DOMAIN = {}
_jdindia_smtp_host = env("SMTP_JDINDIA_HOST", default="")
if _jdindia_smtp_host:
    _jdindia_user = env("SMTP_JDINDIA_USER", default="")
    EMAIL_SMTP_BY_DOMAIN["jdindia.com"] = {
        "host": _jdindia_smtp_host,
        "port": env.int("SMTP_JDINDIA_PORT", default=587),
        "username": _jdindia_user,
        "password": env("SMTP_JDINDIA_PASSWORD", default=""),
        "use_tls": env.bool("SMTP_JDINDIA_USE_TLS", default=True),
        "use_ssl": env.bool("SMTP_JDINDIA_USE_SSL", default=False),
        # From-address recipients see; defaults to the auth username.
        "from_email": env("SMTP_JDINDIA_FROM", default=_jdindia_user),
    }

# Department / role group inboxes used as additional recipients or CC on
# certain triggers (spec: fee receipt → +Accounts, admission filled →
# +Operations, relieving → Ops/Principal/VP/Academic Manager). Blank =
# not wired; the caller skips that recipient rather than erroring.
ACCOUNTS_INBOX = env("ACCOUNTS_INBOX", default="")
OPERATIONS_INBOX = env("OPERATIONS_INBOX", default="")
PRINCIPAL_INBOX = env("PRINCIPAL_INBOX", default="")
VICE_PRINCIPAL_INBOX = env("VICE_PRINCIPAL_INBOX", default="")
ACADEMIC_MANAGER_INBOX = env("ACADEMIC_MANAGER_INBOX", default="")

# Templates that *intentionally* route through SMTP — listed here so
# the dispatcher logs a warning if someone tries to add them to
# MSG91_EMAIL_TEMPLATES by mistake. Keep in sync with the policy above.
SMTP_INTERNAL_TEMPLATE_KEYS = {
    "leaves.application_employee.email",
    "leaves.application_status_employee.email",
    "hr.relieving.application.email",
    "hr.relieving.application_rejected.email",
    "hr.relieving.experience_letter.email",
    "hr.relieving.letter.email",
    "tasks.assigned.email",
    "tasks.completed.email",
    "account.password_reset_by_admin.email",
}


# --- Email — Django built-in -------------------------------------------

# Default to console backend so dev works with no SMTP. Override per env:
#   EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
#   EMAIL_HOST=smtp.gmail.com  EMAIL_PORT=587  EMAIL_USE_TLS=True
#   EMAIL_HOST_USER=…  EMAIL_HOST_PASSWORD=…
EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=25)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=False)
DEFAULT_FROM_EMAIL = env(
    "DEFAULT_FROM_EMAIL",
    default="JD Communications <admin.a@jdinstitute.edu.in>",
)
# Display name applied when DEFAULT_FROM_EMAIL is just a bare address
# or only EMAIL_HOST_USER is configured. Keeps the recipient from
# seeing "admin.a" auto-derived from the email's local-part.
DEFAULT_FROM_NAME = env("DEFAULT_FROM_NAME", default="JD Communications")


# --- django-axes --------------------------------------------------------

AXES_FAILURE_LIMIT = env.int("AXES_FAILURE_LIMIT", default=5)
AXES_COOLOFF_TIME = timedelta(minutes=env.int("AXES_COOLOFF_MINUTES", default=15))
AXES_LOCKOUT_PARAMETERS = ["ip_address", "username"]
AXES_RESET_ON_SUCCESS = True
AXES_ENABLE_ADMIN = False


# --- Sessions (admin UI; API uses JWT) ----------------------------------

SESSION_COOKIE_AGE = 45 * 60
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True


# --- Production hardening (active when DEBUG=False) ---------------------

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"


# --- I18N / TZ ----------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


# --- Static -------------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Per-request body cap; per-file caps belong in serializers.
DATA_UPLOAD_MAX_MEMORY_SIZE = 60 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
