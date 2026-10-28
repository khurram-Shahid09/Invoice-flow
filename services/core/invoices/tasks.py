"""The pipeline (docs/03 "Data flow"): read -> check -> route -> post. Each task is idempotent:
it checks the invoice's status first, so a repeated delivery does nothing."""

import logging
from datetime import date
from decimal import Decimal

from celery import shared_task
from django.utils import timezone

from accounts.models import User
from checks import rules
from erp.adapters.base import BillDraft, BillLine, ErpError
from erp.models import ErpConnection
from erp.sync import adapter_for
from extraction.providers import ExtractionError
from extraction.service import read_invoice

from .documents import render
from .models import Invoice
from .state import transition

log = logging.getLogger(__name__)
S = Invoice.Status
ROUTES = {"review": S.NEEDS_REVIEW, "approval": S.AWAITING_APPROVAL, "straight_through": S.APPROVED}


@shared_task(name="extract.process_invoice")
def process_invoice(invoice_id: str) -> None:
    invoice = Invoice.objects.select_related("document", "org").get(pk=invoice_id)
    if invoice.status not in (S.RECEIVED, S.EXTRACTION_FAILED):
        return
    transition(invoice, S.EXTRACTING)
    try:
        render(invoice.document)
        read_invoice(invoice)
    except ExtractionError as exc:
        transition(invoice, S.EXTRACTION_FAILED, reason=str(exc))
        return
    doc_type = invoice.extraction.get("document_type")
    if doc_type != "invoice":
        transition(invoice, S.NOT_INVOICE, reason=f"This looks like a {doc_type}, not an invoice.")
        return
    apply_checks(invoice)


def apply_checks(invoice: Invoice, actor: User | None = None) -> None:
    outcome = rules.run(invoice)
    invoice.checks, invoice.decision = outcome.as_json()
    invoice.save(update_fields=["checks", "decision", "vendor", "po", "updated_at"])
    target = ROUTES[outcome.route]
    transition(invoice, target, actor=actor, reason=outcome.reasons[0] if outcome.reasons else "")
    if target == S.APPROVED:
        invoice.decided_at = timezone.now()
        invoice.save(update_fields=["decided_at"])
        post_invoice.delay(invoice.id)


def _bill(invoice: Invoice) -> BillDraft:
    assert invoice.vendor is not None and invoice.invoice_date is not None
    fields = invoice.fields
    subtotal = Decimal(fields["subtotal"]["value"] or 0)
    tax = Decimal(fields["tax_total"]["value"] or 0)
    doc_rate = (tax / subtotal * 100).quantize(Decimal(1)) if subtotal else None
    po_lines = list(invoice.po.lines.all()) if invoice.po else []
    lines = []
    for line in invoice.lines:
        po_line = rules._match_line(line, po_lines) if po_lines else None
        rate = line.get("tax_rate_pct", {}).get("value")
        lines.append(
            BillLine(
                description=line["description"]["value"] or "Item",
                quantity=Decimal(line["quantity"]["value"] or 1),
                unit_price=Decimal(line["unit_price"]["value"] or 0),
                tax_rate=Decimal(rate) if rate else doc_rate,
                po_line_erp_id=po_line.erp_id if po_line else None,
            )
        )
    due = fields.get("due_date", {}).get("value")
    document = invoice.document
    return BillDraft(
        vendor_erp_id=invoice.vendor.erp_id,
        ref=invoice.invoice_number,
        invoice_date=invoice.invoice_date,
        due_date=date.fromisoformat(due) if due else None,
        currency=invoice.currency,
        lines=tuple(lines),
        attachment_name=document.filename,
        attachment=document.file.open("rb").read(),
        attachment_mime=document.mime,
    )


@shared_task(name="post.post_invoice")
def post_invoice(invoice_id: str) -> None:
    invoice = Invoice.objects.select_related("document", "org", "vendor", "po").get(pk=invoice_id)
    if invoice.status not in (S.APPROVED, S.POSTING_FAILED):
        return
    transition(invoice, S.POSTING)
    connection = ErpConnection.objects.for_org(invoice.org).first()
    if connection is None:
        transition(invoice, S.POSTING_FAILED, reason="No ERP is connected.")
        return
    try:
        posted = adapter_for(connection).create_bill(_bill(invoice))
    except ErpError as exc:
        log.warning("Posting %s failed: %s", invoice.id, exc)
        transition(invoice, S.POSTING_FAILED, reason=str(exc))
        return
    invoice.erp_bill_id, invoice.erp_url = posted.erp_id, posted.url
    invoice.save(update_fields=["erp_bill_id", "erp_url", "updated_at"])
    note = "Bill created in the ERP." if posted.created else "Bill already existed in the ERP."
    transition(invoice, S.POSTED, reason=note)
