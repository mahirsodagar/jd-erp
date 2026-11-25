"""Django settings for the jd-erp project (single-tenant)."""

import sys
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
    "apps.payments",
    "apps.communications",
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
        # Website Forminator webhook — per IP; one WordPress server posts
        # every form, so this must cover a busy campaign day.
        "website_webhook": env("THROTTLE_WEBSITE_WEBHOOK", default="2000/hour"),
    },
}

# The general buckets are keyed on user pk / IP, which every test reuses
# (rolled-back rows hand out the same pk again) while the LocMem cache
# keeps counting — so the suite as a whole tripped 100/min and failed
# order-dependently with 429s. Lift only those two buckets under test.
if len(sys.argv) > 1 and sys.argv[1] == "test":
    REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"].update(
        user="100000/min", anon="100000/min",
    )

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
# The web app reads the server-chosen download filename (public receipt
# page has no payer name of its own); browsers hide the header otherwise.
CORS_EXPOSE_HEADERS = ["Content-Disposition"]
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

# --- Application-fee payment instructions ------------------------------

# Per-institute UPI / bank-account details rendered on the manual-payment
# page (`/api/public/pay/manual/<INSTITUTE>/`, with a generated UPI QR)
# that fee links point at when the fee has no online route. Override via
# env vars (JSON) when prod values land. Each entry: vpa, payee_name,
# ac_name, ac_no, ifsc, bank, branch, default_amount.
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


# --- HDFC SmartGateway payment gateway ----------------------------------

# Master switch. While False the fee-link flow sends our manual-payment
# page (UPI QR + bank instructions) instead, so a half-configured
# environment degrades instead of breaking. Turn on per-environment once
# the credentials below are filled AND the webhook is registered in the
# SmartGateway dashboard.
SMARTGATEWAY_ENABLED = env.bool("SMARTGATEWAY_ENABLED", default=False)

# Sandbox (smartgateway.hdfcuat.bank.in) vs production
# (smartgateway.hdfc.bank.in). Kept separate from the enable flag so a
# staging box can run the real flow against the UAT bank.
SMARTGATEWAY_SANDBOX = env.bool("SMARTGATEWAY_SANDBOX", default=True)
# Only set this to point at a mock; normally the sandbox flag decides.
SMARTGATEWAY_BASE_URL = env("SMARTGATEWAY_BASE_URL", default="")

# From the HDFC SmartGateway dashboard. The API key is sent as HTTP Basic
# with the key as username and an empty password.
SMARTGATEWAY_API_KEY = env("SMARTGATEWAY_API_KEY", default="")
# Provided by the bank; goes out as the x-merchantid header.
SMARTGATEWAY_MERCHANT_ID = env("SMARTGATEWAY_MERCHANT_ID", default="")
# payment_page_client_id: "hdfcmaster" on sandbox, your merchant id in
# production.
SMARTGATEWAY_CLIENT_ID = env("SMARTGATEWAY_CLIENT_ID", default="hdfcmaster")
# x-resellerid. Usually "hdfc_reseller"; blank omits the header.
SMARTGATEWAY_RESELLER_ID = env("SMARTGATEWAY_RESELLER_ID", default="")

# RESPONSE_KEY from the dashboard config — a THIRD secret, distinct from
# the API key and the webhook credentials. SmartGateway signs the
# return_url parameters with it (HMAC-SHA256), which is what lets us
# trust the redirect the payer's browser comes back on.
SMARTGATEWAY_RESPONSE_KEY = env("SMARTGATEWAY_RESPONSE_KEY", default="")

SMARTGATEWAY_TIMEOUT = env.int("SMARTGATEWAY_TIMEOUT", default=20)

