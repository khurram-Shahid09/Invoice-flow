import pytest
from django.db import DatabaseError, transaction

from accounts.models import Organization
from audit.models import AuditLog
from audit.service import purge, record

pytestmark = pytest.mark.django_db


@pytest.fixture
def org() -> Organization:
    return Organization.objects.create(name="Indus Retail")


def test_audit_rows_cannot_be_updated_or_deleted(org) -> None:
    entry = record("test.event", org=org, actor="system")

    for attempt in (
        lambda: AuditLog.objects.filter(pk=entry.pk).update(action="tampered"),
        lambda: AuditLog.objects.filter(pk=entry.pk).delete(),
    ):
        with pytest.raises(DatabaseError, match="append-only"), transaction.atomic():
            attempt()
    assert AuditLog.objects.get(pk=entry.pk).action == "test.event"


def test_explicit_purge_is_allowed(org) -> None:
    record("test.event", org=org, actor="system")
    assert purge(AuditLog.objects.for_org(org).filter(action="test.event")) == 1
    # the escape hatch is transaction-scoped: afterwards deletes are blocked again
    entry = record("test.event", org=org, actor="system")
    with pytest.raises(DatabaseError), transaction.atomic():
        AuditLog.objects.filter(pk=entry.pk).delete()


def test_record_stores_entity_and_metadata(org) -> None:
    entry = record("org.settings_changed", org=org, entity=org, metadata={"field": "currency"})
    assert entry.actor == "system"
    assert (entry.entity_type, entry.entity_id) == ("organization", org.pk)
    assert entry.metadata == {"field": "currency"}
