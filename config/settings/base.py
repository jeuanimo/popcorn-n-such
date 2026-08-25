import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY must be set via environment variables.")

DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "django_celery_beat",
]

LOCAL_APPS = [
    "accounts",
    "core",
    "products",
    "inventory",
    "supplies",
    "suppliers",
    "purchase_orders",
    "cart",
    "orders",
    "payments",
    "coupons",
    "taxes",
    "shipping",
    "fulfillment",
    "fundraisers",
    "teams",
    "sellers",
    "organizations",
    "customers",
    "crm",
    "notifications",
    "sharing",
    "abandoned_carts",
    "leaderboards",
    "reports",
    "dashboards",
    "security_audit",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

AUTHENTICATION_BACKENDS = [
    "accounts.backends.ThrottledModelBackend",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Content-Security-Policy. Report-only until CSP_ENFORCE=true; see core/csp.py.
    "core.csp.ContentSecurityPolicyMiddleware",
]

# Start in report-only so a missing Poynt origin cannot break checkout on deploy.
CSP_ENFORCE = env_bool("CSP_ENFORCE", False)
CSP_EXTRA_ORIGINS = env_list("CSP_EXTRA_ORIGINS", "")

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.branding",
                "core.context_processors.staff_nav",
                "core.context_processors.cart_item_count",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        ssl_require=env_bool("DB_SSL_REQUIRE", False),
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "home"

LOGIN_THROTTLE_LIMIT = int(os.getenv("LOGIN_THROTTLE_LIMIT", "5"))
LOGIN_THROTTLE_WINDOW_SECONDS = int(os.getenv("LOGIN_THROTTLE_WINDOW_SECONDS", "900"))
REQUIRE_EMAIL_VERIFICATION = env_bool("REQUIRE_EMAIL_VERIFICATION", False)
MFA_REQUIRED_ROLES = env_list("MFA_REQUIRED_ROLES", "staff,admin")
ALLOWED_REMOTE_IMAGE_HOSTS = env_list("ALLOWED_REMOTE_IMAGE_HOSTS", "")

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
REFERRER_POLICY = "strict-origin-when-cross-origin"
DATA_UPLOAD_MAX_MEMORY_SIZE = 2_097_152  # 2 MB — reject oversized POST bodies before they hit views
DATA_UPLOAD_MAX_NUMBER_FIELDS = 500       # guard against hash-flood attacks on form parsing

# -----------------------------------------------------------------------------
# Payments — GoDaddy Payments via the Poynt Commerce Platform
# -----------------------------------------------------------------------------
# Active gateway slug: godaddy | stripe | paypal
PAYMENTS_PROVIDER = os.getenv("PAYMENTS_PROVIDER", "godaddy")
PAYMENTS_WEBHOOK_SECRET = os.getenv("PAYMENTS_WEBHOOK_SECRET", "")
GODADDY_PAYMENTS_WEBHOOK_SECRET = os.getenv("GODADDY_PAYMENTS_WEBHOOK_SECRET", "")

# --- Poynt environment -------------------------------------------------------
# Selects the API host. Use "st" (staging/OTE) for all development and testing;
# only "prod" touches real money. An explicit GODADDY_POYNT_API_HOST wins.
GODADDY_POYNT_ENV = os.getenv("GODADDY_POYNT_ENV", "ote").strip().lower()

# Verified reachable Aug 2026. Note there is NO services-st.poynt.net — that
# name appears in an old SDK host map but does not resolve in public DNS.
# GoDaddy's staging environment is "OTE".
POYNT_API_HOSTS = {
    "prod": "https://services.poynt.net",
    "production": "https://services.poynt.net",
    "ote": "https://services-ote.poynt.net",
    "staging": "https://services-ote.poynt.net",
    "st": "https://services-ote.poynt.net",
    "ci": "https://services-ci.poynt.net",
    "dev": "https://services-ci.poynt.net",
    "eu": "https://services-eu.poynt.net",
}

# The browser SDK is served from a different host per environment.
POYNT_COLLECT_SDK_URLS = {
    "prod": "https://collect.commerce.godaddy.com/sdk.js",
    "production": "https://collect.commerce.godaddy.com/sdk.js",
    "ote": "https://collect.commerce.ote-godaddy.com/sdk.js",
    "staging": "https://collect.commerce.ote-godaddy.com/sdk.js",
    "st": "https://collect.commerce.ote-godaddy.com/sdk.js",
    "ci": "https://collect.commerce.ote-godaddy.com/sdk.js",
    "dev": "https://collect.commerce.ote-godaddy.com/sdk.js",
    "eu": "https://collect.commerce.godaddy.com/sdk.js",
}

GODADDY_POYNT_API_HOST = (
    os.getenv("GODADDY_POYNT_API_HOST", "").strip().rstrip("/")
    or POYNT_API_HOSTS.get(GODADDY_POYNT_ENV, POYNT_API_HOSTS["ote"])
)
GODADDY_POYNT_IS_PRODUCTION = GODADDY_POYNT_API_HOST == POYNT_API_HOSTS["prod"]

# --- Poynt application credentials -------------------------------------------
# Application ID and Business ID come from the Poynt HQ portal. The private key
# is the PEM half of the RSA keypair issued when the application was registered.
GODADDY_POYNT_APPLICATION_ID = os.getenv("GODADDY_POYNT_APPLICATION_ID", "")
GODADDY_POYNT_BUSINESS_ID = os.getenv("GODADDY_POYNT_BUSINESS_ID", "")
GODADDY_POYNT_STORE_ID = os.getenv("GODADDY_POYNT_STORE_ID", "")

# Supply the key EITHER inline (newlines may be written as literal \n) OR as a
# path to a PEM file mounted outside the repository. Never commit either one.
GODADDY_POYNT_PRIVATE_KEY = os.getenv("GODADDY_POYNT_PRIVATE_KEY", "").replace("\\n", "\n")
GODADDY_POYNT_PRIVATE_KEY_PATH = os.getenv("GODADDY_POYNT_PRIVATE_KEY_PATH", "")

# --- Poynt API behaviour -----------------------------------------------------
GODADDY_POYNT_API_VERSION = os.getenv("GODADDY_POYNT_API_VERSION", "1.2")
GODADDY_POYNT_TIMEOUT_SECONDS = float(os.getenv("GODADDY_POYNT_TIMEOUT_SECONDS", "20"))
# Seconds of headroom before expiry at which a cached access token is renewed.
GODADDY_POYNT_TOKEN_LEEWAY_SECONDS = int(os.getenv("GODADDY_POYNT_TOKEN_LEEWAY_SECONDS", "300"))

# Endpoint paths are PINNED here on purpose. They are deliberately NOT resolved
# through runtime_settings: those are staff-editable at runtime, and letting an
# operator repoint payment traffic at an arbitrary path would be a live exploit.
GODADDY_POYNT_TOKEN_PATH = "/token"
GODADDY_POYNT_TOKENIZE_PATH = "/businesses/{business_id}/cards/tokenize"
GODADDY_POYNT_CHARGE_PATH = "/businesses/{business_id}/cards/tokenize/charge"
GODADDY_POYNT_TRANSACTION_PATH = "/businesses/{business_id}/transactions/{transaction_id}"
GODADDY_POYNT_TRANSACTIONS_PATH = "/businesses/{business_id}/transactions"

# SALE = authorize and capture in one step (normal e-commerce checkout).
# AUTHORIZE = authorize only; requires a later capture call.
GODADDY_PAYMENTS_CHARGE_ACTION = os.getenv("GODADDY_PAYMENTS_CHARGE_ACTION", "SALE").strip().upper()

# --- Poynt Collect (browser SDK) ---------------------------------------------
GODADDY_COLLECT_ENABLED = env_bool("GODADDY_COLLECT_ENABLED", True)
GODADDY_COLLECT_SDK_URL = (
    os.getenv("GODADDY_COLLECT_SDK_URL", "").strip()
    or POYNT_COLLECT_SDK_URLS.get(GODADDY_POYNT_ENV, POYNT_COLLECT_SDK_URLS["ote"])
)
# Business/Application IDs used to initialise the browser SDK. These are safe to
# expose to the page; the private key never is. Default to the server-side IDs.
GODADDY_COLLECT_BUSINESS_ID = os.getenv("GODADDY_COLLECT_BUSINESS_ID", "") or GODADDY_POYNT_BUSINESS_ID
GODADDY_COLLECT_APPLICATION_ID = os.getenv("GODADDY_COLLECT_APPLICATION_ID", "") or GODADDY_POYNT_APPLICATION_ID
GODADDY_COLLECT_APPLICATION_KEY = os.getenv("GODADDY_COLLECT_APPLICATION_KEY", "")
GODADDY_COLLECT_IFRAME_HEIGHT = os.getenv("GODADDY_COLLECT_IFRAME_HEIGHT", "460px")
GODADDY_COLLECT_RECAPTCHA_TYPE = os.getenv("GODADDY_COLLECT_RECAPTCHA_TYPE", "DEFAULT")
GODADDY_COLLECT_RECAPTCHA_TEXT_FONT_SIZE = os.getenv("GODADDY_COLLECT_RECAPTCHA_TEXT_FONT_SIZE", "14px")
GODADDY_COLLECT_RECAPTCHA_TEXT_COLOR = os.getenv("GODADDY_COLLECT_RECAPTCHA_TEXT_COLOR", "#111827")
GODADDY_COLLECT_RECAPTCHA_LINK_COLOR = os.getenv("GODADDY_COLLECT_RECAPTCHA_LINK_COLOR", "#0d6efd")
GODADDY_COLLECT_RECAPTCHA_LINK_TEXT_DECORATION = os.getenv("GODADDY_COLLECT_RECAPTCHA_LINK_TEXT_DECORATION", "underline")

# --- Legacy / hosted-redirect settings (kept for the non-Collect fallback) ----
GODADDY_API_KEY = os.getenv("GODADDY_API_KEY", "")
GODADDY_MERCHANT_ID = os.getenv("GODADDY_MERCHANT_ID", "")
GODADDY_STORE_ID = os.getenv("GODADDY_STORE_ID", "") or GODADDY_POYNT_STORE_ID
GODADDY_PAYMENTS_BASE_URL = os.getenv("GODADDY_PAYMENTS_BASE_URL", "")
GODADDY_PAYMENTS_CREATE_SESSION_PATH = os.getenv("GODADDY_PAYMENTS_CREATE_SESSION_PATH", "/v1/payments/sessions")
GODADDY_PAYMENTS_VERIFY_PATH = os.getenv("GODADDY_PAYMENTS_VERIFY_PATH", "/v1/payments/verify")
GODADDY_PAYMENTS_VERIFY_METHOD = os.getenv("GODADDY_PAYMENTS_VERIFY_METHOD", "POST")
GODADDY_PAYMENTS_REFUND_PATH = os.getenv("GODADDY_PAYMENTS_REFUND_PATH", "/v1/payments/refunds")
GODADDY_PAYMENTS_TIMEOUT_SECONDS = os.getenv("GODADDY_PAYMENTS_TIMEOUT_SECONDS", "15")
GODADDY_PAYMENTS_ALLOWED_REDIRECT_HOSTS = os.getenv("GODADDY_PAYMENTS_ALLOWED_REDIRECT_HOSTS", "")

SHIPPING_PROVIDER = os.getenv("SHIPPING_PROVIDER", "shippo")
TAX_PROVIDER = os.getenv("TAX_PROVIDER", "manual")
TAX_FALLBACK_PROVIDER = os.getenv("TAX_FALLBACK_PROVIDER", "manual")
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "smtp")

