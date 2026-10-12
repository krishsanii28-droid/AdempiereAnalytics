"""Integration tests. They run against the live ADempiere database through the insightai views,
so they assert rules that must hold for any data, not specific GardenWorld amounts.

    .venv\\Scripts\\python.exe -m pytest
"""
import pytest
from fastapi.testclient import TestClient

from insightai import auth, db
from insightai.main import app

ALL_TIME = {"date_from": "2000-01-01"}


def _login(user_name: str, role_name: str) -> TestClient:
    row = db.query_one(
        "SELECT ad_user_id::int AS uid, ad_role_id::int AS rid FROM v_user_role "
        "WHERE user_name = %(u)s AND role_name = %(r)s", {"u": user_name, "r": role_name})
    if not row:
        pytest.skip(f"{user_name} / {role_name} does not exist in this database")
    client = TestClient(app, follow_redirects=False)
    assert client.get("/dev/login", params={"user_id": row["uid"], "role_id": row["rid"]}).status_code == 303
    return client


@pytest.fixture(scope="module")
def admin() -> TestClient:
    return _login("GardenAdmin", "GardenWorld Admin")


@pytest.fixture(scope="module")
def restricted() -> TestClient:
    return _login("test_salerep", "SalesRep(Restricted)")


def _cards(client: TestClient, **params) -> dict:
    response = client.get("/api/kpis", params=params)
    assert response.status_code == 200, response.text
    return {c["id"]: c for c in response.json()["cards"]}


# ---- authentication -------------------------------------------------------------------

def test_api_requires_a_session():
    client = TestClient(app)
    assert client.get("/api/kpis").status_code == 401
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/charts/sales_monthly").status_code == 401


def test_tampered_and_expired_tokens_are_rejected():
    good = auth.issue_token(101, 102, 60)
    payload, signature = good.split(".")
    assert auth.read_token(good) == (101, 102)
    assert auth.read_token(payload + "." + signature[::-1]) is None
    assert auth.read_token(auth.issue_token(101, 102, -1)) is None
    assert auth.read_token("not-a-token") is None
    client = TestClient(app)
    client.cookies.set(auth.COOKIE, payload + "." + signature[::-1])
    assert client.get("/api/kpis").status_code == 401


def test_cannot_log_in_with_a_role_the_user_does_not_hold():
    row = db.query_one("SELECT ad_user_id::int AS uid FROM v_user_role WHERE user_name = 'test_salerep'")
    admin_role = db.query_one("SELECT ad_role_id::int AS rid FROM v_user_role WHERE role_name = 'GardenWorld Admin'")
    if not row or not admin_role:
        pytest.skip("test users not present")
    client = TestClient(app, follow_redirects=False)
    assert client.get("/dev/login", params={"user_id": row["uid"], "role_id": admin_role["rid"]}).status_code == 403


# ---- organisation restrictions ----------------------------------------------------------

def test_restricted_role_sees_only_its_organisations(admin, restricted):
    admin_orgs = {o["id"] for o in admin.get("/api/me").json()["filters"]["orgs"]}
    own_orgs = {o["id"] for o in restricted.get("/api/me").json()["filters"]["orgs"]}
    assert own_orgs and own_orgs < admin_orgs

    other_org = next(iter(admin_orgs - own_orgs))
    assert restricted.get("/api/kpis", params={"org_id": other_org}).status_code == 403
    assert restricted.get("/api/charts/sales_monthly", params={"org_id": other_org}).status_code == 403

    other_warehouse = next(w["id"] for w in admin.get("/api/me").json()["filters"]["warehouses"] if w["org_id"] not in own_orgs)
    assert restricted.get("/api/kpis", params={"warehouse_id": other_warehouse}).status_code == 403


def test_restricted_totals_equal_admin_totals_for_the_same_organisations(admin, restricted):
    own_orgs = [o["id"] for o in restricted.get("/api/me").json()["filters"]["orgs"]]
    mine = _cards(restricted, **ALL_TIME)
    for card_id in ("sales", "purchases", "receivables", "inventory"):
        as_admin = sum(_cards(admin, org_id=org, **ALL_TIME)[card_id]["value"] or 0 for org in own_orgs)
        assert mine[card_id]["value"] == pytest.approx(as_admin), card_id


