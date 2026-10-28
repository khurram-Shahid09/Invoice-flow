from rest_framework import serializers

from .adapters.base import ConnectionInfo
from .models import ErpConnection, ErpVendor, SyncRun


class ErpConnectionSerializer(serializers.ModelSerializer):
    secret = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        help_text="API key of the ERP user. Write-only; leave out to keep the current one.",
    )
    has_secret = serializers.SerializerMethodField()

    class Meta:
        model = ErpConnection
        fields = [
            "id",
            "kind",
            "url",
            "database",
            "username",
            "secret",
            "has_secret",
            "last_sync_at",
            "last_sync_status",
            "last_error",
        ]
        read_only_fields = ["id", "last_sync_at", "last_sync_status", "last_error"]

    def get_has_secret(self, connection: ErpConnection) -> bool:
        return bool(connection.secret_enc)

    def validate(self, attrs):
        kind = attrs.get("kind", getattr(self.instance, "kind", None))
        if kind == ErpConnection.Kind.ODOO:
            missing = [f for f in ("url", "database", "username") if not attrs.get(f, "")]
            if missing and self.instance is None:
                raise serializers.ValidationError({f: "Required for Odoo." for f in missing})
        return attrs


class ConnectionInfoSerializer(serializers.Serializer):
    server_version = serializers.CharField()
    company = serializers.CharField()
    currency = serializers.CharField()
    user = serializers.CharField()

    @staticmethod
    def of(info: ConnectionInfo) -> dict:
        return ConnectionInfoSerializer(info).data


class SyncRequestSerializer(serializers.Serializer):
    full = serializers.BooleanField(default=False)


class SyncRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = SyncRun
        fields = ["id", "full", "status", "counts", "error", "started_at", "finished_at"]


class VendorSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErpVendor
        fields = [
            "id",
            "erp_id",
            "name",
            "ref",
            "tax_id",
            "email",
            "city",
            "currency",
            "bank_masks",
            "active",
            "domains",
            "non_po",
            "category",
            "updated_at",
        ]
        read_only_fields = [f for f in fields if f not in ("domains", "non_po", "category")]

    def validate_domains(self, value: list[str]) -> list[str]:
        cleaned = sorted({d.strip().lower() for d in value if d.strip()})
        if any("@" in d or "." not in d for d in cleaned):
            raise serializers.ValidationError("Use domains like vendor.com, not email addresses.")
        return cleaned
