"""End to end with the offline provider and the fake ERP: upload the five demo invoices,
check where each lands, approve one and see it posted. Needs the generated eval files
(cd evals && uv run python -m invoicegen.generate --only demo); skipped without them."""

from pathlib import Path

import pytest
from django.conf import settings as django_settings

from audit.models import AuditLog
from erp.demo import apply_vendor_settings
from erp.models import ErpConnection
from erp.sync import sync_connection
from invoices.models import Invoice

pytestmark = pytest.mark.django_db
FILES = Path(django_settings.REPO_ROOT) / "evals" / "data" / "generated" / "files"
DEMO = [
    "INV-2291.pdf",
    "photo-gulf-packaging.jpg",
    "netlink-internet-oct.pdf",
    "INV2291-resent.pdf",
    "mehran-steel-new-bank.pdf",
]


@pytest.fixture
def team(make_account, settings, tmp_path):
    if not all((FILES / name).is_file() for name in DEMO):
        pytest.skip("generate the demo invoices first (evals)")
    settings.MEDIA_ROOT, settings.LLM_PROVIDER = tmp_path, "fake"
    clerk = make_account("clerk@indus.test", roles=["clerk"])
    approver = make_account("approver@indus.test", org=clerk.org, roles=["approver", "controller"])
    sync_connection(ErpConnection.objects.create(org=clerk.org, kind="fake"))
    apply_vendor_settings(clerk.org)
    return clerk, approver


def upload(client, name: str) -> str:
    with open(FILES / name, "rb") as f:
        response = client.post("/api/v1/documents", {"files": [f]}, format="multipart")
    assert response.status_code == 201, response.content
    return response.data["invoices"][0]["invoice"]


def test_demo_invoices_land_where_the_demo_script_says(
    team, django_capture_on_commit_callbacks
) -> None:
    clerk, approver = team
    ids = {}
    for name in DEMO:
        with django_capture_on_commit_callbacks(execute=True):
            ids[name] = upload(clerk.client, name)
    status = {name: Invoice.objects.get(pk=i).status for name, i in ids.items()}
    assert status == {
        "INV-2291.pdf": "awaiting_approval",
        "photo-gulf-packaging.jpg": "posted",  # straight through, then posted
        "netlink-internet-oct.pdf": "posted",
        "INV2291-resent.pdf": "needs_review",  # duplicate of INV-2291
        "mehran-steel-new-bank.pdf": "needs_review",
    }
    resent = Invoice.objects.get(pk=ids["INV2291-resent.pdf"])
    assert {c["code"] for c in resent.checks} >= {"DUP_EXACT"}
    bank = Invoice.objects.get(pk=ids["mehran-steel-new-bank.pdf"])
    assert {c["code"] for c in bank.checks} >= {"BANK_CHANGED", "HIDDEN_TEXT"}

    detail = clerk.client.get(f"/api/v1/invoices/{ids['INV-2291.pdf']}").data
    assert detail["fields"]["total"]["value"] == "148562.00" and detail["po_number"] == "P00001"
    assert clerk.client.get(f"/api/v1/invoices/{ids['INV-2291.pdf']}/pages/2").status_code == 200

    # The clerk who uploaded it can't approve; the approver can, and it gets posted.
    assert (
        clerk.client.post(
            f"/api/v1/invoices/{ids['INV-2291.pdf']}/decision",
            {"decision": "approve"},
            format="json",
        ).status_code
        == 403
    )
    approved = approver.client.post(
        f"/api/v1/invoices/{ids['INV-2291.pdf']}/decision", {"decision": "approve"}, format="json"
    )
    assert approved.status_code == 200 and approved.data["status"] == "posted"
    assert approved.data["erp_url"].startswith("fake://bills/")
    assert AuditLog.objects.for_org(clerk.org).filter(action="invoice.status_changed").count() >= 15


def test_same_file_twice_is_linked_not_reprocessed(
    team, django_capture_on_commit_callbacks
) -> None:
    clerk, _ = team
    with django_capture_on_commit_callbacks(execute=True):
        first = upload(clerk.client, "INV-2291.pdf")
    with open(FILES / "INV-2291.pdf", "rb") as f:
        response = clerk.client.post("/api/v1/documents", {"files": [f]}, format="multipart")
    assert response.data["invoices"][0] == {
        "invoice": first,
        "filename": "INV-2291.pdf",
        "duplicate_file": True,
    }


def test_clerk_fixes_a_field_and_checks_run_again(team, django_capture_on_commit_callbacks) -> None:
    clerk, approver = team
    with django_capture_on_commit_callbacks(execute=True):
        invoice_id = upload(clerk.client, "INV2291-resent.pdf")  # alone, it's not a duplicate
    assert Invoice.objects.get(pk=invoice_id).status == "awaiting_approval"
    edited = clerk.client.patch(
        f"/api/v1/invoices/{invoice_id}/fields", {"values": {"total": "1.00"}}, format="json"
    )
    assert edited.data["status"] == "needs_review"
    assert any(c["code"] == "MATH_TOTAL" for c in edited.data["checks"])
    rejected = approver.client.post(
        f"/api/v1/invoices/{invoice_id}/decision",
        {"decision": "reject", "reason": "Wrong total"},
        format="json",
    )
    assert rejected.data["status"] == "rejected"
