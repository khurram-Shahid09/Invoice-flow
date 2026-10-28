from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "org", "actor", "action", "entity_type", "entity_id")
    list_filter = ("action",)
    search_fields = ("actor", "action", "entity_id")

    # Read-only in the admin too; the database rejects changes anyway.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
