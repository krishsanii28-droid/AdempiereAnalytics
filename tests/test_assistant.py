"""Assistant tests: parameter extraction, refusal of unsafe and unsupported input, organisation
restrictions, and answers checked against SQL written by hand for the test (not the assistant's own)."""
from datetime import date

import pytest
from assistant_questions import SQL_SHAPED, SUPPORTED, TEST_SUPPORTED, TEST_UNSUPPORTED, UNSUPPORTED
from fastapi.testclient import TestClient

from insightai import auth, db
from insightai.assistant import engine, matcher, params
from insightai.assistant.intents import BY_ID, INTENTS
from insightai.main import app

TODAY = date(2026, 10, 12)


def _session(user: str, role: str):
    row = db.query_one("SELECT ad_user_id::int AS uid, ad_role_id::int AS rid FROM v_user_role "
                       "WHERE user_name = %(u)s AND role_name = %(r)s", {"u": user, "r": role})
    if not row:
        pytest.skip(f"{user} / {role} not present")
    return auth.load_session(row["uid"], row["rid"])


@pytest.fixture(scope="module")
def admin():
    return _session("GardenAdmin", "GardenWorld Admin")


@pytest.fixture(scope="module")
def restricted():
    return _session("test_salerep", "SalesRep(Restricted)")


def _sql(query: str, session, **extra):
    return db.query(query, {"client": session.client_id, "orgs": list(session.org_ids), **extra})


# ---- periods and top-N ------------------------------------------------------------------

@pytest.mark.parametrize("text, start, end", [
    ("top products last month", date(2026, 9, 1), date(2026, 9, 30)),
    ("sales this month", date(2026, 10, 1), TODAY),
    ("sales last quarter", date(2026, 7, 1), date(2026, 9, 30)),
    ("sales this quarter", date(2026, 10, 1), TODAY),
    ("sales this year", date(2026, 1, 1), TODAY),
    ("sales last year", date(2025, 1, 1), date(2025, 12, 31)),
    ("sales in the last 30 days", date(2026, 9, 12), TODAY),
    ("sales in the past six months", date(2026, 4, 12), TODAY),
    ("sales in 2025", date(2025, 1, 1), date(2025, 12, 31)),
    ("sales in 2026", date(2026, 1, 1), TODAY),                     # a year in progress stops today
    ("sales in September", date(2026, 9, 1), date(2026, 9, 30)),
    ("sales in December", date(2025, 12, 1), date(2025, 12, 31)),   # a month still to come means last year's
    ("sales during June 2019", date(2019, 6, 1), date(2019, 6, 30)),
    ("sales since June", date(2026, 6, 1), TODAY),
    ("sales of all time", date(2000, 1, 1), TODAY),
])
def test_periods(text, start, end):
    period = params.parse_period(text, TODAY)
    assert period is not None and (period.start, period.end) == (start, end)


def test_no_period_means_none_and_the_default_is_marked_as_unstated():
    assert params.parse_period("what are our top products", TODAY) is None
    default = params.default_period(TODAY, 12)
    assert (default.start, default.end, default.stated) == (date(2025, 11, 1), TODAY, False)


@pytest.mark.parametrize("text, expected", [
    ("top five products", (5, True)), ("top 10 customers", (10, True)), ("the three best selling items", (3, True)),
    ("top 500 products", (50, True)), ("best products", (5, False)), ("sales in the last 30 days", (5, False)),
])
def test_top_n(text, expected):
    assert params.parse_top_n(text, default=5, maximum=50) == expected


# ---- names ------------------------------------------------------------------------------

PRODUCTS = [{"id": 1, "name": "Oak Tree"}, {"id": 2, "name": "Patio Sun Screen"}, {"id": 3, "name": "Fertilizer #50"}]
PARTNERS = [{"id": 10, "name": "Joe Block"}, {"id": 11, "name": "Seed Farm Inc."}, {"id": 12, "name": "Patio Fun, Inc."}]


def test_names_are_found_exactly_without_suffix_and_by_close_spelling():
    product, partner = params.find_entities("how many Oak Tree did Joe Block buy", PRODUCTS, PARTNERS)
    assert (product.id, product.exact, partner.id, partner.exact) == (1, True, 10, True)
    assert params.find_entities("sales to seed farm", PRODUCTS, PARTNERS)[1].id == 11
    close = params.find_entities("sales to Joe Blok", PRODUCTS, PARTNERS)[1]
    assert close.id == 10 and close.exact is False


def test_a_product_name_is_not_also_read_as_a_similar_customer():
    product, partner = params.find_entities("revenue from Patio Sun Screen", PRODUCTS, PARTNERS)
    assert product.id == 2 and partner is None


def test_unknown_names_are_not_matched():
    assert params.find_entities("how many widgets did Acme buy", PRODUCTS, PARTNERS) == (None, None)


# ---- unsafe and unsupported input ---------------------------------------------------------

