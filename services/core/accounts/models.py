import hashlib
import secrets

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.contrib.postgres.fields import ArrayField
from django.db import models

from common.ids import PrefixedIdField
from common.models import TimeStampedModel
from common.tenancy import OrgOwnedModel


class UserManager(BaseUserManager["User"]):
    use_in_migrations = True

    def _create(self, email: str, password: str | None, **extra) -> "User":
        if not email:
            raise ValueError("email is required")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra) -> "User":
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra) -> "User":
        extra["is_staff"] = True
        extra["is_superuser"] = True
        return self._create(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    """One account for the dashboard. Email is the login (case-insensitive)."""

    id = PrefixedIdField(prefix="usr")
    email = models.EmailField(max_length=254, unique=True)  # always stored lowercased
    name = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)  # Django admin access only

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "users"

    def __str__(self) -> str:
        return self.email

    def save(self, *args, **kwargs) -> None:
        self.email = self.email.lower()
        super().save(*args, **kwargs)


class Organization(TimeStampedModel):
    """A company using InvoiceFlow. Every tenant-owned row belongs to exactly one organization."""

    id = PrefixedIdField(prefix="org")
    name = models.CharField(max_length=120)
    base_currency = models.CharField(max_length=3, default="PKR")  # ISO 4217
    timezone = models.CharField(max_length=64, default="Asia/Karachi")
    date_format = models.CharField(
        max_length=3,
        default="DMY",
        help_text="How ambiguous dates like 03/04/2026 are read (docs/06-ai-extraction.md).",
    )
    # Tolerances, thresholds and toggles for the check rules (docs/07-validation-and-matching.md).
    settings = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "organizations"

    def __str__(self) -> str:
        return self.name


class Role(models.TextChoices):
    """docs/08-approvals-and-workflow.md. A member can hold several roles."""

    CLERK = "clerk"  # upload, review, correct, submit, retry posting
    APPROVER = "approver"  # approve or reject invoices routed to them, up to their limit
    CONTROLLER = "controller"  # any amount; rules, tolerances, approval matrix, metrics, audit
    ADMIN = "admin"  # users and roles, ERP connection, mailbox, budgets, bank verification


def _default_roles() -> list[str]:
    return [Role.CLERK]


class Membership(OrgOwnedModel, TimeStampedModel):
    id = PrefixedIdField(prefix="mem")
    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    roles = ArrayField(
        models.CharField(max_length=12, choices=Role.choices), default=_default_roles
    )
    # Highest invoice total (in the org's base currency) this member may approve; null = no limit.
    approval_limit = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = "memberships"
        constraints = [
            models.UniqueConstraint(fields=["org", "user"], name="memberships_org_user_unique")
        ]

    def __str__(self) -> str:
        return f"{self.user_id} in {self.org_id} ({', '.join(self.roles)})"

    def has_role(self, *roles: str) -> bool:
        return any(role in self.roles for role in roles)

    @property
    def is_admin(self) -> bool:
        return self.has_role(Role.ADMIN)


class ApiToken(OrgOwnedModel, TimeStampedModel):
    """Personal access token for scripts and integrations. Only its SHA-256 is stored."""

    PREFIX = "pat_"
    plaintext = ""  # set on the instance returned by issue(); never stored

    id = PrefixedIdField(prefix="tok")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="api_tokens")
    name = models.CharField(max_length=100)
    token_hash = models.CharField(max_length=64, unique=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "api_tokens"

    def __str__(self) -> str:
        return f"{self.name} ({self.id})"

    @staticmethod
    def hash(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def issue(
        cls, *, org: Organization, user: User, name: str, expires_at=None
    ) -> tuple["ApiToken", str]:
        """Create a token and return it with the plaintext, which is never retrievable again."""
        raw = cls.PREFIX + secrets.token_urlsafe(32)
        token = cls.objects.create(
            org=org, user=user, name=name, token_hash=cls.hash(raw), expires_at=expires_at
        )
        token.plaintext = raw
        return token, raw

    def is_usable(self, now) -> bool:
        return self.revoked_at is None and (self.expires_at is None or self.expires_at > now)
