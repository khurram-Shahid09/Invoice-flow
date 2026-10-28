"""The invoice lifecycle (docs/03 "state machine"). ``transition`` is the only writer of status."""

from accounts.models import User
from audit.service import record

from .models import Invoice

S = Invoice.Status
ALLOWED: dict[str, set[str]] = {
    S.RECEIVED: {S.EXTRACTING, S.NOT_INVOICE},
    S.EXTRACTING: {
        S.NEEDS_REVIEW,
        S.AWAITING_APPROVAL,
        S.APPROVED,
        S.EXTRACTION_FAILED,
        S.NOT_INVOICE,
    },
    S.EXTRACTION_FAILED: {S.EXTRACTING, S.NEEDS_REVIEW},
    S.NEEDS_REVIEW: {S.NEEDS_REVIEW, S.AWAITING_APPROVAL, S.APPROVED, S.REJECTED, S.EXTRACTING},
    S.AWAITING_APPROVAL: {S.APPROVED, S.REJECTED, S.NEEDS_REVIEW, S.AWAITING_APPROVAL},
    S.APPROVED: {S.POSTING},
    S.POSTING: {S.POSTED, S.POSTING_FAILED},
    S.POSTING_FAILED: {S.POSTING},
    S.REJECTED: set(),
    S.POSTED: set(),
    S.NOT_INVOICE: set(),
}


class TransitionError(Exception):
    pass


def transition(invoice: Invoice, to: str, *, actor: User | None = None, reason: str = "") -> None:
    if to not in ALLOWED[invoice.status]:
        raise TransitionError(f"{invoice.status} -> {to} is not allowed")
    before = invoice.status
    invoice.status, invoice.status_reason = to, reason[:300]
    invoice.save(update_fields=["status", "status_reason", "updated_at"])
    record(
        "invoice.status_changed",
        org=invoice.org,
        entity=invoice,
        actor=f"user:{actor.pk}" if actor else "system",
        metadata={"from": before, "to": to, "reason": reason},
    )