# Carrier API keys — set via environment, never hard-code
SHIPPO_API_KEY = os.getenv("SHIPPO_API_KEY", "")
EASYPOST_API_KEY = os.getenv("EASYPOST_API_KEY", "")
USPS_USER_ID = os.getenv("USPS_USER_ID", "")
PITNEY_BOWES_API_KEY = os.getenv("PITNEY_BOWES_API_KEY", "")
PITNEY_BOWES_API_SECRET = os.getenv("PITNEY_BOWES_API_SECRET", "")
PITNEY_BOWES_ENV = os.getenv("PITNEY_BOWES_ENV", "sandbox")
PITNEY_BOWES_BASE_URL_SANDBOX = os.getenv("PITNEY_BOWES_BASE_URL_SANDBOX", "")
PITNEY_BOWES_BASE_URL_PROD = os.getenv("PITNEY_BOWES_BASE_URL_PROD", "")

# USPS modern API credentials (not legacy Web Tools). Fill in when approved.
USPS_CLIENT_ID = os.getenv("USPS_CLIENT_ID", "")
USPS_CLIENT_SECRET = os.getenv("USPS_CLIENT_SECRET", "")
USPS_ENV = os.getenv("USPS_ENV", "sandbox")
USPS_BASE_URL_SANDBOX = os.getenv("USPS_BASE_URL_SANDBOX", "")
USPS_BASE_URL_PROD = os.getenv("USPS_BASE_URL_PROD", "")

