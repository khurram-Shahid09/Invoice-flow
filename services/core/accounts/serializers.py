from datetime import timedelta

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import serializers

from .models import ApiToken, Membership, Organization, User


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ["id", "name", "base_currency", "timezone"]


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "name"]


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    org_name = serializers.CharField(max_length=120)

    def validate_email(self, value: str) -> str:
        value = value.strip().lower()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate(self, attrs):
        try:
            validate_password(
                attrs["password"], User(email=attrs["email"], name=attrs.get("name", ""))
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": exc.messages}) from exc
        return attrs


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class MembershipSerializer(serializers.ModelSerializer):
    org = OrganizationSerializer(read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "org", "roles", "approval_limit"]


class MeTokenSerializer(serializers.ModelSerializer):
    org = OrganizationSerializer(read_only=True)

    class Meta:
        model = ApiToken
        fields = ["id", "name", "org", "expires_at"]


class MeSerializer(serializers.ModelSerializer):
    memberships = MembershipSerializer(many=True, read_only=True)
    token = serializers.SerializerMethodField(
        help_text="The access token this request used (null for dashboard sessions)."
    )

    class Meta:
        model = User
        fields = ["id", "email", "name", "memberships", "token"]

    def get_token(self, user: User) -> dict | None:
        token = self.context.get("token")
        return MeTokenSerializer(token).data if token is not None else None


class AuthResponseSerializer(serializers.Serializer):
    """Documented shape of register/login/refresh responses (refresh token is in the cookie)."""

    access = serializers.CharField()
    access_expires_in = serializers.IntegerField()
    user = UserSerializer()


class ApiTokenSerializer(serializers.ModelSerializer):
    expires_in_days = serializers.IntegerField(
        write_only=True, required=False, min_value=1, max_value=365
    )

    class Meta:
        model = ApiToken
        fields = [
            "id",
            "name",
            "created_at",
            "last_used_at",
            "expires_at",
            "revoked_at",
            "expires_in_days",
        ]
        read_only_fields = ["id", "created_at", "last_used_at", "expires_at", "revoked_at"]

    def create(self, validated_data):
        # org and user come from the view: serializer.save(org=..., user=...)
        days = validated_data.pop("expires_in_days", None)
        token, _ = ApiToken.issue(  # plaintext is on token.plaintext
            org=validated_data["org"],
            user=validated_data["user"],
            name=validated_data["name"],
            expires_at=timezone.now() + timedelta(days=days) if days else None,
        )
        return token


class ApiTokenCreatedSerializer(ApiTokenSerializer):
    token = serializers.CharField(source="plaintext", read_only=True)

    class Meta(ApiTokenSerializer.Meta):
        fields = [*ApiTokenSerializer.Meta.fields, "token"]


class MemberSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    email = serializers.EmailField(write_only=True)

    class Meta:
        model = Membership
        fields = ["id", "user", "roles", "approval_limit", "created_at", "email"]
        read_only_fields = ["id", "created_at"]

    def validate_roles(self, value: list[str]) -> list[str]:
        return _validated_roles(value)


class MemberUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Membership
        fields = ["id", "roles", "approval_limit"]
        read_only_fields = ["id"]

    def validate_roles(self, value: list[str]) -> list[str]:
        return _validated_roles(value)


def _validated_roles(value: list[str]) -> list[str]:
    if not value:
        raise serializers.ValidationError("A member needs at least one role.")
    return sorted(set(value))
