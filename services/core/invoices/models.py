"""Documents, their pages, and the invoices found in them (docs/10-data-model.md).

Extraction results live on the invoice as JSON: every header field carries its value plus
the evidence (page, quote, box on the page, grounding, trust), and check results with the
routing decision are stored with the rules version that produced them.
"""

from django.conf import settings
from django.db import models

from common.ids import PrefixedIdField
from common.models import TimeStampedModel
from common.tenancy import OrgOwnedModel


def _upload_to(document: "Document", filename: str) -> str:
    return f"orgs/{document.org_id}/files/{document.sha256}/{filename}"


def _page_to(page: "Page", filename: str) -> str:
    return f"orgs/{page.document.org_id}/pages/{page.document.sha256}/{filename}"


class Document(OrgOwnedModel, TimeStampedModel):
    id = PrefixedIdField(prefix="doc")
    sha256 = models.CharField(max_length=64)
    filename = models.CharField(max_length=255)
    mime = models.CharField(max_length=60)
    size = models.PositiveIntegerField()
    file = models.FileField(upload_to=_upload_to, max_length=300)
    page_count = models.PositiveIntegerField(default=0)
    has_text_layer = models.BooleanField(default=False)
    hidden_text = models.TextField(blank=True)  # invisible text found in the PDF (docs/06)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )

    class Meta:
        db_table = "documents"
        constraints = [
            models.UniqueConstraint(fields=["org", "sha256"], name="documents_org_sha_uniq")
        ]

    def __str__(self) -> str:
        return self.filename


class Page(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="pages")
    number = models.PositiveIntegerField()  # 1-based
    image = models.ImageField(upload_to=_page_to, max_length=300)
    # Text layer words: [{"t": "INV-2291", "b": [x0, y0, x1, y1]}], boxes as fractions of the page.
    words = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "pages"
        ordering = ["number"]
        constraints = [
            models.UniqueConstraint(fields=["document", "number"], name="pages_doc_number_uniq")
        ]

    def __str__(self) -> str:
        return f"{self.document_id} p{self.number}"


class Invoice(OrgOwnedModel, TimeStampedModel):
    class Status(models.TextChoices):
        RECEIVED = "received"
        EXTRACTING = "extracting"
        EXTRACTION_FAILED = "extraction_failed"
        NEEDS_REVIEW = "needs_review"
        AWAITING_APPROVAL = "awaiting_approval"
        APPROVED = "approved"
        POSTING = "posting"
        POSTED = "posted"
        POSTING_FAILED = "posting_failed"
        REJECTED = "rejected"
        NOT_INVOICE = "not_invoice"

    id = PrefixedIdField(prefix="inv")
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="invoices")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RECEIVED)
    status_reason = models.CharField(max_length=300, blank=True)

    # Extraction (docs/06): {"total": {"value", "page", "quote", "box", "grounding", "trust"}}
    fields = models.JSONField(default=dict, blank=True)
    lines = models.JSONField(default=list, blank=True)
    extraction = models.JSONField(default=dict, blank=True)  # provider, model, tokens, ms

    # Normalised copies of key fields, for queries and duplicate checks.
    invoice_number = models.CharField(max_length=100, blank=True)
    invoice_number_norm = models.CharField(max_length=100, blank=True)
    invoice_date = models.DateField(null=True, blank=True)
    currency = models.CharField(max_length=3, blank=True)
    total = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    vendor = models.ForeignKey(
        "erp.ErpVendor", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    po = models.ForeignKey(
        "erp.ErpPurchaseOrder", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    # Checks (docs/07): [{"code", "severity", "message", "fields"}], plus the routing decision.
    checks = models.JSONField(default=list, blank=True)
    decision = models.JSONField(default=dict, blank=True)

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    last_edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    erp_bill_id = models.CharField(max_length=40, blank=True)
    erp_url = models.URLField(max_length=300, blank=True)

    class Meta:
        db_table = "invoices"
        indexes = [
            models.Index(fields=["org", "status", "-created_at"], name="invoices_inbox_idx"),
            models.Index(fields=["org", "vendor", "invoice_number_norm"], name="invoices_dup_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.invoice_number or self.id} ({self.status})"
