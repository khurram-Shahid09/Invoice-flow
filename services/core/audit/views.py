from rest_framework import generics, serializers

from accounts.models import Role
from accounts.views_base import OrgScopedViewMixin

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = [
            "id",
            "created_at",
            "actor",
            "action",
            "entity_type",
            "entity_id",
            "metadata",
            "ip",
            "user_agent",
        ]


class AuditLogListView(OrgScopedViewMixin, generics.ListAPIView):
    """Controllers and admins. Newest first, cursor-paginated."""

    queryset = AuditLog.objects.all()
    serializer_class = AuditLogSerializer
    method_roles = {"GET": frozenset({Role.CONTROLLER.value, Role.ADMIN.value})}
