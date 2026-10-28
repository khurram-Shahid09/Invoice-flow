from django.db import models

from common.ids import PrefixedIdField
from common.tenancy import OrgOwnedModel


class AuditLog(OrgOwnedModel):
    """Append-only record of who did what. UPDATE and DELETE are rejected by a database trigger."""

    id = PrefixedIdField(prefix="aud")
    actor = models.CharField(max_length=64)  # "user:usr_..." | "system" | "token:tok_..."
    action = models.CharField(max_length=64)  # e.g. "invoice.approved"
    entity_type = models.CharField(max_length=32, blank=True)
    entity_id = models.CharField(max_length=40, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "audit_log"
        indexes = [models.Index(fields=["org", "-created_at"], name="audit_org_created_idx")]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.actor} {self.action}"
