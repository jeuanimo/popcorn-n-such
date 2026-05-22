"""
Production settings for Popcorn N Such.

All secrets come from environment variables — nothing sensitive lives here.
See .env.example for the full list of required and optional variables.
"""
from __future__ import annotations

import os

from . import base as base_settings

for setting_name in dir(base_settings):
    if setting_name.isupper():
        globals()[setting_name] = getattr(base_settings, setting_name)

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

DEBUG = False

if not ALLOWED_HOSTS:  # noqa: F821 — imported from base via loop above
    raise RuntimeError("DJANGO_ALLOWED_HOSTS must be set in production.")

# ---------------------------------------------------------------------------
# HTTPS / security headers
# ---------------------------------------------------------------------------

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14  # 2 weeks

SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 31_536_000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_RESOURCE_POLICY = "same-origin"
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

# ---------------------------------------------------------------------------
# Cache — Redis (required in production)
# ---------------------------------------------------------------------------

_redis_url = os.getenv("REDIS_URL", "")
if _redis_url:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": _redis_url,
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
                "CONNECTION_POOL_KWARGS": {"max_connections": 20},
                "SOCKET_CONNECT_TIMEOUT": 5,
                "SOCKET_TIMEOUT": 5,
            },
            "KEY_PREFIX": "pns",
            "TIMEOUT": 300,
        }
    }
    SESSION_ENGINE = "django.contrib.sessions.backends.cache"
    SESSION_CACHE_ALIAS = "default"

# ---------------------------------------------------------------------------
# Media files — S3 / Cloudflare R2 / DigitalOcean Spaces
# ---------------------------------------------------------------------------

_use_s3 = os.getenv("USE_S3", "").lower() in {"1", "true", "yes"}

if _use_s3:
    # django-storages with boto3 backend
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
            "OPTIONS": {
                "bucket_name": os.getenv("AWS_STORAGE_BUCKET_NAME", ""),
                "region_name": os.getenv("AWS_S3_REGION_NAME", "auto"),
                "endpoint_url": os.getenv("AWS_S3_ENDPOINT_URL", ""),  # set for R2/Spaces
                "access_key": os.getenv("AWS_ACCESS_KEY_ID", ""),
                "secret_key": os.getenv("AWS_SECRET_ACCESS_KEY", ""),
                "file_overwrite": False,
                "default_acl": None,
                "location": "media",
                "object_parameters": {"CacheControl": "max-age=86400"},
            },
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }
    _cdn_domain = os.getenv("AWS_S3_CUSTOM_DOMAIN", "")
    if _cdn_domain:
        MEDIA_URL = f"https://{_cdn_domain}/media/"
    else:
        MEDIA_URL = f"https://{os.getenv('AWS_STORAGE_BUCKET_NAME', '')}.s3.amazonaws.com/media/"

# ---------------------------------------------------------------------------
# Email — use SMTP in prod (configure for SES, SendGrid, etc.)
# ---------------------------------------------------------------------------

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "true").lower() in {"1", "true", "yes"}
EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "").lower() in {"1", "true", "yes"}

# ---------------------------------------------------------------------------
# Logging — structured JSON-style to stdout for log aggregators
# ---------------------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(asctime)s [%(levelname)s] %(name)s pid=%(process)d %(message)s",
        },
    },
    "filters": {
        "require_debug_false": {
            "()": "django.utils.log.RequireDebugFalse",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "mail_admins": {
            "level": "ERROR",
            "class": "django.utils.log.AdminEmailHandler",
            "filters": ["require_debug_false"],
        },
    },
    "root": {
        "handlers": ["console"],
        "level": os.getenv("DJANGO_LOG_LEVEL", "WARNING"),
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console", "mail_admins"],
            "level": "ERROR",
            "propagate": False,
        },
        "security_audit": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

# ---------------------------------------------------------------------------
# Error tracking — Sentry (optional)
# ---------------------------------------------------------------------------

_sentry_dsn = os.getenv("SENTRY_DSN", "")
if _sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.redis import RedisIntegration

    sentry_sdk.init(
        dsn=_sentry_dsn,
        integrations=[DjangoIntegration(), RedisIntegration()],
        environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
        release=os.getenv("GIT_COMMIT_SHA", ""),
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        send_default_pii=False,
    )

# ---------------------------------------------------------------------------
# Admin email notifications for 500 errors
# ---------------------------------------------------------------------------

_admin_email = os.getenv("DJANGO_ADMIN_EMAIL", "")
if _admin_email:
    ADMINS = [("Popcorn N Such Admin", _admin_email)]
    SERVER_EMAIL = os.getenv("SERVER_EMAIL", DEFAULT_FROM_EMAIL)  # noqa: F821
