from decimal import Decimal

import pytest
from django.db import IntegrityError

from accounts.models import Membership, Organization, Role, User

pytestmark = pytest.mark.django_db


def test_create_user_normalizes_email_and_hashes_password() -> None:
    user = User.objects.create_user("Sara@Example.COM", "correct horse battery")
    assert user.email == "sara@example.com"
    assert user.id.startswith("usr_")
    assert user.password != "correct horse battery"
    assert user.check_password("correct horse battery")
    assert not user.is_staff


def test_email_is_case_insensitively_unique() -> None:
    User.objects.create_user("imran@example.com", "pw-1234567890")
    with pytest.raises(IntegrityError):
        User.objects.create_user("IMRAN@example.com", "pw-1234567890")


def test_user_without_password_cannot_sign_in() -> None:
    user = User.objects.create_user("invited@example.com")
    assert not user.has_usable_password()


def test_create_superuser() -> None:
    admin = User.objects.create_superuser("admin@example.com", "pw-1234567890")
    assert admin.is_staff and admin.is_superuser


def test_organization_defaults_to_pakistan() -> None:
    org = Organization.objects.create(name="Indus Retail")
    assert (org.base_currency, org.timezone, org.date_format) == ("PKR", "Asia/Karachi", "DMY")


def test_membership_roles() -> None:
    org = Organization.objects.create(name="Indus Retail")
    clerk = Membership.objects.create(org=org, user=User.objects.create_user("c@x.test"))
    assert clerk.roles == ["clerk"]
    assert not clerk.is_admin

    boss = Membership.objects.create(
        org=org,
        user=User.objects.create_user("b@x.test"),
        roles=[Role.APPROVER, Role.CONTROLLER],
        approval_limit=Decimal("500000"),
    )
    assert boss.has_role(Role.CONTROLLER)
    assert boss.has_role(Role.ADMIN, Role.APPROVER)
    assert not boss.has_role(Role.CLERK)


def test_one_membership_per_user_and_org() -> None:
    org = Organization.objects.create(name="Indus Retail")
    user = User.objects.create_user("c@x.test")
    Membership.objects.create(org=org, user=user)
    with pytest.raises(IntegrityError):
        Membership.objects.create(org=org, user=user)
