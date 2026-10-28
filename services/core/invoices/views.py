"""Invoices API (docs/11-api-spec.md): upload, inbox, review, edit, approve or reject, retry."""

from decimal import Decimal
from functools import partial

from django.db import transaction
from django.http import FileResponse
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Role
from accounts.views_base import OrgScopedViewMixin
from common.exceptions import ApiError
from common.text import normalize_invoice_number
from extraction.normalize import parse_date

from .documents import store
from .models import Invoice, Page
from .state import transition
from .tasks import apply_checks, post_invoice, process_invoice

S = Invoice.Status
CLERKS = frozenset({Role.CLERK.value, Role.ADMIN.value})
APPROVERS = frozenset({Role.APPROVER.value, Role.CONTROLLER.value})
EDITABLE = {
    "vendor_name",
    "vendor_tax_id",
    "bank_account",
    "invoice_number",
    "invoice_date",
    "due_date",
    "po_number",
    "currency",
    "subtotal",
    "tax_total",
    "shipping",
    "total",
}


class InvoiceSummarySerializer(serializers.ModelSerializer):
    vendor_name = serializers.SerializerMethodField()
    filename = serializers.CharField(source="document.filename")
    route = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id",
            "status",
            "status_reason",
            "filename",
            "vendor_name",
            "invoice_number",
            "invoice_date",
            "currency",
            "total",
            "route",
            "created_at",
            "updated_at",
        ]

    def get_vendor_name(self, invoice: Invoice) -> str:
        if invoice.vendor:
            return invoice.vendor.name
        return (invoice.fields.get("vendor_name") or {}).get("value") or ""

    def get_route(self, invoice: Invoice) -> str:
        return invoice.decision.get("route", "")


class InvoiceDetailSerializer(InvoiceSummarySerializer):
    pages = serializers.SerializerMethodField()
    po_number = serializers.CharField(source="po.number", default=None)
    has_text_layer = serializers.BooleanField(source="document.has_text_layer")
    uploaded_by = serializers.CharField(source="uploaded_by.email", default=None)
    decided_by = serializers.CharField(source="decided_by.email", default=None)

    class Meta(InvoiceSummarySerializer.Meta):
        fields = [
            *InvoiceSummarySerializer.Meta.fields,
            "fields",
            "lines",
            "checks",
            "decision",
            "extraction",
            "pages",
            "po_number",
            "has_text_layer",
            "uploaded_by",
            "decided_by",
            "decided_at",
            "erp_bill_id",
            "erp_url",
        ]

    def get_pages(self, invoice: Invoice) -> list[dict]:
        return [
            {"number": p.number, "width": p.image.width, "height": p.image.height}
            for p in invoice.document.pages.all()
        ]


class UploadView(OrgScopedViewMixin, APIView):
    parser_classes = [MultiPartParser]
    method_roles = {"POST": CLERKS}

    @extend_schema(
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "files": {"type": "array", "items": {"type": "string", "format": "binary"}}
                },
            }
        },
        responses={201: None},
    )
    def post(self, request: Request) -> Response:
        files = request.FILES.getlist("files")
        if not 1 <= len(files) <= 20:
            raise ApiError("bad_upload", "Send 1 to 20 files in the 'files' field.")
        result = []
        for upload in files:
            stored = store(self.org, request.user, upload.name or "upload", upload.read())  # type: ignore[arg-type]
            if not stored.duplicate_file:
                transaction.on_commit(partial(process_invoice.delay, stored.invoice.id))
            result.append(
                {
                    "invoice": stored.invoice.id,
                    "filename": stored.document.filename,
                    "duplicate_file": stored.duplicate_file,
                }
            )
        return Response({"invoices": result}, status=status.HTTP_201_CREATED)


class InvoiceListView(OrgScopedViewMixin, generics.ListAPIView):
    """``?status=awaiting_approval,needs_review`` filters."""

    queryset = Invoice.objects.select_related("vendor", "document")
    serializer_class = InvoiceSummarySerializer

    def get_queryset(self):
        qs = super().get_queryset()
        wanted = [s for s in self.request.query_params.get("status", "").split(",") if s]
        return qs.filter(status__in=wanted) if wanted else qs


class InvoiceDetailView(OrgScopedViewMixin, generics.RetrieveAPIView):
    queryset = Invoice.objects.select_related(
        "vendor", "po", "document", "uploaded_by", "decided_by"
    )
    serializer_class = InvoiceDetailSerializer
    lookup_url_kwarg = "invoice_id"


class PageImageView(OrgScopedViewMixin, APIView):
    def get(self, request: Request, invoice_id: str, number: int) -> FileResponse:
        invoice = Invoice.objects.for_org(self.org).filter(pk=invoice_id).first()
        page = (
            Page.objects.filter(document_id=invoice.document_id, number=number).first()
            if invoice
            else None
        )
        if page is None:
            raise ApiError("not_found", "No such page.", status_code=404)
        response = FileResponse(page.image.open("rb"), content_type="image/png")
        response["Cache-Control"] = "private, max-age=3600"
        return response


def _invoice(view: OrgScopedViewMixin, invoice_id: str) -> Invoice:
    invoice = (
        Invoice.objects.for_org(view.org)
        .select_related("document", "org", "vendor", "po")
        .filter(pk=invoice_id)
        .first()
    )
    if invoice is None:
        raise ApiError("not_found", "No such invoice.", status_code=404)
    return invoice


