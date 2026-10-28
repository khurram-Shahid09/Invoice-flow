from .base import *  # noqa: F403

DEBUG = False

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # TLS terminates at Caddy
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
CSRF_TRUSTED_ORIGINS = [API_BASE_URL, APP_BASE_URL]  # noqa: F405

if len(SECRET_KEY) < 50:  # noqa: F405
    raise RuntimeError("DJANGO_SECRET_KEY must be at least 50 characters in production")
if not FIELD_ENCRYPTION_KEY:  # noqa: F405
    raise RuntimeError("FIELD_ENCRYPTION_KEY is required in production")

SENTRY_ENVIRONMENT = env.str("SENTRY_ENVIRONMENT", default="production")  # noqa: F405
