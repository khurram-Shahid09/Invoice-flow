"""InvoiceFlow-side vendor settings for the demo company (from infra/odoo/seed_data.json).

``non_po`` and ``category`` belong to InvoiceFlow, not the ERP, so a sync never sets them;
the demo workspace, tests and evals apply them once after the first sync.
"""

import json

from accounts.models import Organization

from .adapters.fake import SEED_FILE
from .models import ErpVendor


def apply_vendor_settings(org: Organization) -> int:
    data = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    updated = 0
    for vendor in data["vendors"]:
        updated += (
            ErpVendor.objects.for_org(org)
            .filter(ref=vendor["ref"])
            .update(non_po=bool(vendor.get("non_po")), category=vendor["category"])
        )
    return updated
