"""Read an invoice: pages -> AI -> grounded, normalised fields stored on the invoice."""

from decimal import Decimal

from common.text import normalize_invoice_number
from invoices.models import Invoice

from . import normalize
from .grounding import ground
from .providers import extract
from .schema import HEADER_FIELDS, LINE_FIELDS, Value

AMOUNTS = {"subtotal", "tax_total", "shipping", "total"}
LINE_AMOUNTS = {"quantity", "unit_price", "tax_rate_pct", "line_total"}


def _typed(name: str, raw: str | None, org) -> str | None:
    """The comparable form stored alongside the printed value (dates ISO, amounts plain)."""
    if raw is None:
        return None
    if name in AMOUNTS or name in LINE_AMOUNTS:
        amount = normalize.amount(raw)
        return None if amount is None else str(amount)
    if name in ("invoice_date", "due_date"):
        parsed = normalize.parse_date(raw, org.date_format)
        return parsed.isoformat() if parsed else None
    if name == "currency":
        return normalize.currency(raw, org.base_currency)
    return raw.strip()


def _evidence(name: str, item: Value, pages: list[list[dict]], trusted: bool, org) -> dict:
    if trusted:
        typed = _typed(name, item.value, org)
        return {
            "value": typed,
            "printed": item.value,
            "page": item.page,
            "grounding": "answer_key" if typed is not None else "absent",
            "trust": "high",
        }
    found = ground(item.value, item.page, item.quote, pages)
    typed = _typed(name, found.get("value"), org)
    if (
        found["grounding"] in ("exact", "fuzzy", "model_only")
        and typed is None
        and name != "currency"
    ):
        found = {**found, "value": None, "rejected": found.get("value"), "grounding": "unparseable"}
    trust = {"exact": "high", "fuzzy": "medium", "model_only": "medium"}.get(
        found["grounding"], "low"
    )
    return {**found, "printed": found.get("value"), "value": typed, "trust": trust}


def read_invoice(invoice: Invoice) -> None:
    document = invoice.document
    pages = list(document.pages.all())
    images = [p.image.open("rb").read() for p in pages]
    words = [p.words for p in pages]
    texts = [" ".join(w["t"] for w in ws) for ws in words]
    result = extract(images, texts, document.filename)
    data = result.extraction
    org = invoice.org

    fields = {
        name: _evidence(name, getattr(data, name), words, result.trusted, org)
        for name in HEADER_FIELDS
    }
    if fields["currency"]["value"] is None:
        fields["currency"]["value"] = org.base_currency
    lines = [
        {
            name: _evidence(name, getattr(line, name), words, result.trusted, org)
            for name in LINE_FIELDS
        }
        for line in data.lines
    ]
    invoice.fields, invoice.lines = fields, lines
    invoice.extraction = {
        "provider": result.provider,
        "model": result.model,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "ms": result.ms,
        "document_type": data.document_type,
        "notes": data.notes_for_reviewer,
        **result.meta,
    }
    number = fields["invoice_number"]["value"] or ""
    invoice.invoice_number = number[:100]
    invoice.invoice_number_norm = normalize_invoice_number(number)[:100]
    invoice.invoice_date = normalize.parse_date(fields["invoice_date"]["value"])
    invoice.currency = fields["currency"]["value"] or ""
    total = fields["total"]["value"]
    invoice.total = Decimal(total) if total is not None else None
    invoice.save()
