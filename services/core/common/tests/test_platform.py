import re

import pytest
from django.test import Client
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from common.exceptions import ApiError
from common.ids import PrefixedULID

ULID_RE = r"[0-9A-HJKMNP-TV-Z]{26}"


def test_prefixed_ulid_format_and_order() -> None:
    gen = PrefixedULID("inv")
    first, second = gen(), gen()
    assert re.fullmatch(rf"inv_{ULID_RE}", first)
    assert first != second


def test_prefixed_ulid_rejects_bad_prefix() -> None:
    with pytest.raises(ValueError, match="invalid id prefix"):
        PrefixedULID("Invoice")


def test_healthz(client: Client) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_readyz_reports_dependencies(client: Client) -> None:
    body = client.get("/readyz").json()
    assert body["checks"]["database"] == "ok"
    assert set(body["checks"]) == {"database", "redis"}


@pytest.mark.django_db
def test_openapi_schema_served(client: Client) -> None:
    response = client.get("/api/v1/schema/")
    assert response.status_code == 200
    assert b"InvoiceFlow API" in response.content


class _Boom(APIView):
    permission_classes: list = []

    def get(self, request):  # replaced per test
        raise NotImplementedError


class _Protected(APIView):
    def get(self, request):
        return None


@pytest.mark.parametrize(
    ("exc", "status_code", "code"),
    [
        (
            ApiError("invoice_not_found", "No such invoice.", status_code=404),
            404,
            "invoice_not_found",
        ),
        (NotFound(), 404, "not_found"),
    ],
)
def test_error_envelope(monkeypatch, exc: Exception, status_code: int, code: str) -> None:
    def _raise(self, request):
        raise exc

    monkeypatch.setattr(_Boom, "get", _raise)
    response = _Boom.as_view()(APIRequestFactory().get("/x"))
    assert response.status_code == status_code
    assert response.data["error"]["code"] == code
    assert set(response.data["error"]) == {"code", "message", "details"}


def test_unauthenticated_by_default() -> None:
    response = _Protected.as_view()(APIRequestFactory().get("/x"))
    assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
    assert response.data["error"]["code"] == "not_authenticated"