# Ship-from address used by admin fulfillment actions and label creation
SHIPPING_FROM_NAME = os.getenv("SHIPPING_FROM_NAME", "Popcorn N Such")
SHIPPING_FROM_ADDRESS_LINE_1 = os.getenv("SHIPPING_FROM_ADDRESS_LINE_1", "")
SHIPPING_FROM_CITY = os.getenv("SHIPPING_FROM_CITY", "")
SHIPPING_FROM_STATE = os.getenv("SHIPPING_FROM_STATE", "")
SHIPPING_FROM_POSTAL_CODE = os.getenv("SHIPPING_FROM_POSTAL_CODE", "")
SHIPPING_FROM_COUNTRY = os.getenv("SHIPPING_FROM_COUNTRY", "US")
SHIPPING_DEFAULT_WEIGHT_OZ = float(os.getenv("SHIPPING_DEFAULT_WEIGHT_OZ", "16"))
SHIPPING_MARKUP_PERCENT = float(os.getenv("SHIPPING_MARKUP_PERCENT", "10"))
SMS_PROVIDER = os.getenv("SMS_PROVIDER", "twilio")
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "http://localhost:8000")

# Safety switch: when false, checkout cannot create orders from stub payment payloads.
ALLOW_STUB_CHECKOUT_PAYMENT = env_bool("ALLOW_STUB_CHECKOUT_PAYMENT", False)