# Webhook credentials — the username/password pair configured under
# Webhooks in the SmartGateway dashboard, which the bank replays to us as
# an ordinary Basic auth header. Unrelated to SMARTGATEWAY_API_KEY.
# Without both, every delivery is rejected with a 401.
SMARTGATEWAY_WEBHOOK_USERNAME = env(
    "SMARTGATEWAY_WEBHOOK_USERNAME", default="",
)
SMARTGATEWAY_WEBHOOK_PASSWORD = env(
    "SMARTGATEWAY_WEBHOOK_PASSWORD", default="",
)

# SmartGateway does not sign webhook bodies — the shared credentials are
# the whole of the authentication. So by default a webhook is treated as
# a nudge and the order is re-read from /orders/{id} before anything is
# marked paid. Only turn this on if you accept that anyone holding the
# webhook credentials can assert a payment.
SMARTGATEWAY_TRUST_WEBHOOK_PAYLOAD = env.bool(
    "SMARTGATEWAY_TRUST_WEBHOOK_PAYLOAD", default=False,
)

# Public origin of THIS API, as the bank's servers and the student's
# phone reach it. The pay link and the return_url are built off it, and
# SmartGateway requires return_url to be a reachable HTTPS endpoint — so
# this cannot be localhost in any environment that actually takes money.
SMARTGATEWAY_PUBLIC_BASE_URL = env(
    "SMARTGATEWAY_PUBLIC_BASE_URL", default="",
)

# Send the application-form link automatically the moment the fee is
# paid, instead of waiting for a counsellor to click "Send application
# link". Off by default: it messages a real lead with no human in the
# loop.
SMARTGATEWAY_AUTOSEND_APPLICATION_LINK = env.bool(
    "SMARTGATEWAY_AUTOSEND_APPLICATION_LINK", default=False,
)

# Settlement accounts (see apps/payments/routing.py for which fee goes
# where). Each account reads SMARTGATEWAY_<ACCOUNT>_<FIELD>; any blank
# field falls back to the shared SMARTGATEWAY_<FIELD> above. So:
#
#   * HDFC issues separate merchants → set each account's API_KEY,
#     MERCHANT_ID, CLIENT_ID, RESPONSE_KEY, WEBHOOK_USERNAME/PASSWORD.
#   * HDFC keeps one merchant with extra TIDs → set only each account's
#     GATEWAY_REFERENCE_ID, exactly as mapped in PG Control Centre.
#
# An account takes no payments until SMARTGATEWAY_<ACCOUNT>_LIVE=True —
# set it only once HDFC has confirmed that config settles into that bank
# account. Otherwise the shared fallback would quietly pay (say) Trust
# fees into the JDIFT account.
SMARTGATEWAY_ACCOUNTS = {
    account: {
        "live": env.bool(f"SMARTGATEWAY_{account}_LIVE", default=False),
        **{
            field: env(f"SMARTGATEWAY_{account}_{field.upper()}", default="")
            for field in (
                "api_key", "merchant_id", "client_id", "reseller_id",
                "response_key", "webhook_username", "webhook_password",
                "gateway_reference_id",
            )
        },
    }
    for account in ("JDSD_TRUST", "JDIFT_MAIN", "JDIFT_ROYALTY")
}


# --- Razorpay (Payment Links) -------------------------------------------
# Routed to by apps/payments/routing.py — only JDIFT's registration fee
# (Royalty account); JDIFT_MAIN is kept configurable but nothing routes
# to it since 2026-10-26. Reuses
# SMARTGATEWAY_PUBLIC_BASE_URL (the public origin of this API) for the pay
# link and callback_url. Keys from Dashboard → Account & Settings → API
# keys; rzp_test_… keys run the whole flow in test mode.
RAZORPAY_ENABLED = env.bool("RAZORPAY_ENABLED", default=False)
# Shared fallback keys — blank per-account fields below fall back to these.
RAZORPAY_KEY_ID = env("RAZORPAY_KEY_ID", default="")
RAZORPAY_KEY_SECRET = env("RAZORPAY_KEY_SECRET", default="")
# The secret typed when creating the webhook in the dashboard (URL
# <public base>/api/public/razorpay/webhook/, events payment_link.*).
# Distinct from the key secret. Blank = every webhook is rejected, and
# payments settle only via the callback redirect or the reconcile command.
RAZORPAY_WEBHOOK_SECRET = env("RAZORPAY_WEBHOOK_SECRET", default="")

