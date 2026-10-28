import pytest
from django.core.management import CommandError, call_command

from accounts.models import Membership, Organization
from erp.models import ErpConnection, ErpVendor

pytestmark = pytest.mark.django_db


def test_seed_demo_creates_one_user_per_role_and_is_repeatable(settings, api) -> None:
    settings.DEMO_PASSWORD = "demo-password-123"
    settings.ODOO_API_KEY = ""  # no Odoo: the fake ERP with the same seed data
    call_command("seed_demo", stdout=None)
    call_command("seed_demo", stdout=None)  # second run updates, never duplicates

    org = Organization.objects.get(name="Indus Retail (Pvt) Ltd")
    roles = {m.user.email: m.roles for m in Membership.objects.for_org(org).select_related("user")}
    assert roles == {
        "clerk@indus-retail.test": ["clerk"],
        "approver@indus-retail.test": ["approver"],
        "controller@indus-retail.test": ["approver", "controller"],
        "admin@indus-retail.test": ["admin"],
    }
    connection = ErpConnection.objects.get(org=org)
    assert connection.kind == "fake" and connection.last_sync_status == "ok"
    assert ErpVendor.objects.for_org(org).count() == 11

    login = api.post(
        "/api/v1/auth/login",
        {"email": "clerk@indus-retail.test", "password": "demo-password-123"},
        format="json",
    )
    assert login.status_code == 200


def test_seed_demo_needs_a_password(settings) -> None:
    settings.DEMO_PASSWORD = ""
    with pytest.raises(CommandError, match="DEMO_PASSWORD"):
        call_command("seed_demo")


def test_seed_demo_marks_utility_vendors_non_po(settings) -> None:
    settings.DEMO_PASSWORD = "demo-password-123"
    settings.ODOO_API_KEY = ""
    call_command("seed_demo", stdout=None)
    org = Organization.objects.get(name="Indus Retail (Pvt) Ltd")
    non_po = set(ErpVendor.objects.for_org(org).filter(non_po=True).values_list("ref", flat=True))
    assert non_po == {"N01", "N02", "N03"}
