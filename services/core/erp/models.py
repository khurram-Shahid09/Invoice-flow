"""The org's ERP connection and a local mirror of its master data (docs/09, docs/10).

Checks read these tables, never the ERP directly: fast, testable, and they keep working while
the ERP is down. ``erp/sync.py`` is the only writer of the mirrored fields; fields marked
"local" belong to InvoiceFlow and survive every sync.
"""

from django.contrib.postgres.fields import ArrayField
from django.db import models

from common import crypto
from common.ids import PrefixedIdField
from common.models import TimeStampedModel
from common.tenancy import OrgOwnedModel


class ErpConnection(OrgOwnedModel, TimeStampedModel):
    class Kind(models.TextChoices):
        ODOO = "odoo"
        FAKE = "fake"  # in-memory seed data, for demos without an ERP

    class Status(models.TextChoices):
        NEVER = "never"
        OK = "ok"
        FAILED = "failed"

    id = PrefixedIdField(prefix="erp")
    org = models.OneToOneField(
        "accounts.Organization", on_delete=models.CASCADE, related_name="erp_connection"
    )
    kind = models.CharField(max_length=10, choices=Kind.choices)
    url = models.URLField(blank=True)
    database = models.CharField(max_length=100, blank=True)
    username = models.CharField(max_length=200, blank=True)
    secret_enc = models.TextField(blank=True)  # API key, encrypted (common/crypto.py)
    # Per-kind high-water marks for incremental sync: {"vendors": "2026-10-28T08:00:00+00:00"}.
    sync_state = models.JSONField(default=dict, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=10, choices=Status.choices, default="never")
    last_error = models.TextField(blank=True)

    class Meta:
        db_table = "erp_connections"

    def __str__(self) -> str:
        return f"{self.kind} for {self.org_id}"

    def set_secret(self, secret: str) -> None:
        self.secret_enc = crypto.encrypt(secret, org_id=self.org_id) if secret else ""

    def get_secret(self) -> str:
        return crypto.decrypt(self.secret_enc, org_id=self.org_id) if self.secret_enc else ""


class SyncRun(OrgOwnedModel):
    class Status(models.TextChoices):
        RUNNING = "running"
        OK = "ok"
        FAILED = "failed"

    id = PrefixedIdField(prefix="syn")
    full = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RUNNING)
    counts = models.JSONField(default=dict, blank=True)  # {"vendors": 3, "purchase_orders": 1}
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "erp_sync_runs"
        indexes = [models.Index(fields=["org", "-started_at"], name="sync_runs_org_started_idx")]

    def __str__(self) -> str:
        return f"{self.org_id} {self.started_at:%Y-%m-%d %H:%M} {self.status}"


class MirrorModel(OrgOwnedModel, TimeStampedModel):
    erp_id = models.CharField(max_length=40)

    class Meta:
        abstract = True


class ErpVendor(MirrorModel):
    id = PrefixedIdField(prefix="ven")
    name = models.CharField(max_length=255)
    ref = models.CharField(max_length=64, blank=True)
    tax_id = models.CharField(max_length=64, blank=True)
    tax_id_norm = models.CharField(max_length=64, blank=True, db_index=True)
    email = models.CharField(max_length=254, blank=True)
    city = models.CharField(max_length=100, blank=True)
    currency = models.CharField(max_length=3, blank=True)
    # Bank accounts: encrypted values, HMAC index for exact matching, masked for display.
    bank_accounts_enc = ArrayField(models.TextField(), default=list, blank=True)
    bank_hashes = ArrayField(models.CharField(max_length=64), default=list, blank=True)
    bank_masks = ArrayField(models.CharField(max_length=40), default=list, blank=True)
    active = models.BooleanField(default=True)
    erp_updated_at = models.DateTimeField(null=True, blank=True)
    # local: set by people in InvoiceFlow, never overwritten by sync
    domains = ArrayField(models.CharField(max_length=253), default=list, blank=True)
    non_po = models.BooleanField(default=False, help_text="Bills without a purchase order")
    category = models.CharField(max_length=60, blank=True)

    class Meta:
        db_table = "erp_vendors"
        constraints = [
            models.UniqueConstraint(fields=["org", "erp_id"], name="erp_vendors_org_erp_id_uniq")
        ]

    def __str__(self) -> str:
        return self.name