# Settlement accounts. A Razorpay merchant pays out to one bank account,
# so Royalty and JDIFT main are two merchants with two key pairs, read
# from RAZORPAY_<ACCOUNT>_<FIELD>. Both point their webhook at the same
# URL, each with its own secret. An account takes no payments until
# RAZORPAY_<ACCOUNT>_LIVE=True — set it only after a live test payment
# has landed in the right bank account.
RAZORPAY_ACCOUNTS = {
    account: {
        "live": env.bool(f"RAZORPAY_{account}_LIVE", default=False),
        **{
            field: env(f"RAZORPAY_{account}_{field.upper()}", default="")
            for field in ("key_id", "key_secret", "webhook_secret")
        },
    }
    for account in ("JDIFT_ROYALTY", "JDIFT_MAIN")
}
# How long a minted link stays payable. A fresh one is minted (and the old
# one cancelled) when the lead opens our pay link after this.
RAZORPAY_LINK_EXPIRY_MINUTES = env.int("RAZORPAY_LINK_EXPIRY_MINUTES", default=1440)
RAZORPAY_TIMEOUT = env.int("RAZORPAY_TIMEOUT", default=20)

# Institutes whose applicants get the "Pay fees" page right after
# submitting the application form. Empty (the default since the client's
# 2026-11-03 rule) means every institute: the registration fee is payable
# for all, course and other fees only where the route table names a
# gateway (JDSD). A row is payable only when the fee template carries an
# amount and the routed gateway is on for this environment. See
# apps/payments/applicant_fees.py.
REGISTRATION_FEE_AT_APPLICATION_INSTITUTES = env.list(
    "REGISTRATION_FEE_AT_APPLICATION_INSTITUTES", default=[],
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

# Only used when SMS_PROVIDER=msg91 (default is bulksms). Authkey from
# the MSG91 dashboard → Authkeys → "SMS" row. MSG91 email is gone
# (2026-11-18, ZeptoMail) — there is no shared MSG91_AUTHKEY any more.
MSG91_SMS_AUTHKEY = env("MSG91_SMS_AUTHKEY", default="")
MSG91_SMS_SENDER_ID = env("MSG91_SMS_SENDER_ID", default="JDEDUC")
# Network timeout (seconds) for the MSG91 SMS API.
MSG91_TIMEOUT = env.int("MSG91_TIMEOUT", default=10)

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


# --- Email — ZeptoMail SMTP (the ONLY outbound mail transport) --------
#
# Since 2026-11-18 every outgoing email (enquiry mail, automated
# notifications, bulk campaigns, PDFs) leaves through ZeptoMail's SMTP
# relay, authenticated with the ZeptoMail send-mail token. The From
# address is ALWAYS `no-reply@dkul.in` (the client's verified ZeptoMail
# domain). Credentials of jdindia.com, jdinstitute.com,
# jdinstitute.edu.in or any other mailbox must never be used here — not
# for SMTP auth and not as the From. Those addresses survive only as
# recipient inboxes and as Reply-To (see EMAIL_REPLY_TO_POLICY below).
#
# Who answers a reply is decided per trigger: the From stays no-reply,
# the Reply-To header is set to the person/department that handles that
# kind of mail (apps.notifications.reply_to.resolve_reply_to).
#
# Configuration lives in the Django EMAIL_* settings, so every code
# path — the notifications dispatcher, direct EmailMessage senders,
# Django's own password-reset mail — goes through the same relay.
# The transport settings themselves (EMAIL_HOST…, DEFAULT_FROM_EMAIL,
# EMAIL_DEFAULT_REPLY_TO, EMAIL_REPLY_TO_POLICY) are further down,
# after the inbox maps they refer to.

# Faculty + admin daily reports freeze month-wise: month M locks on the
# 1st of M+1 plus this many grace days (0 = strictly month-wise). A
# frozen month is edited only via an approved + granted access request
# (apps.audit_reports.freeze).
DAILY_REPORT_FREEZE_GRACE_DAYS = env.int("DAILY_REPORT_FREEZE_GRACE_DAYS", default=0)

# Department / role group inboxes used as additional recipients or CC on
# certain triggers (spec: fee receipt → +Accounts, admission filled →
# +Operations, relieving → Ops/Principal/VP/Academic Manager). Blank =
# not wired; the caller skips that recipient rather than erroring.
# Client 2026-11-20: Accounts and Operations are the same operations
# mailbox.
ACCOUNTS_INBOX = env("ACCOUNTS_INBOX", default="operations@jdinstitute.edu.in")
OPERATIONS_INBOX = env("OPERATIONS_INBOX", default="operations@jdinstitute.edu.in")
# The Principal is NOT a fixed mailbox (client 2026-11-20): it is the
# active employee holding the PRINCIPAL_DESIGNATION designation at the
# campus of the mail's context (apps.notifications.reply_to, token
# PRINCIPAL). PRINCIPAL_INBOX is only the fallback when that campus has
# no such employee.
PRINCIPAL_DESIGNATION = env("PRINCIPAL_DESIGNATION", default="Principal")
# Designation names (case-insensitive, exact) that count as teaching
# staff for the timetable's Faculty pickers (`/api/employees/?teaching=1`).
# Client 2026-11-21: only "Faculty". Add e.g. "Assistant Professor" or
# "Visiting Faculty" here if those must be schedulable too.
# Designations whose employees are teaching staff BY DEFAULT: migration
# employees.0013 ticks `Employee.is_teaching` for them and a new hire with
# one of these designations gets the flag on create. The pickers
# themselves filter on the flag, which HR can set for anyone (an HOD who
# also teaches) — since 2026-11-25 this list no longer limits pickers.
TIMETABLE_FACULTY_DESIGNATIONS = env.list(
    "TIMETABLE_FACULTY_DESIGNATIONS", default=["Faculty"],
)
PRINCIPAL_INBOX = env("PRINCIPAL_INBOX", default="")
VICE_PRINCIPAL_INBOX = env("VICE_PRINCIPAL_INBOX", default="")
ACADEMIC_MANAGER_INBOX = env("ACADEMIC_MANAGER_INBOX", default="")

# Campus-wise CC inboxes (client list, 2026-11-20). Each map is keyed
# on `Campus.code` (BLR, GOA, COK, VJY, HYD); the matching inbox is put
# in CC of every mail sent for that purpose, and doubles as Reply-To
# through EMAIL_REPLY_TO_POLICY. A campus absent / blank here gets no
# campus copy (the primary recipient still gets the mail). Override per
# env. All five campuses are covered for all four purposes.

# Purpose: Fee Receipts — receipt PDF to the student, campus in CC.
FEE_RECEIPT_CAMPUS_INBOXES = {
    "BLR": env("FEE_RECEIPT_INBOX_BLR", default="dkul.receipts@jdinstitute.edu.in"),
    "GOA": env("FEE_RECEIPT_INBOX_GOA", default="dkul.goareceipts@jdinstitute.edu.in"),
    "COK": env("FEE_RECEIPT_INBOX_COK", default="dkul.cochinreceipts@jdinstitute.edu.in"),
    "VJY": env("FEE_RECEIPT_INBOX_VJY", default="dkul.vijaywadareceipts@jdinstitute.edu.in"),
    "HYD": env("FEE_RECEIPT_INBOX_HYD", default="dkul.hyderabadreceipts@jdinstitute.edu.in"),
}

# Purpose: Acknowledgement — application form PDF (office copy) to the
# campus acknowledgement inbox; student copy replies there too.
APPLICATION_ACK_CAMPUS_INBOXES = {
    "BLR": env("APPLICATION_ACK_INBOX_BLR",
               default="acknowledgement.bengaluru@jdinstitute.edu.in"),
    "GOA": env("APPLICATION_ACK_INBOX_GOA",
               default="acknowledgement.goa@jdinstitute.edu.in"),
    "COK": env("APPLICATION_ACK_INBOX_COK",
               default="acknowledgement.cochin@jdinstitute.edu.in"),
    "VJY": env("APPLICATION_ACK_INBOX_VJY",
               default="acknowledgement.vijaywada@jdinstitute.edu.in"),
    "HYD": env("APPLICATION_ACK_INBOX_HYD",
               default="acknowledgement.hyderabad@jdinstitute.edu.in"),
}

# Purpose: Admissions / counselling — the campus admissions inbox that
# handles replies to lead & CRM mail (application / fee / exam links,
# welcome, drips…) when the lead has no counsellor (client list,
# 2026-11-21). A campus left blank here falls back to its
# acknowledgement inbox above. Bengaluru was not on the client's list.
ADMISSIONS_CAMPUS_INBOXES = {
    "BLR": env("ADMISSIONS_INBOX_BLR", default=""),
    "GOA": env("ADMISSIONS_INBOX_GOA", default="goa@jdinstitute.edu.in"),
    "COK": env("ADMISSIONS_INBOX_COK",
               default="marketing.cochin@jdinstitute.edu.in"),
    "VJY": env("ADMISSIONS_INBOX_VJY", default="vijayawada@jdinstitute.edu.in"),
    "HYD": env("ADMISSIONS_INBOX_HYD", default="hyderabad@jdinstitute.edu.in"),
}

# Purpose: Leaves — student leave mail (applied → mentor, approved →
# student) and employee leave / comp-off mail CC the leave inbox of the
# student's / employee's campus. LEAVES_HR_INBOX (further up) is the
# fallback for a campus not listed here.
LEAVE_CAMPUS_INBOXES = {
    "BLR": env("LEAVE_INBOX_BLR", default="leave@jdinstitute.edu.in"),
    "GOA": env("LEAVE_INBOX_GOA", default="leave.goa@jdinstitute.edu.in"),
    "COK": env("LEAVE_INBOX_COK", default="leave.cochin@jdinstitute.edu.in"),
    "VJY": env("LEAVE_INBOX_VJY", default="leave.vijaywada@jdinstitute.edu.in"),
    "HYD": env("LEAVE_INBOX_HYD", default="leave.hyderabad@jdinstitute.edu.in"),
}

# Purpose: Fee Payment Schedule (undertaking) — the schedule PDF (sent
# by staff from the enrollment) to the student with the campus
# undertaking inbox in CC.
UNDERTAKING_CAMPUS_INBOXES = {
    "BLR": env("UNDERTAKING_INBOX_BLR",
               default="undertaking.bangalore@jdinstitute.edu.in"),
    "GOA": env("UNDERTAKING_INBOX_GOA",
               default="undertaking.goa@jdinstitute.edu.in"),
    "COK": env("UNDERTAKING_INBOX_COK",
               default="undertaking.cochin@jdinstitute.edu.in"),
    "VJY": env("UNDERTAKING_INBOX_VJY",
               default="undertaking.vijaywada@jdinstitute.edu.in"),
    "HYD": env("UNDERTAKING_INBOX_HYD",
               default="undertaking.hyderabad@jdinstitute.edu.in"),
}

# Relieving approval chain: L1–L4 per institute live in the Relieving
# Managers master (HR → Relieving Managers), not here. These two are
# read ONLY by migration relieving.0003 to pre-fill L3 / L4 from the
# old fixed approvers on an existing deployment; safe to drop from .env
# once that migration has run.
RELIEVING_L3_APPROVER_EMAIL = env(
    "RELIEVING_L3_APPROVER_EMAIL", default="principal@jdinstitute.edu.in",
)
RELIEVING_L4_APPROVER_EMAIL = env("RELIEVING_L4_APPROVER_EMAIL", default="")
# Signatory printed under the signature on relieving / experience letters.
RELIEVING_LETTER_SIGNATORY = env(
    "RELIEVING_LETTER_SIGNATORY", default="TRUPTI DESHPANDE",
)
RELIEVING_LETTER_SIGNATORY_TITLE = env(
    "RELIEVING_LETTER_SIGNATORY_TITLE", default="HR",
)

# ZeptoMail SMTP relay. Host/port/user are fixed by ZeptoMail; only the
# token differs per Mail Agent. Prod .env needs exactly:
#   ZEPTOMAIL_SMTP_TOKEN=<token from ZeptoMail → Mail Agent → SMTP>
# (EMAIL_HOST_PASSWORD is accepted as an alias.) Everything else below
# may stay at its default.
EMAIL_BACKEND = env(
    "EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = env("EMAIL_HOST", default="smtp.zeptomail.in")
# 465 = implicit SSL (the setup that already works from the VPS);
# 587 + EMAIL_USE_TLS=True / EMAIL_USE_SSL=False also works.
EMAIL_PORT = env.int("EMAIL_PORT", default=465)
EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=True)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="emailapikey")
EMAIL_HOST_PASSWORD = env(
    "ZEPTOMAIL_SMTP_TOKEN", default=env("EMAIL_HOST_PASSWORD", default=""),
)
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=30)

