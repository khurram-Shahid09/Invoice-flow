"""Cross-tenant access must be impossible (threat T7). Two layers:

1. Behaviour: a user of org B gets 404 for everything in org A.
2. Structure (meta-tests): every model with an ``org`` field is an OrgOwnedModel, and every
   API view over such a model uses OrgScopedViewMixin. New code that forgets fails CI here.
"""

import pytest
from django.apps import apps
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.test import APIClient

from accounts.models import ApiToken
from accounts.views_base import OrgScopedViewMixin
from audit.models import AuditLog
from common.tenancy import OrgOwnedModel

pytestmark = pytest.mark.django_db


@pytest.fixture
def two_orgs(make_account):
    return make_account("a@alpha.test"), make_account("b@beta.test")


def test_cannot_list_or_touch_another_orgs_members(two_orgs) -> None:
    a, b = two_orgs
    url = f"/api/v1/orgs/{a.org.id}/members"
    assert b.client.get(url).status_code == 404
    assert b.client.post(url, {"email": "b@beta.test"}, format="json").status_code == 404
    assert (
        b.client.patch(f"{url}/{a.membership.id}", {"roles": ["clerk"]}, format="json").status_code
        == 404
    )
    assert b.client.delete(f"{url}/{a.membership.id}").status_code == 404


def test_cannot_revoke_another_users_token(two_orgs) -> None:
    a, b = two_orgs
    token_id = a.client.post("/api/v1/tokens", {"name": "a"}, format="json").data["id"]
    assert b.client.delete(f"/api/v1/tokens/{token_id}").status_code == 404
    assert ApiToken.objects.get(pk=token_id).revoked_at is None
    assert b.client.get("/api/v1/tokens").data["results"] == []


def test_org_header_for_foreign_org_is_not_found(two_orgs) -> None:
    a, b = two_orgs
    response = b.client.get("/api/v1/tokens", HTTP_X_ORG_ID=a.org.id)
    assert response.status_code == 404


def test_pat_is_pinned_to_its_org(two_orgs, make_account) -> None:
    a, _ = two_orgs
    make_account("a@second.test")  # unrelated
    raw = a.client.post("/api/v1/tokens", {"name": "scanner"}, format="json").data["token"]
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    other_org = make_account("x@gamma.test").org
    assert client.get("/api/v1/tokens", HTTP_X_ORG_ID=other_org.id).status_code == 404
    assert client.get("/api/v1/tokens").status_code == 200


def test_audit_log_is_per_org(two_orgs) -> None:
    a, b = two_orgs
    a.client.post("/api/v1/tokens", {"name": "a-token"}, format="json")
    b_actions = [row["action"] for row in b.client.get("/api/v1/audit").data["results"]]
    assert "token.created" not in b_actions


# --- Structural guarantees ---


def test_every_org_owned_model_uses_the_scoped_base() -> None:
    offenders = [
        m.__name__
        for m in apps.get_models()
        if any(f.name == "org" for f in m._meta.fields) and not issubclass(m, OrgOwnedModel)
    ]
    assert offenders == []


def _api_views(resolver: URLResolver, prefix: str = ""):
    for p in resolver.url_patterns:
        if isinstance(p, URLResolver):
            yield from _api_views(p, prefix + str(p.pattern))
        elif isinstance(p, URLPattern) and hasattr(p.callback, "cls"):
            yield prefix + str(p.pattern), p.callback.cls


def test_every_view_over_org_owned_data_is_scoped() -> None:
    offenders = []
    for route, view in _api_views(get_resolver()):
        queryset = getattr(view, "queryset", None)
        model = getattr(queryset, "model", None)
        if (
            model is not None
            and issubclass(model, OrgOwnedModel)
            and not issubclass(view, OrgScopedViewMixin)
        ):
            offenders.append(f"{route} ({view.__name__})")
    assert offenders == []


def test_for_org_refuses_unsaved_or_missing_org() -> None:
    with pytest.raises(ValueError):
        AuditLog.objects.for_org(None)  # type: ignore[arg-type]
