"""ERP connection, sync and vendor master data (docs/11-api-spec.md "Rules, vendors, ERP")."""

from django.db.models import Q
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Role
from accounts.views_base import OrgScopedViewMixin
from audit.service import record
from common.exceptions import ApiError
from common.pagination import CursorPagination

from .adapters.base import ErpError
from .models import ErpConnection, ErpVendor, SyncRun
from .serializers import (
    ConnectionInfoSerializer,
    ErpConnectionSerializer,
    SyncRequestSerializer,
    SyncRunSerializer,
    VendorSerializer,
)
from .sync import adapter_for
from .tasks import sync_erp

ADMIN = frozenset({Role.ADMIN.value})
FINANCE = frozenset({Role.CONTROLLER.value, Role.ADMIN.value})


def _connection(org) -> ErpConnection:
    connection = ErpConnection.objects.for_org(org).first()
    if connection is None:
        raise ApiError("erp_not_connected", "No ERP is connected yet.", status_code=404)
    return connection


class ErpConnectionView(OrgScopedViewMixin, APIView):
    method_roles = {"GET": ADMIN, "PUT": ADMIN}

    @extend_schema(responses={200: ErpConnectionSerializer})
    def get(self, request: Request) -> Response:
        return Response(ErpConnectionSerializer(_connection(self.org)).data)

    @extend_schema(request=ErpConnectionSerializer, responses={200: ErpConnectionSerializer})
    def put(self, request: Request) -> Response:
        existing = ErpConnection.objects.for_org(self.org).first()
        serializer = ErpConnectionSerializer(existing, data=request.data, partial=bool(existing))
        serializer.is_valid(raise_exception=True)
        secret = serializer.validated_data.pop("secret", None)
        connection = serializer.save(org=self.org)
        if secret is not None:
            connection.set_secret(secret)
            connection.sync_state = {}  # new credentials may mean a different database
            connection.save(update_fields=["secret_enc", "sync_state", "updated_at"])
        record(
            "erp.connection_saved",
            org=self.org,
            request=request,
            entity=connection,
            metadata={
                "kind": connection.kind,
                "url": connection.url,
                "database": connection.database,
                "username": connection.username,
                "secret_changed": secret is not None,
            },
        )
        return Response(ErpConnectionSerializer(connection).data)


class ErpConnectionTestView(OrgScopedViewMixin, APIView):
    method_roles = {"POST": ADMIN}

    @extend_schema(request=None, responses={200: ConnectionInfoSerializer})
    def post(self, request: Request) -> Response:
        try:
            info = adapter_for(_connection(self.org)).test_connection()
        except ErpError as exc:
            raise ApiError("erp_error", str(exc), status_code=502) from exc
        return Response(ConnectionInfoSerializer.of(info))


class ErpSyncView(OrgScopedViewMixin, APIView):
    method_roles = {"POST": ADMIN}

    @extend_schema(request=SyncRequestSerializer, responses={202: None})
    def post(self, request: Request) -> Response:
        options = SyncRequestSerializer(data=request.data)
        options.is_valid(raise_exception=True)
        connection = _connection(self.org)
        record(
            "erp.sync_requested",
            org=self.org,
            request=request,
            entity=connection,
            metadata=options.validated_data,
        )
        sync_erp.delay(connection.id, full=options.validated_data["full"])
        return Response(status=status.HTTP_202_ACCEPTED)


class SyncRunPagination(CursorPagination):
    ordering = ("-started_at", "-id")


class SyncRunListView(OrgScopedViewMixin, generics.ListAPIView):
    queryset = SyncRun.objects.all()
    serializer_class = SyncRunSerializer
    pagination_class = SyncRunPagination
    method_roles = {"GET": FINANCE}


class VendorListView(OrgScopedViewMixin, generics.ListAPIView):
    """Every member can look vendors up. ``?q=`` searches name, ref, tax id and email."""

    queryset = ErpVendor.objects.all()
    serializer_class = VendorSerializer
    pagination_class = None  # a vendor master is small; the dashboard filters client-side

    def get_queryset(self):
        qs = super().get_queryset().order_by("name")
        q = self.request.query_params.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(ref__iexact=q)
                | Q(tax_id__icontains=q)
                | Q(email__icontains=q)
            )
        return qs


class VendorDetailView(OrgScopedViewMixin, generics.RetrieveUpdateAPIView):
    """Controllers and admins mark vendors as non-PO, set a category and known domains."""

    queryset = ErpVendor.objects.all()
    serializer_class = VendorSerializer
    lookup_url_kwarg = "vendor_id"
    http_method_names = ["get", "patch", "head", "options"]
    method_roles = {"PATCH": FINANCE}

    def perform_update(self, serializer) -> None:
        vendor = serializer.instance
        before = {f: getattr(vendor, f) for f in ("non_po", "category", "domains")}
        serializer.save()
        after = {f: getattr(vendor, f) for f in ("non_po", "category", "domains")}
        record(
            "vendor.updated",
            org=self.org,
            request=self.request,
            entity=vendor,
            metadata={"from": before, "to": after},
        )