# The one and only From. ZeptoMail rejects any From whose domain is not
# verified under the Mail Agent, so this must stay on dkul.in.
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="no-reply@dkul.in")
# Display name wrapped around DEFAULT_FROM_EMAIL when it is a bare
# address — recipients see "JD Institute <no-reply@dkul.in>".
DEFAULT_FROM_NAME = env("DEFAULT_FROM_NAME", default="JD Institute")
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# Reply-To fallback for every mail with no specific handler (client
# decision 2026-11-20: webmaster@dkul.in; replaced the interim
# admin.a@jdinstitute.edu.in). Overridable via env.
EMAIL_DEFAULT_REPLY_TO = env(
    "EMAIL_DEFAULT_REPLY_TO", default="webmaster@dkul.in",
)

# trigger template_key → who handles replies. Values are either a
# literal address or one of these tokens (resolved against the inbox
# settings + the send context):
#   HR_LEAVE            → LEAVE_CAMPUS_INBOXES[context.campus_code],
#                         else LEAVES_HR_INBOX (leave / comp-off dept.)
#   CAMPUS_RECEIPTS     → FEE_RECEIPT_CAMPUS_INBOXES[context.campus_code]
#   CAMPUS_LEADS        → ADMISSIONS_CAMPUS_INBOXES[context.campus_code],
#                         else APPLICATION_ACK_CAMPUS_INBOXES[...] (lead/CRM)
#   CAMPUS_ADMISSIONS   → APPLICATION_ACK_CAMPUS_INBOXES[context.campus_code]
#   CAMPUS_UNDERTAKING  → UNDERTAKING_CAMPUS_INBOXES[context.campus_code]
#   PRINCIPAL           → active employee with the Principal designation
#                         at context.campus_code, else PRINCIPAL_INBOX
#   ACCOUNTS            → ACCOUNTS_INBOX
#   CONTEXT             → context["reply_to"] only (no static fallback)
# A caller can always pass `reply_to` in the context (counsellor,
# manager, faculty, mentor…) — that wins over this table. Anything that
# resolves blank falls back to EMAIL_DEFAULT_REPLY_TO.
EMAIL_REPLY_TO_POLICY = {
    # Leads / CRM — the assigned counsellor (passed in context by
    # apps/leads/send_links.py); campus admissions inbox
    # (ADMISSIONS_CAMPUS_INBOXES, else the ack inbox) otherwise.
    "lead.application_link.email":   "CAMPUS_LEADS",
    "lead.fee_link.email":           "CAMPUS_LEADS",
    "lead.entrance_exam_link.email": "CAMPUS_LEADS",
    "lead.welcome.email":            "CAMPUS_LEADS",
    "lead.inactive.email":           "CAMPUS_LEADS",
    "lead.non_responsive.email":     "CAMPUS_LEADS",
    "lead_welcome_email":            "CAMPUS_LEADS",
    "hot_why_join_jd":               "CAMPUS_LEADS",
    "campus_visit_confirmation":     "CAMPUS_LEADS",
    "post_visit_thanks":             "CAMPUS_LEADS",
    "not_answered_closing_soon":     "CAMPUS_LEADS",
    "cold_drip_30":                  "CAMPUS_LEADS",
    "cold_drip_60":                  "CAMPUS_LEADS",
    "cold_drip_90":                  "CAMPUS_LEADS",
    "enrolled_confirmation":         "CAMPUS_LEADS",
    "manager_overdue_hot_lead":      "CAMPUS_LEADS",

    # Admissions — application ack / office copy / undertaking.
    "admissions.application_submitted.email": "CAMPUS_ADMISSIONS",
    "admissions.form_submitted.email":        "CAMPUS_ADMISSIONS",
    "admissions.undertaking.email":           "CAMPUS_UNDERTAKING",
    "fees.installment_undertaking.email":     "CAMPUS_UNDERTAKING",

    # Fees — campus receipts inbox (accounts).
    "fees.receipt.email":                 "CAMPUS_RECEIPTS",
    "fees.application_fee_receipt.email": "CAMPUS_RECEIPTS",
    "fees.fee_link.email":                "CAMPUS_RECEIPTS",
    "fees.installment_pending.email":     "CAMPUS_RECEIPTS",

    # Employee leave / comp-off → the leave department.
    "leaves.application_employee.email":         "HR_LEAVE",
    "leaves.application_status_employee.email":  "HR_LEAVE",
    "leaves.compoff_application_employee.email": "HR_LEAVE",
    "leaves.compoff_status_employee.email":      "HR_LEAVE",

    # Relieving — the approver handling the application is passed in
    # context by apps/relieving/notifications.py; Principal otherwise.
    "hr.relieving.application.email":          "PRINCIPAL",
    "hr.relieving.application_rejected.email": "PRINCIPAL",
    "hr.relieving.application_approved.email": "PRINCIPAL",
    "hr.relieving.experience_letter.email":    "PRINCIPAL",
    "hr.relieving.letter.email":               "PRINCIPAL",

    # Student leave / assignments / attendance: mentor, faculty or
    # student passed in context by the caller; default inbox otherwise.
    "student_leaves.applied.email":          "CONTEXT",
    "student_leaves.accepted.email":         "CONTEXT",
    "leaves.application_status_student.email": "CONTEXT",
    "academics.assignment_assigned.email":   "CONTEXT",
    "academics.assignment_submitted.email":  "CONTEXT",
    "student_absent_email":                  "CONTEXT",
    "parent_absent_email":                   "CONTEXT",

    # Account mails (portal credentials, admin reset) and certificates
    # intentionally have no handler — they use EMAIL_DEFAULT_REPLY_TO.
}


# --- django-axes --------------------------------------------------------

AXES_FAILURE_LIMIT = env.int("AXES_FAILURE_LIMIT", default=5)
AXES_COOLOFF_TIME = timedelta(minutes=env.int("AXES_COOLOFF_MINUTES", default=15))
# Lock on the COMBINATION of username AND ip_address (nested list = AND),
# not each independently. Behind nginx every request's REMOTE_ADDR is the
# proxy's 127.0.0.1, so a flat ["ip_address", "username"] (OR) meant 5
# failures from ANY users locked out the shared 127.0.0.1 — i.e. everyone.
# Keyed on the pair, one user's failures only lock that user.
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
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
