"""``record()`` is the one way to write the audit log."""

from typing import Any

from django.db import models
from rest_framework.request import Request

from accounts.models import Organization

from .models import AuditLog


def actor_for(request: Request | None) -> str:
    if request is None or not getattr(request, "user", None) or not request.user.is_authenticated:
        return "system"
    token = getattr(request, "auth", None)
    if token is not None and token.__class__.__name__ == "ApiToken":
        return f"user:{request.user.pk} via token:{token.pk}"[:64]
    return f"user:{request.user.pk}"


def _client_ip(request: Request) -> str | None:
    # Behind Caddy the client is the first X-Forwarded-For hop; REMOTE_ADDR otherwise.
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return forwarded.split(",")[0].strip() or request.META.get("REMOTE_ADDR") or None


def record(
    action: str,
    *,
    org: Organization,
    request: Request | None = None,
    entity: models.Model | None = None,
    metadata: dict[str, Any] | None = None,
    actor: str | None = None,
) -> AuditLog:
    return AuditLog.objects.create(
        org=org,
        actor=actor or actor_for(request),
        action=action,
        entity_type=(entity._meta.model_name or "") if entity is not None else "",
        entity_id=str(entity.pk) if entity is not None else "",
        metadata=metadata or {},
        ip=_client_ip(request) if request is not None else None,
        user_agent=(request.META.get("HTTP_USER_AGENT", "")[:300] if request is not None else ""),
    )


def purge(queryset: "models.QuerySet[AuditLog]") -> int:
    """Delete audit rows. Only for the retention job and workspace deletion; logged as it runs."""
    from django.db import connection, transaction

    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL invoiceflow.audit_purge = 'on'")
        try:
            deleted, _ = queryset.delete()
        finally:
            # SET LOCAL lasts until the outermost transaction ends; when purge() runs inside
            # a caller's transaction, switch the escape hatch off again right away.
            cursor.execute("SET LOCAL invoiceflow.audit_purge = 'off'")
    return deleted