# Manual tax rules for development/fallback. Keys are 2-letter state codes.
MANUAL_TAX_RATES = {}

# Staff notification thresholds
LARGE_ORDER_THRESHOLD_CENTS = int(os.getenv("LARGE_ORDER_THRESHOLD_CENTS", "15000"))

# Purchase order receiving
PURCHASE_ORDER_ALLOW_OVER_RECEIVE = env_bool("PURCHASE_ORDER_ALLOW_OVER_RECEIVE", False)

ABANDONED_CART_ABANDONMENT_MINUTES = int(os.getenv("ABANDONED_CART_ABANDONMENT_MINUTES", "60"))
ABANDONED_CART_EVENT_EXPIRY_HOURS = int(os.getenv("ABANDONED_CART_EVENT_EXPIRY_HOURS", "168"))
ABANDONED_CART_TOKEN_EXPIRY_HOURS = int(os.getenv("ABANDONED_CART_TOKEN_EXPIRY_HOURS", "96"))

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.getenv("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "1025"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", False)
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "no-reply@popcornnsuch.local")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "popcorn-n-such",
    }
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        },
        # Appends order_id / payment_id / transaction_id / status / amount so a
        # payment can be traced end to end without logging anything sensitive.
        "payment": {
            "()": "payments.log_filters.PaymentContextFormatter",
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        },
    },
    "filters": {
        # Backstop that scrubs card numbers, JWTs and private keys from any
        # payment log line that somehow contains one.
        "redact_sensitive": {
            "()": "payments.log_filters.RedactSensitiveFilter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
        "payment_console": {
            "class": "logging.StreamHandler",
            "formatter": "payment",
            "filters": ["redact_sensitive"],
        },
    },
    "root": {
        "handlers": ["console"],
        "level": os.getenv("DJANGO_LOG_LEVEL", "INFO"),
    },
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "security_audit": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        # All payment logging goes through the redacting handler.
        "payments": {
            "handlers": ["payment_console"],
            "level": os.getenv("PAYMENTS_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
    },
}

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------

_redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

CELERY_BROKER_URL = _redis_url
CELERY_RESULT_BACKEND = _redis_url

CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"

# Track task state so the admin and monitoring can show started/running.
CELERY_TASK_TRACK_STARTED = True

# Hard and soft time limits prevent runaway tasks from blocking workers.
CELERY_TASK_TIME_LIMIT = 300        # 5 min — SIGKILL
CELERY_TASK_SOFT_TIME_LIMIT = 240   # 4 min — raises SoftTimeLimitExceeded

# Prevent workers from pre-fetching more tasks than they can handle.
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

# Use the database-backed Beat scheduler so schedules survive restarts
# and can be edited in the Django admin.
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# Default periodic schedule.  Additional entries can be created in the
# Django admin under Periodic Tasks without a deploy.
CELERY_BEAT_SCHEDULE = {
    "process-abandoned-carts": {
        "task": "abandoned_carts.tasks.process_abandoned_carts",
        "schedule": 1800.0,  # every 30 minutes
    },
    # Resolve charges whose outcome we never received. Runs often because an
    # unresolved ambiguous payment means a customer may have been charged for
    # an order that does not exist.
    "reconcile-ambiguous-payments": {
        "task": "payments.tasks.reconcile_ambiguous_payments",
        "schedule": 120.0,  # every 2 minutes
    },
}
