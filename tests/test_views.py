"""Integration tests for the insightai views, run as the read-only service role.

They check rules the views must keep for any data. Comparison with ADempiere's own figures needs
the adempiere role and is done by scripts\\db_crosscheck.ps1.
"""
import psycopg
import pytest

from insightai import db

FACT_VIEWS = ["v_order_line", "v_invoice", "v_invoice_line", "v_inout_line", "v_demand_daily",
              "v_open_item", "v_stock", "v_stock_movement"]
ALL_VIEWS = FACT_VIEWS + ["v_user_role_org", "v_user_role", "v_role_process", "v_org", "v_warehouse",
                          "v_product_category", "v_product", "v_bpartner", "v_product_cost"]


def test_all_views_exist_and_are_readable():
    for view in ALL_VIEWS:
        db.query(f"SELECT * FROM {view} LIMIT 1")


def test_every_fact_view_carries_client_and_organisation():
    for view in FACT_VIEWS:
        row = db.query_one(f"SELECT COUNT(*) AS n, COUNT(ad_client_id) AS clients, COUNT(ad_org_id) AS orgs FROM {view}")
        assert row["n"] == row["clients"] == row["orgs"], view


def test_only_completed_and_closed_documents():
    for view in ("v_order_line", "v_invoice", "v_invoice_line", "v_inout_line"):
        statuses = {r["docstatus"] for r in db.query(f"SELECT DISTINCT docstatus FROM {view}")}
        assert statuses <= {"CO", "CL"}, (view, statuses)


def test_document_types_and_signs():
    assert {r["t"] for r in db.query("SELECT DISTINCT docbasetype AS t FROM v_invoice")} <= {"ARI", "ARC", "API", "APC"}
    assert {r["t"] for r in db.query("SELECT DISTINCT movementtype AS t FROM v_inout_line")} <= {"C-", "C+", "V+", "V-"}
    assert {r["s"] for r in db.query("SELECT DISTINCT COALESCE(docsubtypeso, '') AS s FROM v_order_line")}.isdisjoint({"ON", "OB"})
    wrong = db.query_one("""SELECT (SELECT COUNT(*) FROM v_invoice WHERE sign <> CASE WHEN is_credit_memo THEN -1 ELSE 1 END)
                                 + (SELECT COUNT(*) FROM v_invoice_line WHERE sign <> CASE WHEN is_credit_memo THEN -1 ELSE 1 END)
                                 + (SELECT COUNT(*) FROM v_order_line WHERE sign <> CASE WHEN is_return THEN -1 ELSE 1 END) AS n""")
    assert wrong["n"] == 0


def test_invoice_lines_belong_to_invoices_in_the_header_view():
    orphans = db.query_one("""SELECT COUNT(*) AS n FROM v_invoice_line l
                              WHERE NOT EXISTS (SELECT 1 FROM v_invoice i WHERE i.c_invoice_id = l.c_invoice_id)""")
    assert orphans["n"] == 0
    mismatch = db.query_one("""SELECT COUNT(*) AS n FROM v_invoice i JOIN (
                                   SELECT c_invoice_id, SUM(line_net_amt) AS lines FROM v_invoice_line GROUP BY 1) l USING (c_invoice_id)
                               WHERE ABS(i.total_lines - l.lines) > 0.01""")
    assert mismatch["n"] == 0


def test_base_currency_amounts_are_present_and_equal_when_already_in_base_currency():
    for view, column, base in (("v_order_line", "line_net_amt", "line_net_amt_base"), ("v_invoice", "grand_total", "grand_total_base"),
                               ("v_invoice_line", "line_net_amt", "line_net_amt_base")):
        row = db.query_one(f"""SELECT COUNT(*) FILTER (WHERE {base} IS NULL) AS missing,
                                      COUNT(*) FILTER (WHERE c_currency_id = base_currency_id(ad_client_id)
                                                         AND ABS({column} - {base}) > 0.005) AS changed FROM {view}""")
        assert row["changed"] == 0, view
        assert row["missing"] == 0, f"{view}: {row['missing']} rows have no conversion rate"


def test_stock_arithmetic():
    wrong = db.query_one("""SELECT COUNT(*) FILTER (WHERE qty_available <> qty_on_hand - qty_reserved) AS available,
                                   COUNT(*) FILTER (WHERE unit_cost IS NOT NULL AND ABS(stock_value_base - qty_on_hand * unit_cost) > 0.005) AS value,
                                   COUNT(*) FILTER (WHERE (unit_cost IS NULL) <> (cost_source IS NULL)) AS source FROM v_stock""")
    assert (wrong["available"], wrong["value"], wrong["source"]) == (0, 0, 0)
    assert {r["s"] for r in db.query("SELECT DISTINCT cost_source AS s FROM v_stock WHERE cost_source IS NOT NULL")} \
        <= {"ACCT_SCHEMA_COST_TYPE", "STANDARD_COST"}


