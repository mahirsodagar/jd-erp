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
    "apps.portal",
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


# --- SMS — Bulk SMS Gateway India --------------------------------------

# https://www.bulksmsgateway.in — DLT-compliant transactional SMS.
# Templates MUST be pre-registered with TRAI/DLT operators; the keys
# below map our notification template_keys to the registered IDs.
BULK_SMS_USER = env("BULK_SMS_USER", default="")
BULK_SMS_PASSWORD = env("BULK_SMS_PASSWORD", default="")
BULK_SMS_SENDER = env("BULK_SMS_SENDER", default="JDEDUC")
BULK_SMS_TEMPLATE_IDS = {
    "lead.application_link.sms": env(
        "DLT_TPL_APPLICATION_LINK", default="1307167852052800815",
    ),
    "lead.fee_link.sms": env(
        "DLT_TPL_FEE_LINK", default="1307168958796572350",
    ),
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
