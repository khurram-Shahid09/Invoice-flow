from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import ApiToken, Membership
from audit.models import AuditLog

pytestmark = pytest.mark.django_db


def create_token(client, name="Chrome on laptop", **extra):
    return client.post("/api/v1/tokens", {"name": name, **extra}, format="json")


def pat_client(raw: str) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return client


def test_token_is_shown_once_and_stored_hashed(make_account) -> None:
    account = make_account("sara@acme.test")
    response = create_token(account.client, expires_in_days=30)
    assert response.status_code == 201
    raw = response.data["token"]
    assert raw.startswith("pat_") and len(raw) > 40

    stored = ApiToken.objects.get(pk=response.data["id"])
    assert stored.token_hash == ApiToken.hash(raw) and raw not in stored.token_hash
    assert stored.expires_at is not None

    listed = account.client.get("/api/v1/tokens")
    assert listed.status_code == 200
    assert [t["id"] for t in listed.data["results"]] == [stored.id]
    assert "token" not in listed.data["results"][0]
    assert AuditLog.objects.for_org(account.org).filter(action="token.created").exists()


def test_pat_authenticates_and_tracks_last_use(make_account) -> None:
    account = make_account("sara@acme.test")
    raw = create_token(account.client).data["token"]
    me = pat_client(raw).get("/api/v1/me")
    assert me.status_code == 200 and me.data["email"] == "sara@acme.test"
    assert ApiToken.objects.get(token_hash=ApiToken.hash(raw)).last_used_at is not None


@pytest.mark.parametrize("change", ["revoked", "expired", "removed_from_org", "deactivated"])
def test_pat_stops_working(make_account, change: str) -> None:
    account = make_account("sara@acme.test")
    raw = create_token(account.client).data["token"]
    token = ApiToken.objects.get(token_hash=ApiToken.hash(raw))

    if change == "revoked":
        assert account.client.delete(f"/api/v1/tokens/{token.id}").status_code == 204
    elif change == "expired":
        ApiToken.objects.filter(pk=token.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
    elif change == "removed_from_org":
        Membership.objects.filter(pk=account.membership.pk).delete()
    else:
        account.user.is_active = False
        account.user.save()

    response = pat_client(raw).get("/api/v1/me")
    assert response.status_code == 401
    assert response.data["error"]["code"] in ("invalid_token", "authentication_failed")


def test_unknown_pat_rejected() -> None:
    assert pat_client("pat_not-a-real-token").get("/api/v1/me").status_code == 401


def test_pat_cannot_mint_tokens(make_account) -> None:
    account = make_account("sara@acme.test")
    raw = create_token(account.client).data["token"]
    response = create_token(pat_client(raw), name="escalation")
    assert response.status_code == 403
    assert ApiToken.objects.count() == 1


def test_revoke_is_idempotent_and_audited_once(make_account) -> None:
    account = make_account("sara@acme.test")
    token_id = create_token(account.client).data["id"]
    assert account.client.delete(f"/api/v1/tokens/{token_id}").status_code == 204
    assert account.client.delete(f"/api/v1/tokens/{token_id}").status_code == 204
    assert AuditLog.objects.for_org(account.org).filter(action="token.revoked").count() == 1


def test_me_reports_the_tokens_workspace(make_account) -> None:
    account = make_account("sara@acme.test")
    raw = create_token(account.client, name="Scanner").data["token"]
    me = pat_client(raw).get("/api/v1/me").data
    assert me["token"]["name"] == "Scanner"
    assert me["token"]["org"] == {
        "id": account.org.id,
        "name": account.org.name,
        "base_currency": "PKR",
        "timezone": "Asia/Karachi",
    }
    assert account.client.get("/api/v1/me").data["token"] is None