@pytest.mark.parametrize("text", SQL_SHAPED)
def test_sql_shaped_input_is_refused_before_matching(admin, text, monkeypatch):
    def must_not_run(*_args, **_kwargs):
        raise AssertionError("the matcher or database was reached")
    monkeypatch.setattr(matcher, "match", must_not_run)
    monkeypatch.setattr(db, "query", must_not_run)
    response = engine.ask(admin, text)
    assert response["supported"] is False and "does not run SQL" in response["answer"] and "rows" not in response


def test_ordinary_questions_are_not_mistaken_for_sql():
    for question, _ in SUPPORTED + TEST_SUPPORTED:
        assert not params.looks_like_sql(question), question


def test_empty_and_overlong_questions_are_declined(admin):
    assert engine.ask(admin, "  ")["supported"] is False
    assert engine.ask(admin, "sales " * 100)["supported"] is False


def test_development_questions_match_as_expected():
    """Guards against regressions on the questions the matcher was tuned with (model required)."""
    client_id = db.query_one("SELECT MIN(ad_client_id)::int AS id FROM v_org")["id"]
    products, partners = engine._entities(type("S", (), {"client_id": client_id})())
    if matcher.match("warm up").matcher != "minilm":
        pytest.skip("embedding model not available")
    wrong = []
    for question, wanted in SUPPORTED:
        text, _, _, eligible = engine.prepare(question, products, partners)
        got = matcher.match(text, eligible=eligible)
        if got.intent_id not in (wanted, None):          # declining is acceptable, a wrong answer is not
            wrong.append((question, got.intent_id))
    assert wrong == []
    for question in UNSUPPORTED:
        text, product, partner, eligible = engine.prepare(question, products, partners)
        got = matcher.match(text, eligible=eligible)
        found = {"product": product, "bpartner": partner}
        answered = got.intent_id is not None and all(found[n] is not None for n in BY_ID[got.intent_id].requires)
        assert not answered, question


def test_unsupported_test_questions_are_declined_end_to_end(admin):
    for question in TEST_UNSUPPORTED:
        response = engine.ask(admin, question)
        assert response["supported"] is False, question
        assert response["supported_questions"], question


def test_keyword_fallback_declines_rather_than_guesses(admin):
    for question in UNSUPPORTED + TEST_UNSUPPORTED:
        assert engine.ask(admin, question, force_keywords=True)["supported"] is False, question
    response = engine.ask(admin, "How much money is tied up in overdue invoices?", force_keywords=True)
    assert response["supported"] and response["intent"] == "overdue_receivables" and response["matcher"] == "keyword"
    assert "language model is unavailable" in response["matcher_note"]


def test_requests_to_change_data_are_refused_as_read_only(admin):
    response = engine.ask(admin, "Create a purchase order for 50 Oak Tree", today=TODAY)
    if response["supported"]:
        assert response["intent"] == "action_request" and "read-only" in response["answer"] and response["rows"] == []


def test_a_missing_name_is_asked_for_not_invented(admin):
    response = engine.ask(admin, "How many of this product do we have in stock?", today=TODAY)
    assert response["supported"] is False and "couldn't find a product name" in response["answer"]


# ---- answers checked against hand-written SQL --------------------------------------------

def test_top_products_matches_hand_written_sql(admin):
    response = engine.ask(admin, "What were our top five products by sales last month?", today=TODAY)
    assert response["intent"] == "top_products"
    expected = _sql("""
        SELECT p.product_name AS name, SUM(il.line_net_amt_base * il.sign) AS amount
        FROM insightai.v_invoice_line il JOIN insightai.v_product p ON p.m_product_id = il.m_product_id
        WHERE il.ad_client_id = %(client)s AND il.ad_org_id = ANY(%(orgs)s::numeric[]) AND il.issotrx = 'Y'
          AND il.date_invoiced >= DATE '2026-09-01' AND il.date_invoiced < DATE '2026-10-01'
        GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 5""", admin)
    got = [(r["label"], round(r["amount"], 2)) for r in response["rows"]]
    assert got == [(r["name"], round(r["amount"], 2)) for r in expected]
    assert "2026-09-01 to 2026-09-30" in " ".join(response["understood"])


def test_overdue_total_matches_hand_written_sql(admin):
    response = engine.ask(admin, "How much money is tied up in overdue invoices?", today=TODAY)
    expected = _sql("""SELECT COALESCE(SUM(open_amt_base), 0) AS total, COUNT(*) AS n FROM insightai.v_open_item
                       WHERE ad_client_id = %(client)s AND ad_org_id = ANY(%(orgs)s::numeric[])
                         AND issotrx = 'Y' AND due_date < CURRENT_DATE""", admin)[0]
    assert sum(r["open_amount"] for r in response["rows"]) == pytest.approx(expected["total"])
    assert sum(r["invoices"] for r in response["rows"]) == expected["n"]
    assert f"{expected['total']:,.2f}" in response["answer"]