class FieldEditSerializer(serializers.Serializer):
    values = serializers.DictField(child=serializers.CharField(allow_blank=True, allow_null=True))


class InvoiceFieldsView(OrgScopedViewMixin, APIView):
    """A clerk corrects fields; the checks run again. The editor can't approve it later."""

    method_roles = {"PATCH": CLERKS}

    @extend_schema(request=FieldEditSerializer, responses={200: InvoiceDetailSerializer})
    def patch(self, request: Request, invoice_id: str) -> Response:
        invoice = _invoice(self, invoice_id)
        if invoice.status not in (S.NEEDS_REVIEW, S.AWAITING_APPROVAL):
            raise ApiError(
                "not_editable",
                "Only invoices in review or awaiting approval can be edited.",
                status_code=409,
            )
        data = FieldEditSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        changes = {
            k: (v or None) for k, v in data.validated_data["values"].items() if k in EDITABLE
        }
        for name, value in changes.items():
            before = invoice.fields.get(name, {}).get("value")
            invoice.fields[name] = {
                "value": value,
                "printed": value,
                "grounding": "edited",
                "trust": "high",
                "before": before,
            }
        invoice.invoice_number = invoice.fields.get("invoice_number", {}).get("value") or ""
        invoice.invoice_number_norm = normalize_invoice_number(invoice.invoice_number)
        invoice.invoice_date = parse_date(
            invoice.fields.get("invoice_date", {}).get("value"), invoice.org.date_format
        )
        total = invoice.fields.get("total", {}).get("value")
        invoice.total = Decimal(total) if total else None
        invoice.currency = invoice.fields.get("currency", {}).get("value") or invoice.currency
        invoice.last_edited_by = request.user  # type: ignore[assignment]
        invoice.save()
        from audit.service import record

        record(
            "invoice.fields_edited",
            org=self.org,
            request=request,
            entity=invoice,
            metadata={"fields": list(changes)},
        )
        apply_checks(invoice, actor=request.user)  # type: ignore[arg-type]
        return Response(InvoiceDetailSerializer(invoice).data)


class DecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approve", "reject"])
    reason = serializers.CharField(required=False, allow_blank=True, max_length=300)


class InvoiceDecisionView(OrgScopedViewMixin, APIView):
    """Approve (approvers, within their limit) or reject (approvers and clerks)."""

    @extend_schema(request=DecisionSerializer, responses={200: InvoiceDetailSerializer})
    def post(self, request: Request, invoice_id: str) -> Response:
        invoice = _invoice(self, invoice_id)
        data = DecisionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        approve = data.validated_data["decision"] == "approve"
        reason = data.validated_data.get("reason", "")
        member = self.membership
        if approve:
            if not member.has_role(*APPROVERS):
                raise PermissionDenied("Only approvers can approve.", code="role_required")
            if invoice.status != S.AWAITING_APPROVAL:
                raise ApiError(
                    "not_awaiting_approval",
                    "This invoice isn't waiting for approval.",
                    status_code=409,
                )
            if request.user.pk in (invoice.uploaded_by_id, invoice.last_edited_by_id):
                raise PermissionDenied(
                    "You uploaded or edited this invoice, so someone else must approve it.",
                    code="segregation_of_duties",
                )
            limit = member.approval_limit
            if (
                limit is not None
                and invoice.total is not None
                and invoice.total > limit
                and not member.has_role(Role.CONTROLLER)
            ):
                raise PermissionDenied(
                    f"Above your approval limit of {limit:,.0f}.", code="over_limit"
                )
            target = S.APPROVED
        else:
            if not member.has_role(*APPROVERS, *CLERKS):
                raise PermissionDenied("You can't reject invoices.", code="role_required")
            if invoice.status not in (S.AWAITING_APPROVAL, S.NEEDS_REVIEW):
                raise ApiError(
                    "not_rejectable", "This invoice can't be rejected now.", status_code=409
                )
            if not reason:
                raise ApiError("reason_required", "Say why it's rejected.")
            target = S.REJECTED
        invoice.decided_by, invoice.decided_at = request.user, timezone.now()  # type: ignore[assignment]
        invoice.save(update_fields=["decided_by", "decided_at", "updated_at"])
        transition(invoice, target, actor=request.user, reason=reason or "Approved")  # type: ignore[arg-type]
        if approve:
            post_invoice.delay(invoice.id)
            invoice.refresh_from_db()
        return Response(InvoiceDetailSerializer(invoice).data)


class InvoiceRetryView(OrgScopedViewMixin, APIView):
    """Retry a failed read or a failed posting."""

    method_roles = {"POST": CLERKS}

    @extend_schema(request=None, responses={202: None})
    def post(self, request: Request, invoice_id: str) -> Response:
        invoice = _invoice(self, invoice_id)
        if invoice.status == S.EXTRACTION_FAILED:
            process_invoice.delay(invoice.id)
        elif invoice.status == S.POSTING_FAILED:
            post_invoice.delay(invoice.id)
        else:
            raise ApiError(
                "nothing_to_retry", "Only failed reads or postings can be retried.", status_code=409
            )
        return Response(status=status.HTTP_202_ACCEPTED)
