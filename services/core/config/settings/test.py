import os

# Tests must not depend on a developer's secrets; provide safe defaults before base reads the env.
os.environ.setdefault("DJANGO_SECRET_KEY", "test-secret-key-not-for-production-" + "x" * 20)
# Test-only field encryption key (32 bytes, base64).
os.environ.setdefault(
    "FIELD_ENCRYPTION_KEY",
    "dGVzdC1maWVsZC1rZXktMzItYnl0ZXMtbG9uZyEhISE=",  # gitleaks:allow (test-only)
)
os.environ.setdefault(
    "DATABASE_URL", "postgres://invoiceflow:invoiceflow@localhost:5435/invoiceflow"
)

from .base import *  # noqa: E402, F403

DEBUG = False
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # fast tests only  # noqa: S303
CELERY_TASK_ALWAYS_EAGER = True
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