def test_stock_of_product_matches_hand_written_sql(admin):
    product = _sql("""SELECT p.product_name AS name, SUM(s.qty_on_hand) AS on_hand FROM insightai.v_stock s
                      JOIN insightai.v_product p ON p.m_product_id = s.m_product_id
                      WHERE s.ad_client_id = %(client)s AND s.ad_org_id = ANY(%(orgs)s::numeric[])
                      GROUP BY 1 HAVING SUM(s.qty_on_hand) > 0 ORDER BY 2 DESC LIMIT 1""", admin)
    if not product:
        pytest.skip("no stock")
    name = product[0]["name"].strip()
    response = engine.ask(admin, f"What is the stock level of {name}?", today=TODAY)
    assert response["intent"] == "stock_of_product"
    assert sum(r["on_hand"] for r in response["rows"]) == pytest.approx(product[0]["on_hand"])


def test_sales_to_customer_matches_hand_written_sql(admin):
    customer = _sql("""SELECT b.bpartner_name AS name, b.c_bpartner_id AS id, SUM(il.line_net_amt_base * il.sign) AS amount
                       FROM insightai.v_invoice_line il JOIN insightai.v_bpartner b ON b.c_bpartner_id = il.c_bpartner_id
                       WHERE il.ad_client_id = %(client)s AND il.ad_org_id = ANY(%(orgs)s::numeric[]) AND il.issotrx = 'Y'
                         AND il.date_invoiced BETWEEN DATE '2026-01-01' AND DATE '2026-10-12'
                       GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 1""", admin)
    if not customer:
        pytest.skip("no sales in 2026")
    name = customer[0]["name"].replace(", Inc.", "").strip()
    response = engine.ask(admin, f"How much did we sell to {name} this year?", today=TODAY)
    assert response["intent"] == "sales_to_customer"
    assert sum(r["amount"] for r in response["rows"]) == pytest.approx(customer[0]["amount"])


# ---- organisation restrictions ------------------------------------------------------------

def test_restricted_role_gets_only_its_organisations(admin, restricted):
    question = "Top 50 customers by sales all time"
    mine = engine.ask(restricted, question, today=TODAY)
    everyone = engine.ask(admin, question, today=TODAY)
    expected = _sql("""SELECT COALESCE(SUM(line_net_amt_base * sign), 0) AS amount FROM insightai.v_invoice_line
                       WHERE ad_client_id = %(client)s AND ad_org_id = ANY(%(orgs)s::numeric[]) AND issotrx = 'Y'""", restricted)[0]
    assert sum(r["amount"] for r in mine["rows"]) == pytest.approx(expected["amount"])
    assert sum(r["amount"] for r in mine["rows"]) < sum(r["amount"] for r in everyone["rows"])
    assert "1 your role can access" in " ".join(mine["understood"])


def test_stockout_question_is_never_answered_from_synthetic_data(admin):
    response = engine.ask(admin, "Which products are likely to run out of stock in the next 30 days?", today=TODAY)
    assert response["intent"] == "stockout_risk"
    client = TestClient(app, follow_redirects=False)
    client.get("/dev/login", params={"user_id": admin.user_id, "role_id": admin.role_id})
    real = client.get("/api/forecast").json()
    if real["available"] and real["counts"]["forecast"] == 0:
        # GardenWorld's real history cannot be forecast, so there must be no rows even though the synthetic demo has plenty
        assert response["rows"] == [] and "synthetic demo in the forecast panel is not used" in response["answer"]
    else:
        assert all(r["level"] in ("high", "medium") for r in response["rows"])


# ---- every intent runs, and the API ---------------------------------------------------------

def test_every_intent_has_examples_and_runs(admin):
    for intent in INTENTS:
        assert len(intent.examples) >= 5, intent.id
    for question, wanted in SUPPORTED:
        response = engine.ask(admin, question, today=TODAY)
        if response["supported"]:
            assert {"answer", "rows", "columns", "understood", "notes", "basis"} <= response.keys(), question
            assert response["answer"], question


def test_api_requires_a_session_and_validates_input():
    client = TestClient(app, follow_redirects=False)
    assert client.post("/api/assistant/ask", json={"question": "top products"}).status_code == 401
    row = db.query_one("SELECT ad_user_id::int AS uid, ad_role_id::int AS rid FROM v_user_role WHERE role_name = 'GardenWorld Admin' LIMIT 1")
    if not row:
        pytest.skip("no admin role")
    client.get("/dev/login", params={"user_id": row["uid"], "role_id": row["rid"]})
    assert client.post("/api/assistant/ask", json={}).status_code == 422
    assert client.post("/api/assistant/ask", json={"question": "x" * 5000}).status_code == 422
    ok = client.post("/api/assistant/ask", json={"question": "How much money is tied up in overdue invoices?"})
    assert ok.status_code == 200 and ok.json()["supported"] is True
    assert len(client.get("/api/assistant/questions").json()) >= 15
