import pytest

from accounts.models import Membership
from audit.models import AuditLog

pytestmark = pytest.mark.django_db


@pytest.fixture
def team(make_account):
    admin = make_account("admin@indus.test")
    clerk = make_account("clerk@indus.test", org=admin.org, roles=["clerk"])
    return admin, clerk


def members_url(org_id: str, member_id: str | None = None) -> str:
    base = f"/api/v1/orgs/{org_id}/members"
    return f"{base}/{member_id}" if member_id else base


def test_any_member_can_list_members(team) -> None:
    admin, clerk = team
    response = clerk.client.get(members_url(admin.org.id))
    assert response.status_code == 200
    emails = {m["user"]["email"] for m in response.data["results"]}
    assert emails == {"admin@indus.test", "clerk@indus.test"}


def test_admin_adds_existing_user_with_roles(team, make_account) -> None:
    admin, _ = team
    make_account("manager@indus.test")  # has their own workspace already
    response = admin.client.post(
        members_url(admin.org.id),
        {"email": "Manager@indus.test", "roles": ["approver"], "approval_limit": "500000"},
        format="json",
    )
    assert response.status_code == 201
    assert response.data["roles"] == ["approver"]
    assert response.data["approval_limit"] == "500000.00"
    assert AuditLog.objects.for_org(admin.org).filter(action="member.added").exists()


def test_new_member_defaults_to_clerk(team, make_account) -> None:
    admin, _ = team
    make_account("newhire@indus.test")
    response = admin.client.post(
        members_url(admin.org.id), {"email": "newhire@indus.test"}, format="json"
    )
    assert response.status_code == 201
    assert response.data["roles"] == ["clerk"]


@pytest.mark.parametrize(
    ("email", "status", "code"),
    [("nobody@indus.test", 404, "user_not_found"), ("clerk@indus.test", 409, "already_member")],
)
def test_add_member_errors(team, email, status, code) -> None:
    admin, _ = team
    response = admin.client.post(members_url(admin.org.id), {"email": email}, format="json")
    assert response.status_code == status
    assert response.data["error"]["code"] == code


def test_roles_must_be_known_and_not_empty(team) -> None:
    admin, clerk = team
    url = members_url(admin.org.id, clerk.membership.id)
    assert admin.client.patch(url, {"roles": []}, format="json").status_code == 400
    assert admin.client.patch(url, {"roles": ["boss"]}, format="json").status_code == 400


def test_non_admins_cannot_manage_members(team) -> None:
    admin, clerk = team
    add = clerk.client.post(members_url(admin.org.id), {"email": "x@indus.test"}, format="json")
    assert add.status_code == 403
    assert add.data["error"]["code"] == "role_required"
    promote = clerk.client.patch(
        members_url(admin.org.id, clerk.membership.id), {"roles": ["admin"]}, format="json"
    )
    assert promote.status_code == 403
    assert Membership.objects.get(pk=clerk.membership.pk).roles == ["clerk"]


def test_admin_updates_and_removes_member(team) -> None:
    admin, clerk = team
    url = members_url(admin.org.id, clerk.membership.id)
    updated = admin.client.patch(
        url, {"roles": ["clerk", "approver"], "approval_limit": "50000"}, format="json"
    )
    assert updated.data["roles"] == ["approver", "clerk"]
    assert admin.client.delete(url).status_code == 204
    assert not Membership.objects.filter(pk=clerk.membership.pk).exists()
    actions = list(AuditLog.objects.for_org(admin.org).values_list("action", flat=True))
    assert "member.updated" in actions and "member.removed" in actions


def test_last_admin_cannot_leave_or_lose_the_role(team) -> None:
    admin, _ = team
    url = members_url(admin.org.id, admin.membership.id)
    demote = admin.client.patch(url, {"roles": ["controller"]}, format="json")
    assert demote.status_code == 409 and demote.data["error"]["code"] == "last_admin"
    assert admin.client.delete(url).status_code == 409
