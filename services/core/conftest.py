from dataclasses import dataclass

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from accounts.models import Membership, Organization, Role, User

PASSWORD = "correct-horse-battery-9"
ALL_ROLES = sorted(Role.values)


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()  # throttle counters live in the cache
    yield
    cache.clear()


@dataclass
class Account:
    user: User
    org: Organization
    membership: Membership
    client: APIClient  # authenticated with a JWT access token


@pytest.fixture
def make_account(db):
    """make_account("sara@acme.test", org=None, roles=None) → Account with a logged-in client.

    Without ``roles`` the member gets every role (like the person who creates a workspace).
    """

    def _make(
        email: str, *, org: Organization | None = None, roles: list[str] | None = None
    ) -> Account:
        user = User.objects.create_user(email, PASSWORD, name=email.split("@")[0])
        org = org or Organization.objects.create(name=f"{email} org")
        membership = Membership.objects.create(org=org, user=user, roles=roles or ALL_ROLES)
        client = APIClient()
        response = client.post(
            "/api/v1/auth/login", {"email": email, "password": PASSWORD}, format="json"
        )
        assert response.status_code == 200, response.content
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        return Account(user, org, membership, client)

    return _make


@pytest.fixture
def api() -> APIClient:
    return APIClient()