class ErpPurchaseOrder(MirrorModel):
    id = PrefixedIdField(prefix="po")
    number = models.CharField(max_length=64)
    vendor = models.ForeignKey(
        ErpVendor, on_delete=models.SET_NULL, null=True, related_name="purchase_orders"
    )
    vendor_erp_id = models.CharField(max_length=40)
    state = models.CharField(max_length=20)
    currency = models.CharField(max_length=3, blank=True)
    vendor_ref = models.CharField(max_length=64, blank=True)
    order_date = models.DateField(null=True, blank=True)
    requester = models.CharField(max_length=200, blank=True)
    amount_total = models.DecimalField(max_digits=18, decimal_places=4)
    erp_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "erp_purchase_orders"
        constraints = [
            models.UniqueConstraint(fields=["org", "erp_id"], name="erp_pos_org_erp_id_uniq")
        ]
        indexes = [models.Index(fields=["org", "number"], name="erp_pos_org_number_idx")]

    def __str__(self) -> str:
        return self.number


class ErpPurchaseOrderLine(MirrorModel):
    id = PrefixedIdField(prefix="pol")
    po = models.ForeignKey(ErpPurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    position = models.PositiveIntegerField(default=0)
    product_code = models.CharField(max_length=64, blank=True)
    description = models.TextField(blank=True)
    uom = models.CharField(max_length=40, blank=True)
    qty_ordered = models.DecimalField(max_digits=18, decimal_places=4)
    qty_received = models.DecimalField(max_digits=18, decimal_places=4)
    qty_invoiced = models.DecimalField(max_digits=18, decimal_places=4)
    unit_price = models.DecimalField(max_digits=18, decimal_places=4)
    tax_rate = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True)

    class Meta:
        db_table = "erp_purchase_order_lines"
        ordering = ["position"]
        constraints = [
            models.UniqueConstraint(fields=["org", "erp_id"], name="erp_po_lines_org_erp_id_uniq")
        ]

    def __str__(self) -> str:
        return f"{self.po_id} {self.product_code or self.description[:30]}"


class ErpReceipt(MirrorModel):
    id = PrefixedIdField(prefix="grn")
    number = models.CharField(max_length=64)
    po = models.ForeignKey(
        ErpPurchaseOrder, on_delete=models.SET_NULL, null=True, related_name="receipts"
    )
    state = models.CharField(max_length=20)
    done_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "erp_receipts"
        constraints = [
            models.UniqueConstraint(fields=["org", "erp_id"], name="erp_receipts_org_erp_id_uniq")
        ]

    def __str__(self) -> str:
        return self.number


class ErpAccount(MirrorModel):
    id = PrefixedIdField(prefix="acc")
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=40, blank=True)

    class Meta:
        db_table = "erp_accounts"
        constraints = [
            models.UniqueConstraint(fields=["org", "erp_id"], name="erp_accounts_org_erp_id_uniq")
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.name}"


class ErpTax(MirrorModel):
    id = PrefixedIdField(prefix="tax")
    name = models.CharField(max_length=255)
    rate = models.DecimalField(max_digits=7, decimal_places=4)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "erp_taxes"
        constraints = [
            models.UniqueConstraint(fields=["org", "erp_id"], name="erp_taxes_org_erp_id_uniq")
        ]

    def __str__(self) -> str:
        return self.name


class ErpBillRef(MirrorModel):
    """A bill that already exists in the ERP, for duplicate checks."""

    id = PrefixedIdField(prefix="bil")
    vendor = models.ForeignKey(ErpVendor, on_delete=models.SET_NULL, null=True, related_name="+")
    vendor_erp_id = models.CharField(max_length=40)
    ref = models.CharField(max_length=128, blank=True)
    ref_norm = models.CharField(max_length=128, blank=True)
    total = models.DecimalField(max_digits=18, decimal_places=4)
    currency = models.CharField(max_length=3, blank=True)
    bill_date = models.DateField(null=True, blank=True)
    state = models.CharField(max_length=20)

    class Meta:
        db_table = "erp_bill_refs"
        constraints = [
            models.UniqueConstraint(fields=["org", "erp_id"], name="erp_bills_org_erp_id_uniq")
        ]
        indexes = [models.Index(fields=["org", "vendor", "ref_norm"], name="erp_bills_dup_idx")]

    def __str__(self) -> str:
        return self.ref or self.erp_id
