import pytest

from audit.models import AuditLog
from erp.adapters.base import ErpError
from erp.models import ErpConnection, ErpVendor, SyncRun

pytestmark = pytest.mark.django_db


@pytest.fixture
def team(make_account):
    admin = make_account("admin@indus.test", roles=["admin"])
    controller = make_account("controller@indus.test", org=admin.org, roles=["controller"])
    clerk = make_account("clerk@indus.test", org=admin.org, roles=["clerk"])
    return admin, controller, clerk


@pytest.fixture
def synced(team):
    admin, *_ = team
    assert (
        admin.client.put("/api/v1/erp/connection", {"kind": "fake"}, format="json").status_code
        == 200
    )
    assert admin.client.post("/api/v1/erp/sync", {}, format="json").status_code == 202
    return team


def test_admin_connects_odoo_and_the_secret_never_comes_back(team) -> None:
    admin, *_ = team
    response = admin.client.put(
        "/api/v1/erp/connection",
        {
            "kind": "odoo",
            "url": "http://odoo.test",
            "database": "indus",
            "username": "ap-bot@indus.test",
            "secret": "odoo-key-123",
        },
        format="json",
    )
    assert response.status_code == 200
    assert response.data["has_secret"] is True
    assert "secret" not in response.data
    connection = ErpConnection.objects.for_org(admin.org).get()
    assert connection.get_secret() == "odoo-key-123"
    entry = AuditLog.objects.for_org(admin.org).get(action="erp.connection_saved")
    assert entry.metadata["secret_changed"] is True
    assert "odoo-key-123" not in str(entry.metadata)

    # Updating other fields keeps the stored secret.
    admin.client.put("/api/v1/erp/connection", {"database": "indus2"}, format="json")
    connection.refresh_from_db()
    assert (connection.database, connection.get_secret()) == ("indus2", "odoo-key-123")


def test_odoo_needs_url_database_and_user(team) -> None:
    admin, *_ = team
    response = admin.client.put("/api/v1/erp/connection", {"kind": "odoo"}, format="json")
    assert response.status_code == 400
    assert set(response.data["error"]["details"]["fields"]) == {"url", "database", "username"}


def test_only_admins_manage_the_connection(team) -> None:
    _, controller, clerk = team
    for member in (controller, clerk):
        assert member.client.get("/api/v1/erp/connection").status_code == 403
        assert member.client.post("/api/v1/erp/sync", {}, format="json").status_code == 403


def test_not_connected_yet(team) -> None:
    admin, *_ = team
    response = admin.client.get("/api/v1/erp/connection")
    assert response.status_code == 404
    assert response.data["error"]["code"] == "erp_not_connected"


def test_test_connection(team, monkeypatch) -> None:
    admin, *_ = team
    admin.client.put("/api/v1/erp/connection", {"kind": "fake"}, format="json")
    ok = admin.client.post("/api/v1/erp/connection/test")
    assert ok.status_code == 200 and ok.data["company"] == "Indus Retail (Pvt) Ltd"

    def refuse(self):
        raise ErpError("Odoo rejected the API user's credentials.")

    monkeypatch.setattr("erp.adapters.fake.FakeErp.test_connection", refuse)
    failed = admin.client.post("/api/v1/erp/connection/test")
    assert failed.status_code == 502
    assert failed.data["error"] == {
        "code": "erp_error",
        "message": "Odoo rejected the API user's credentials.",
        "details": {},
    }


def test_sync_now_and_sync_history(synced) -> None:
    admin, controller, clerk = synced
    assert ErpVendor.objects.for_org(admin.org).count() == 11
    assert SyncRun.objects.for_org(admin.org).get().status == "ok"
    runs = controller.client.get("/api/v1/erp/sync-runs")
    assert runs.status_code == 200 and runs.data["results"][0]["counts"]["vendors"] == 11
    assert clerk.client.get("/api/v1/erp/sync-runs").status_code == 403


def test_every_member_can_look_up_vendors(synced) -> None:
    *_, clerk = synced
    vendors = clerk.client.get("/api/v1/vendors").data
    assert len(vendors) == 11
    first = vendors[0]
    assert "bank_accounts_enc" not in first and "bank_hashes" not in first
    assert first["bank_masks"][0].startswith("PK")
    found = clerk.client.get("/api/v1/vendors?q=3520117").data
    assert [v["name"] for v in found] == ["Al-Noor Traders"]


def test_controller_marks_a_vendor_non_po(synced) -> None:
    admin, controller, clerk = synced
    vendor = ErpVendor.objects.for_org(admin.org).get(ref="N01")
    url = f"/api/v1/vendors/{vendor.id}"
    response = controller.client.patch(
        url,
        {
            "non_po": True,
            "category": "internet",
            "domains": ["NetLink.test", " billing.netlink.test "],
        },
        format="json",
    )
    assert response.status_code == 200
    assert response.data["domains"] == ["billing.netlink.test", "netlink.test"]
    # read-only fields are ignored
    controller.client.patch(url, {"name": "Hacked", "tax_id": "1"}, format="json")
    vendor.refresh_from_db()
    assert (vendor.non_po, vendor.name) == (True, "NetLink Broadband")
    assert clerk.client.patch(url, {"non_po": False}, format="json").status_code == 403
    assert AuditLog.objects.for_org(admin.org).filter(action="vendor.updated").count() == 2


def test_domains_must_be_domains(synced) -> None:
    admin, controller, _ = synced
    vendor = ErpVendor.objects.for_org(admin.org).get(ref="V01")
    response = controller.client.patch(
        f"/api/v1/vendors/{vendor.id}", {"domains": ["billing@vendor.test"]}, format="json"
    )
    assert response.status_code == 400