def test_organisation_filter_partitions_the_total(admin):
    orgs = [o["id"] for o in admin.get("/api/me").json()["filters"]["orgs"]]
    total = _cards(admin, **ALL_TIME)
    for card_id in ("sales", "purchases", "receivables", "overdue"):
        parts = sum(_cards(admin, org_id=org, **ALL_TIME)[card_id]["value"] for org in orgs)
        assert parts == pytest.approx(total[card_id]["value"]), card_id


# ---- consistency between figures --------------------------------------------------------

def test_kpi_totals_match_their_charts(admin):
    cards = _cards(admin, **ALL_TIME)
    monthly = admin.get("/api/charts/sales_monthly", params=ALL_TIME).json()["rows"]
    assert sum(r["amount"] for r in monthly) == pytest.approx(cards["sales"]["value"])
    purchases = admin.get("/api/charts/purchases_monthly", params=ALL_TIME).json()["rows"]
    assert sum(r["amount"] for r in purchases) == pytest.approx(cards["purchases"]["value"])
    aging = admin.get("/api/charts/receivables_aging").json()["rows"]
    assert sum(r["amount"] for r in aging) == pytest.approx(cards["receivables"]["value"])
    assert sum(r["amount"] for r in aging if r["bucket"] != "Not due") == pytest.approx(cards["overdue"]["value"])
    by_warehouse = admin.get("/api/charts/inventory_by_warehouse").json()["rows"]
    assert sum(r["value"] for r in by_warehouse) == pytest.approx(cards["inventory"]["value"])


def test_filters_a_view_cannot_apply_are_reported(admin):
    warehouse = admin.get("/api/me").json()["filters"]["warehouses"][0]["id"]
    cards = _cards(admin, warehouse_id=warehouse)
    assert "warehouse" in cards["sales"]["ignored"]          # invoices carry no warehouse
    assert "warehouse" not in cards["inventory"]["ignored"]
    chart = admin.get("/api/charts/sales_by_product", params={"warehouse_id": warehouse}).json()
    assert chart["ignored"] == ["warehouse"]


# ---- empty data and bad input -----------------------------------------------------------

def test_period_without_documents_is_empty_not_an_error(admin):
    params = {"date_from": "1990-01-01", "date_to": "1990-12-31"}
    cards = _cards(admin, **params)
    assert cards["sales"]["value"] == 0 and cards["sales"]["delta"] is None
    assert cards["turnover"]["available"] is False and cards["turnover"]["reason"]
    assert cards["supplier_on_time"]["available"] is False
    assert admin.get("/api/charts/sales_monthly", params=params).json()["rows"] == []
    assert admin.get("/api/charts/sales_by_product", params=params).json()["rows"] == []


@pytest.mark.parametrize("params, status", [
    ({"date_from": "not-a-date"}, 422),
    ({"date_from": "2026-10-01", "date_to": "2026-01-01"}, 422),
    ({"org_id": "11; DROP TABLE c_invoice"}, 422),
    ({"category_id": 999999999}, 422),
    ({"bpartner_id": 999999999}, 422),
    ({"org_id": 999999999}, 403),
])
def test_bad_input_is_rejected(admin, params, status):
    assert admin.get("/api/kpis", params=params).status_code == status


def test_unknown_chart_is_404(admin):
    assert admin.get("/api/charts/does_not_exist").status_code == 404


def test_every_chart_responds(admin):
    from insightai.queries import CHARTS
    for name in CHARTS:
        body = admin.get(f"/api/charts/{name}", params=ALL_TIME)
        assert body.status_code == 200, name
        assert {"rows", "basis", "period", "ignored", "notes"} <= body.json().keys(), name


def test_database_failure_becomes_503(admin, monkeypatch):
    def down(*_args, **_kwargs):
        raise db.DatabaseUnavailable("The ADempiere database is not reachable.")
    monkeypatch.setattr(db, "query", down)
    response = admin.get("/api/charts/sales_monthly")
    assert response.status_code == 503 and "not reachable" in response.json()["detail"]
