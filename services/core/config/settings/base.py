"""Settings shared by every environment. Environment-specific overrides live in dev/prod/test."""

from datetime import timedelta
from pathlib import Path

import environ

CORE_DIR = Path(__file__).resolve().parents[2]  # services/core
REPO_ROOT = CORE_DIR.parents[1]

env = environ.Env()
# Local development reads the repo-root .env. In containers the variables come from the environment.
if (REPO_ROOT / ".env").is_file():
    # parse_comments: .env.example documents values with trailing "# ..." comments.
    env.read_env(str(REPO_ROOT / ".env"), overwrite=False, parse_comments=True)

APP_ENV = env.str("APP_ENV", default="local")
SECRET_KEY = env.str("DJANGO_SECRET_KEY")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
APP_BASE_URL = env.str("APP_BASE_URL", default="http://localhost:3100")
API_BASE_URL = env.str("API_BASE_URL", default="http://localhost:8100")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    # third party
    "rest_framework",
    "drf_spectacular",
    "corsheaders",
    "rest_framework_simplejwt.token_blacklist",
    # invoiceflow
    "common",
    "accounts",
    "audit",
    "erp",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
ASGI_APPLICATION = "config.asgi.application"

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

DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = CORE_DIR / "staticfiles"

REDIS_URL = env.str("REDIS_URL", default="redis://localhost:6380/0")

# --- DRF / OpenAPI ---
REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "accounts.authentication.PersonalAccessTokenAuthentication",  # "Bearer pat_..."
        "rest_framework_simplejwt.authentication.JWTAuthentication",  # "Bearer <jwt>"
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "common.pagination.CursorPagination",
    "DEFAULT_THROTTLE_RATES": {
        "token": env.str("API_RATE_PER_TOKEN", default="120/min"),
        "login_ip": "20/min",
        "login_email": "5/min",  # with login_ip: brute-force lockout per account
        "register": "10/hour",
    },
    "EXCEPTION_HANDLER": "common.exceptions.api_exception_handler",
}
SPECTACULAR_SETTINGS = {
    "TITLE": "InvoiceFlow API",
    "DESCRIPTION": "AI accounts-payable agent: invoices in, approved bills out, every decision explained.",
    "VERSION": "1.0.0",
    "SCHEMA_PATH_PREFIX": "/api/v1",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

# --- Auth tokens (docs/11-api-spec.md) ---
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "sub",
    "AUTH_HEADER_TYPES": ("Bearer",),
}
REFRESH_COOKIE = {
    "key": "if_refresh",
    "path": "/api/v1/auth/",
    "httponly": True,
    "secure": not DEBUG,
    "samesite": "Lax",  # served first-party through the dashboard's server (BFF)
}

CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}
}

# --- CORS ---
CORS_ALLOWED_ORIGINS = env.list("CORS_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = True

# --- Celery (queues in docs/03-architecture.md) ---
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = None
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_DEFAULT_QUEUE = "check"
# Tasks are named "<queue>.<task>", e.g. "post.sync_erp"; the prefix picks the queue.
CELERY_TASK_ROUTES = {
    f"{queue}.*": {"queue": queue, "routing_key": queue}
    for queue in ("ingest", "extract", "check", "post")
}

# --- Local Odoo (infra/odoo/seed.py, seed_demo, contract tests) ---
ODOO_URL = env.str("ODOO_URL", default="http://localhost:8069").strip()
ODOO_DB = env.str("ODOO_DB", default="invoiceflow").strip()
ODOO_API_USER = env.str("ODOO_API_USER", default="ap-bot@indus-retail.test").strip()
ODOO_API_KEY = env.str("ODOO_API_KEY", default="").strip()

# --- Demo workspace (manage.py seed_demo) ---
# .strip(): .env lines may carry padding before a trailing "# ..." comment.
DEMO_PASSWORD = env.str("DEMO_PASSWORD", default="").strip()

# --- Encryption of bank details and ERP keys (docs/12-security-privacy.md) ---
FIELD_ENCRYPTION_KEY = env.str("FIELD_ENCRYPTION_KEY", default="")

# --- Logging: single-line logs to stdout ---
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "line": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "line"}},
    "root": {"handlers": ["console"], "level": env.str("LOG_LEVEL", default="INFO")},
}

# --- Error reporting (off unless a DSN is set) ---
SENTRY_DSN_API = env.str("SENTRY_DSN_API", default="")
SENTRY_ENVIRONMENT = env.str("SENTRY_ENVIRONMENT", default="development")