def test_demand_is_shipments_minus_returns():
    wrong = db.query_one("SELECT COUNT(*) AS n FROM v_demand_daily WHERE qty_net <> qty_shipped - qty_returned")
    assert wrong["n"] == 0
    totals = db.query_one("""SELECT (SELECT COALESCE(SUM(qty_shipped), 0) FROM v_demand_daily) AS daily,
                                    (SELECT COALESCE(SUM(movement_qty), 0) FROM v_inout_line WHERE movementtype = 'C-' AND is_stocked_item) AS lines""")
    assert totals["daily"] == pytest.approx(totals["lines"])


def test_demand_contains_only_stocked_items():
    """Services and expense items appear on shipment documents but move no stock."""
    wrong = db.query_one("""SELECT COUNT(*) AS n FROM v_demand_daily d JOIN v_product p ON p.m_product_id = d.m_product_id
                            WHERE NOT (p.isstocked = 'Y' AND p.producttype = 'I')""")
    assert wrong["n"] == 0


def test_open_items_are_open_and_bucketed_consistently():
    wrong = db.query_one("""SELECT COUNT(*) FILTER (WHERE open_amt = 0) AS settled,
                                   COUNT(*) FILTER (WHERE (days_due <= 0) <> (aging_bucket = 'Not due')) AS bucket,
                                   COUNT(*) FILTER (WHERE aging_bucket NOT IN ('Not due', '1-30', '31-60', '61-90', 'Over 90')) AS unknown
                            FROM v_open_item""")
    assert (wrong["settled"], wrong["bucket"], wrong["unknown"]) == (0, 0, 0)


def test_days_late_only_for_receipts_linked_to_a_promised_date():
    wrong = db.query_one("""SELECT COUNT(*) FILTER (WHERE movementtype <> 'V+' AND days_late IS NOT NULL) AS not_receipt,
                                   COUNT(*) FILTER (WHERE movementtype = 'V+' AND (date_promised IS NULL) <> (days_late IS NULL)) AS unlinked,
                                   COUNT(*) FILTER (WHERE days_late IS NOT NULL AND days_late <> movement_date - date_promised) AS arithmetic
                            FROM v_inout_line""")
    assert (wrong["not_receipt"], wrong["unlinked"], wrong["arithmetic"]) == (0, 0, 0)


def test_organisation_access_view_lists_only_real_leaf_organisations_of_the_roles_client():
    wrong = db.query_one("""SELECT COUNT(*) AS n FROM v_user_role_org a
                            WHERE NOT EXISTS (SELECT 1 FROM v_org o WHERE o.ad_org_id = a.ad_org_id AND o.ad_client_id = a.ad_client_id)""")
    assert wrong["n"] == 0                       # v_org holds active, non-summary organisations other than *
    duplicates = db.query_one("""SELECT COUNT(*) AS n FROM (SELECT 1 FROM v_user_role_org
                                 GROUP BY ad_user_id, ad_role_id, ad_org_id HAVING COUNT(*) > 1) d""")
    assert duplicates["n"] == 0
    roleless = db.query_one("""SELECT COUNT(*) AS n FROM v_user_role_org a
                               WHERE NOT EXISTS (SELECT 1 FROM v_user_role u WHERE u.ad_user_id = a.ad_user_id AND u.ad_role_id = a.ad_role_id)""")
    assert roleless["n"] == 0


@pytest.mark.parametrize("statement", [
    "SELECT COUNT(*) FROM adempiere.c_invoice",
    "SELECT password FROM adempiere.ad_user LIMIT 1",
    "SELECT value FROM adempiere.ad_sysconfig LIMIT 1",
    "SELECT adempiere.invoiceopen(100, 0)",
    "CREATE TABLE insightai.should_not_exist (id int)",
    "CREATE TEMP TABLE should_not_exist (id int)",
    "DELETE FROM insightai.v_org",
    "UPDATE insightai.v_product SET product_name = 'x'",
])
def test_service_role_cannot_read_adempiere_or_write_anything(statement):
    with pytest.raises((psycopg.errors.InsufficientPrivilege, psycopg.errors.ReadOnlySqlTransaction,
                        psycopg.errors.ObjectNotInPrerequisiteState, psycopg.errors.FeatureNotSupported)):
        db.query(statement)


def test_service_role_cannot_write_even_after_lifting_its_read_only_default():
    with db._get_pool().connection() as conn:
        conn.execute("SET default_transaction_read_only = off")
        try:
            for statement in ("CREATE TABLE public.should_not_exist (id int)", "CREATE TEMP TABLE should_not_exist (id int)",
                              "CREATE TABLE insightai.should_not_exist (id int)"):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    conn.execute(statement)
        finally:
            conn.execute("SET default_transaction_read_only = on")
