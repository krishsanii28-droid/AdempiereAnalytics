"""The approved questions.

Each intent has example phrasings (used only for matching) and a handler that runs fixed SQL over
the insightai views, scoped to the session's client and organisations, and words the answer from
the rows it got back. Adding a question the assistant can answer means adding an intent here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from .. import db, queries
from ..config import Settings
from ..forecast import store as forecast_store
from .params import Entity, Period, previous_period


@dataclass
class Context:
    scope: queries.Scope
    currency: str
    today: date
    settings: Settings
    period: Period
    top_n: int
    top_n_stated: bool
    product: Entity | None = None
    bpartner: Entity | None = None


@dataclass
class Intent:
    id: str
    title: str
    examples: list[str]
    handler: Callable[[Context], dict[str, Any]]
    uses: tuple[str, ...] = ()            # parameters the handler reads: period, top_n, product, bpartner
    requires: tuple[str, ...] = ()        # entity parameters that must be found in the question
    keywords: list[set[str]] = field(default_factory=list)   # fallback matching: any one set fully present


# ---- helpers ----------------------------------------------------------------------------

def _money(ctx: Context, value: float | None) -> str:
    return f"{ctx.currency} {value or 0:,.2f}"


def _qty(value: float | None) -> str:
    return f"{value or 0:,.10g}"


def _day(value: date) -> str:
    return f"{value.day} {value:%b %Y}"


def _span(period: Period) -> str:
    return f"{period.label} ({_day(period.start)} to {_day(period.end)})"


def _filters(period: Period, bpartner: Entity | None = None) -> queries.Filters:
    return queries.Filters(period.start, period.end, None, None, bpartner.id if bpartner else None)


def _names(rows: list[dict], key: str, value: Callable[[dict], str], limit: int = 3) -> str:
    parts = [f"{r[key].strip()} ({value(r)})" for r in rows[:limit]]
    if len(parts) > 1:
        return ", ".join(parts[:-1]) + " and " + parts[-1]
    return parts[0]


def _result(answer: str, rows: list[dict], columns: list[list[str]], basis: str, *, chart: dict | None = None,
            notes: list[str] | None = None) -> dict[str, Any]:
    return {"answer": answer, "rows": rows, "columns": columns, "basis": basis, "chart": chart, "notes": notes or []}


# ---- sales and purchases ------------------------------------------------------------------

def _flow_total(ctx: Context, issotrx: str) -> dict[str, Any]:
    where, params, _ = queries._where(ctx.scope, _filters(ctx.period, ctx.bpartner), dims=("bpartner",),
                                      date_col="date_invoiced", extra=("issotrx = %(issotrx)s",))
    params["issotrx"] = issotrx
    rows = db.query(
        f"""SELECT to_char(date_trunc('month', date_invoiced), 'YYYY-MM') AS month,
                   SUM(line_net_amt_base * sign) AS amount, COUNT(DISTINCT c_invoice_id) AS documents
            FROM v_invoice_line WHERE {where} GROUP BY 1 ORDER BY 1""", params)
    total = sum(r["amount"] or 0 for r in rows)
    documents = db.query_one(f"SELECT COUNT(DISTINCT c_invoice_id) AS n FROM v_invoice_line WHERE {where}", params)["n"]
    return {"rows": rows, "total": total, "documents": documents}


def total_sales(ctx: Context) -> dict[str, Any]:
    data = _flow_total(ctx, "Y")
    if not data["documents"]:
        answer = f"There were no completed customer invoices for {_span(ctx.period)}."
    else:
        answer = (f"Sales were {_money(ctx, data['total'])} for {_span(ctx.period)}, "
                  f"from {data['documents']} customer invoice(s).")
    return _result(answer, data["rows"], [["month", "Month", "month"], ["amount", "Sales", "money"], ["documents", "Invoices", "number"]],
                   "Customer invoice lines by invoice date, net of credit memos, before tax",
                   chart={"kind": "columns", "x": "month", "xFormat": "month", "y": "amount", "series": "sales"})


def total_purchases(ctx: Context) -> dict[str, Any]:
    data = _flow_total(ctx, "N")
    if not data["documents"]:
        answer = f"There were no completed vendor invoices for {_span(ctx.period)}."
    else:
        answer = (f"Purchases were {_money(ctx, data['total'])} for {_span(ctx.period)}, "
                  f"from {data['documents']} vendor invoice(s).")
    return _result(answer, data["rows"], [["month", "Month", "month"], ["amount", "Purchases", "money"], ["documents", "Invoices", "number"]],
                   "Vendor invoice lines by invoice date, net of credit memos, before tax",
                   chart={"kind": "columns", "x": "month", "xFormat": "month", "y": "amount", "series": "purchases"})


def _ranking(ctx: Context, issotrx: str, label_sql: str, join_sql: str, noun: str, measure: str,
             series: str, limit: int | None) -> dict[str, Any]:
    where, params, _ = queries._where(ctx.scope, _filters(ctx.period), dims=(), date_col="date_invoiced", alias="l",
                                      extra=("l.issotrx = %(issotrx)s",))
    params.update(issotrx=issotrx, limit=limit or ctx.settings.max_rows)
    rows = db.query(
        f"""SELECT COALESCE({label_sql}, 'Charges and other lines') AS label,
                   SUM(l.line_net_amt_base * l.sign) AS amount, SUM(l.qty_invoiced * l.sign) AS quantity
            FROM v_invoice_line l {join_sql}
            WHERE {where} GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1 LIMIT %(limit)s""", params)
    columns = [["label", noun.capitalize(), "text"], ["amount", measure.capitalize(), "money"], ["quantity", "Quantity", "number"]]
    basis = ("Customer" if issotrx == "Y" else "Vendor") + " invoice lines by invoice date, before tax"
    if not rows:
        return _result(f"There were no {measure} for {_span(ctx.period)}.", [], columns, basis)
    if limit is None:
        answer = f"{measure.capitalize()} by {noun} for {_span(ctx.period)}: {_names(rows, 'label', lambda r: _money(ctx, r['amount']))} lead."
    elif len(rows) < limit and ctx.top_n_stated:
        answer = (f"Only {len(rows)} {noun}(s) had {measure} for {_span(ctx.period)}: "
                  f"{_names(rows, 'label', lambda r: _money(ctx, r['amount']), limit=len(rows))}.")
    else:
        answer = (f"The top {len(rows)} {noun}(s) by {measure} for {_span(ctx.period)}: "
                  f"{_names(rows, 'label', lambda r: _money(ctx, r['amount']), limit=min(len(rows), 5))}"
                  + ("." if len(rows) <= 5 else ", and others in the table."))
    return _result(answer, rows, columns, basis, chart={"kind": "bars", "x": "label", "y": "amount", "series": series})


def top_products(ctx: Context) -> dict[str, Any]:
    return _ranking(ctx, "Y", "p.product_name", "LEFT JOIN v_product p ON p.m_product_id = l.m_product_id",
                    "product", "sales", "sales", ctx.top_n)


def top_customers(ctx: Context) -> dict[str, Any]:
    return _ranking(ctx, "Y", "b.bpartner_name", "LEFT JOIN v_bpartner b ON b.c_bpartner_id = l.c_bpartner_id",
                    "customer", "sales", "sales", ctx.top_n)


def sales_by_category(ctx: Context) -> dict[str, Any]:
    return _ranking(ctx, "Y", "c.category_name",
                    "LEFT JOIN v_product_category c ON c.m_product_category_id = l.m_product_category_id",
                    "product category", "sales", "sales", None)


def top_suppliers(ctx: Context) -> dict[str, Any]:
    return _ranking(ctx, "N", "b.bpartner_name", "LEFT JOIN v_bpartner b ON b.c_bpartner_id = l.c_bpartner_id",
                    "supplier", "purchases", "purchases", ctx.top_n)


def sales_to_customer(ctx: Context) -> dict[str, Any]:
    data = _flow_total(ctx, "Y")
    name = ctx.bpartner.name
    if not data["documents"]:
        answer = f"There were no completed customer invoices for {name} for {_span(ctx.period)}."
    else:
        answer = f"Sales to {name} were {_money(ctx, data['total'])} for {_span(ctx.period)}, from {data['documents']} invoice(s)."
    return _result(answer, data["rows"], [["month", "Month", "month"], ["amount", "Sales", "money"], ["documents", "Invoices", "number"]],
                   "Customer invoice lines by invoice date, net of credit memos, before tax",
                   chart={"kind": "columns", "x": "month", "xFormat": "month", "y": "amount", "series": "sales"})


def product_sales(ctx: Context) -> dict[str, Any]:
    where, params, _ = queries._where(ctx.scope, _filters(ctx.period), dims=(), date_col="date_invoiced",
                                      extra=("issotrx = 'Y'", "m_product_id = %(product)s"))
    params["product"] = ctx.product.id
    rows = db.query(
        f"""SELECT to_char(date_trunc('month', date_invoiced), 'YYYY-MM') AS month,
                   SUM(line_net_amt_base * sign) AS amount, SUM(qty_invoiced * sign) AS quantity
            FROM v_invoice_line WHERE {where} GROUP BY 1 ORDER BY 1""", params)
    columns = [["month", "Month", "month"], ["amount", "Sales", "money"], ["quantity", "Quantity", "number"]]
    basis = "Customer invoice lines by invoice date, net of credit memos, before tax"
    if not rows:
        return _result(f"{ctx.product.name} had no invoiced sales for {_span(ctx.period)}.", [], columns, basis)
    amount, quantity = sum(r["amount"] or 0 for r in rows), sum(r["quantity"] or 0 for r in rows)
    return _result(f"{ctx.product.name} sold {_qty(quantity)} unit(s) for {_money(ctx, amount)} for {_span(ctx.period)}.",
                   rows, columns, basis,
                   chart={"kind": "columns", "x": "month", "xFormat": "month", "y": "amount", "series": "sales"})


def declining_sales_high_stock(ctx: Context) -> dict[str, Any]:
    """Products that sold less than in the preceding period of equal length and still have stock on hand."""
    previous = previous_period(ctx.period)
    params = {"client": ctx.scope.client_id, "orgs": list(ctx.scope.org_ids), "from": ctx.period.start, "to": ctx.period.end,
              "prev_from": previous.start, "prev_to": previous.end, "limit": ctx.settings.max_rows}
    rows = db.query(
        """WITH sales AS (
               SELECT m_product_id,
                      SUM(line_net_amt_base * sign) FILTER (WHERE date_invoiced BETWEEN %(from)s AND %(to)s) AS current_sales,
                      SUM(line_net_amt_base * sign) FILTER (WHERE date_invoiced BETWEEN %(prev_from)s AND %(prev_to)s) AS previous_sales
               FROM v_invoice_line
               WHERE ad_client_id = %(client)s AND ad_org_id = ANY(%(orgs)s::numeric[]) AND issotrx = 'Y'
                 AND m_product_id IS NOT NULL AND date_invoiced BETWEEN %(prev_from)s AND %(to)s
               GROUP BY 1),
           stock AS (
               SELECT m_product_id, SUM(qty_on_hand) AS on_hand, SUM(stock_value_base) AS stock_value
               FROM v_stock
               WHERE ad_client_id = %(client)s AND ad_org_id = ANY(%(orgs)s::numeric[])
               GROUP BY 1 HAVING SUM(qty_on_hand) > 0)
           SELECT p.product_name AS product, COALESCE(s.current_sales, 0) AS current_sales, s.previous_sales,
                  (COALESCE(s.current_sales, 0) - s.previous_sales) / NULLIF(s.previous_sales, 0) AS change,
                  k.on_hand, k.stock_value
           FROM sales s JOIN stock k ON k.m_product_id = s.m_product_id
           JOIN v_product p ON p.m_product_id = s.m_product_id
           WHERE s.previous_sales > 0 AND COALESCE(s.current_sales, 0) < s.previous_sales
           ORDER BY k.stock_value DESC NULLS LAST, 1 LIMIT %(limit)s""", params)
    columns = [["product", "Product", "text"], ["current_sales", "Sales, this period", "money"], ["previous_sales", "Sales, previous period", "money"],
               ["change", "Change", "percent"], ["on_hand", "On hand", "number"], ["stock_value", "Stock value", "money"]]
    basis = "Customer invoice lines by invoice date, compared with stock on hand today"
    notes = [f"Compared {_day(ctx.period.start)} to {_day(ctx.period.end)} with {_day(previous.start)} to {_day(previous.end)}. "
             "Rule: sales fell and stock is still on hand. Ordered by stock value."]
    if not rows:
        return _result(f"No product in stock sold less for {_span(ctx.period)} than in the preceding period of equal length. "
                       "Products with no sales in the earlier period cannot be compared and are left out.", [], columns, basis, notes=notes)
    answer = (f"{len(rows)} product(s) in stock sold less for {_span(ctx.period)} than in the preceding period of equal length. "
              f"Holding the most stock value: {_names(rows, 'product', lambda r: _money(ctx, r['stock_value']))}.")
    return _result(answer, rows, columns, basis, notes=notes)


# ---- receivables --------------------------------------------------------------------------

def _receivables(ctx: Context, overdue_only: bool) -> list[dict]:
    where, params, _ = queries._where(ctx.scope, _filters(ctx.period, ctx.bpartner), dims=("bpartner",), date_col=None,
                                      alias="o", extra=("o.issotrx = 'Y'",) + (("o.days_due > 0",) if overdue_only else ()))
    params["limit"] = ctx.settings.max_rows
    return db.query(
        f"""SELECT b.bpartner_name AS customer, SUM(o.open_amt_base) AS open_amount, COUNT(*) AS invoices,
                   SUM(o.open_amt_base) FILTER (WHERE o.days_due > 0) AS overdue_amount, MAX(o.days_due) AS oldest_days
            FROM v_open_item o JOIN v_bpartner b ON b.c_bpartner_id = o.c_bpartner_id
            WHERE {where} GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT %(limit)s""", params)


def overdue_receivables(ctx: Context) -> dict[str, Any]:
    rows = _receivables(ctx, overdue_only=True)
    columns = [["customer", "Customer", "text"], ["open_amount", "Overdue amount", "money"], ["invoices", "Overdue invoices", "number"],
               ["oldest_days", "Oldest, days past due", "days"]]
    basis = "Open customer invoices past their due date, as of today"
    who = f" for {ctx.bpartner.name}" if ctx.bpartner else ""
    if not rows:
        return _result(f"No customer invoices are overdue{who} as of today.", [], columns, basis)
    total, count = sum(r["open_amount"] for r in rows), sum(r["invoices"] for r in rows)
    answer = f"{_money(ctx, total)} is tied up in {count} overdue customer invoice(s){who}, as of today."
    if not ctx.bpartner:
        answer += f" Largest: {_names(rows, 'customer', lambda r: _money(ctx, r['open_amount']))}."
    return _result(answer, rows, columns, basis, chart={"kind": "bars", "x": "customer", "y": "open_amount", "series": "sales"})


def open_receivables(ctx: Context) -> dict[str, Any]:
    rows = _receivables(ctx, overdue_only=False)
    columns = [["customer", "Customer", "text"], ["open_amount", "Open amount", "money"], ["invoices", "Open invoices", "number"],
               ["overdue_amount", "Of which overdue", "money"], ["oldest_days", "Oldest, days past due", "days"]]
    basis = "Open customer invoices, as of today"
    who = f" for {ctx.bpartner.name}" if ctx.bpartner else ""
    if not rows:
        return _result(f"There are no open customer invoices{who} as of today.", [], columns, basis)
    total, count = sum(r["open_amount"] for r in rows), sum(r["invoices"] for r in rows)
    overdue = sum(r["overdue_amount"] or 0 for r in rows)
    if ctx.bpartner:
        answer = f"{ctx.bpartner.name} owes {_money(ctx, total)} on {count} open invoice(s), of which {_money(ctx, overdue)} is overdue."
    else:
        answer = (f"Customers owe {_money(ctx, total)} on {count} open invoice(s), of which {_money(ctx, overdue)} is overdue. "
                  f"Largest: {_names(rows, 'customer', lambda r: _money(ctx, r['open_amount']))}.")
    return _result(answer, rows, columns, basis, chart={"kind": "bars", "x": "customer", "y": "open_amount", "series": "sales"})


# ---- stock ---------------------------------------------------------------------------------

def stock_of_product(ctx: Context) -> dict[str, Any]:
    rows = db.query(
        """SELECT w.warehouse_name AS warehouse, s.qty_on_hand AS on_hand, s.qty_reserved AS reserved,
                  s.qty_available AS available, s.qty_ordered AS on_order
           FROM v_stock s JOIN v_warehouse w ON w.m_warehouse_id = s.m_warehouse_id
           WHERE s.ad_client_id = %(client)s AND s.ad_org_id = ANY(%(orgs)s::numeric[]) AND s.m_product_id = %(product)s
           ORDER BY 2 DESC, 1""",
        {"client": ctx.scope.client_id, "orgs": list(ctx.scope.org_ids), "product": ctx.product.id})
    columns = [["warehouse", "Warehouse", "text"], ["on_hand", "On hand", "number"], ["reserved", "Reserved", "number"],
               ["available", "Available", "number"], ["on_order", "On purchase order", "number"]]
    basis = "Quantity on hand, reserved and on order, as of today"
    if not rows:
        return _result(f"There is no stock record for {ctx.product.name} in the warehouses your role can see.", [], columns, basis)
    on_hand, available = sum(r["on_hand"] for r in rows), sum(r["available"] for r in rows)
    answer = (f"{ctx.product.name}: {_qty(on_hand)} on hand across {len(rows)} warehouse(s), "
              f"{_qty(available)} available after reservations.")
    return _result(answer, rows, columns, basis)


def inventory_value(ctx: Context) -> dict[str, Any]:
    data = queries.inventory_by_warehouse(ctx.scope, _filters(ctx.period))
    rows = data["rows"]
    columns = [["label", "Warehouse", "text"], ["value", "Value", "money"], ["quantity", "Quantity", "number"], ["products", "Products", "number"]]
    basis = "Quantity on hand x unit cost, as of today"
    if not rows:
        return _result("There is no stock on hand in the warehouses your role can see.", [], columns, basis)
    split = db.query_one(
        """SELECT COALESCE(SUM(stock_value_base) FILTER (WHERE cost_source = 'STANDARD_COST'), 0) AS standard
           FROM v_stock WHERE ad_client_id = %(client)s AND ad_org_id = ANY(%(orgs)s::numeric[])""",
        {"client": ctx.scope.client_id, "orgs": list(ctx.scope.org_ids)})
    notes = list(data["notes"])
    if split["standard"]:
        notes.append(f"{_money(ctx, split['standard'])} of this is valued at standard cost because no ledger cost is recorded for those products.")
    total = sum(r["value"] for r in rows)
    answer = (f"Inventory is worth {_money(ctx, total)} as of today, across {len(rows)} warehouse(s). "
              f"Largest: {_names(rows, 'label', lambda r: _money(ctx, r['value']))}.")
    return _result(answer, rows, columns, basis, notes=notes, chart={"kind": "bars", "x": "label", "y": "value", "series": "inventory"})


def slow_moving(ctx: Context) -> dict[str, Any]:
    data = queries.slow_moving(ctx.scope, _filters(ctx.period))
    rows = data["rows"]
    columns = [["product", "Product", "text"], ["warehouse", "Warehouse", "text"], ["quantity", "On hand", "number"], ["value", "Value", "money"],
               ["last_outbound", "Last outbound movement", "date"], ["days_since", "Days since", "days"]]
    basis = "Stock on hand and stock movements, as of today"
    days = ctx.settings.slow_moving_days
    if not rows:
        return _result(f"No stock on hand has gone {days} days without an outbound movement.", [], columns, basis, notes=data["notes"])
    total = sum(r["value"] or 0 for r in rows)
    answer = (f"{len(rows)} product and warehouse combination(s) have stock but no outbound movement in the last {days} days, "
              f"holding {_money(ctx, total)}. Largest: {_names(rows, 'product', lambda r: _money(ctx, r['value']))}.")
    return _result(answer, rows, columns, basis, notes=data["notes"])


def stockout_risk(ctx: Context) -> dict[str, Any]:
    """Answered from the real-data forecast only. The synthetic demo is never used to answer a question."""
    data = forecast_store.summary("real", ctx.scope, queries.Filters(ctx.today, ctx.today))
    columns = [["product", "Product", "text"], ["warehouse", "Warehouse", "text"], ["level", "Risk", "text"],
               ["probability_text", "Estimated chance", "text"], ["available", "Available", "number"], ["incoming", "Incoming", "number"],
               ["demand_median", "Forecast demand", "number"], ["stockout_week", "Runs out in week", "number"]]
    basis = "Demand forecast compared with available stock and open purchase orders"
    if not data["available"]:
        return _result("This can't be answered yet: no forecast has been run. Use Run forecast in the forecast panel.", [], columns, basis)
    horizon = data["horizon_weeks"]
    notes = [f"The forecast horizon is fixed at {horizon} weeks (to {data['forecast_end']}), whatever period the question names.",
             f"Forecast run {data['generated_at'].replace('T', ' ')}."]
    if data["counts"]["forecast"] == 0:
        return _result(f"This can't be answered from the data available: none of the {data['counts']['series']} product and warehouse "
                       "combinations has enough completed shipment history to forecast. The synthetic demo in the forecast panel "
                       "is not used to answer questions.", [], columns, basis, notes=notes)
    at_risk = [r for r in data["rows"] if r["level"] in ("high", "medium")]
    if not at_risk:
        return _result(f"No forecast product is at high or medium stockout risk in the next {horizon} weeks.", [], columns, basis, notes=notes)
    high = sum(1 for r in at_risk if r["level"] == "high")
    answer = (f"{len(at_risk)} product and warehouse combination(s) are at risk of running out in the next {horizon} weeks "
              f"({high} high, {len(at_risk) - high} medium). Most at risk: "
              f"{_names(at_risk, 'product', lambda r: r['probability_text'] + ' chance')}.")
    return _result(answer, at_risk, columns, basis, notes=notes)


# ---- suppliers -----------------------------------------------------------------------------

def supplier_delays(ctx: Context) -> dict[str, Any]:
    data = queries.supplier_performance(ctx.scope, _filters(ctx.period))
    rows = sorted(data["rows"], key=lambda r: (r["avg_days_late"] is None, -(r["avg_days_late"] or 0), r["supplier"]))
    columns = [["supplier", "Supplier", "text"], ["receipt_lines", "Receipt lines", "number"], ["matched_lines", "Linked to an order", "number"],
               ["on_time_rate", "On time", "percent"], ["avg_days_late", "Average days late", "days"], ["max_days_late", "Worst days late", "days"]]
    basis = "Vendor receipt lines by movement date, against the order line's promised date"
    if not rows:
        return _result(f"There were no vendor receipts for {_span(ctx.period)}.", [], columns, basis, notes=data["notes"])
    rated = [r for r in rows if r["matched_lines"]]
    late = [r for r in rated if (r["max_days_late"] or 0) > 0]
    matched = sum(r["matched_lines"] for r in rated)
    if not rated:
        answer = (f"Delivery delays can't be measured for {_span(ctx.period)}: none of the {sum(r['receipt_lines'] for r in rows)} "
                  "receipt line(s) is linked to an order line with a promised date.")
    elif not late:
        answer = (f"No supplier delivered late for {_span(ctx.period)}: all {matched} receipt line(s) that can be rated "
                  "arrived on or before the promised date.")
    else:
        answer = (f"{len(late)} supplier(s) delivered late for {_span(ctx.period)}. Longest average delay: "
                  f"{_names(late, 'supplier', lambda r: f'{r['avg_days_late']:.1f} days')}.")
    return _result(answer, rows, columns, basis, notes=data["notes"])


# ---- not a question the assistant will act on ----------------------------------------------

def action_request(ctx: Context) -> dict[str, Any]:
    return _result("InsightAI is read-only. It can report on orders, invoices and stock, but it cannot create, change, "
                   "post or delete anything in ADempiere. Use the ADempiere windows for that.", [], [], "")


INTENTS: list[Intent] = [
    Intent("total_sales", "Total sales for a period", [
        "What were our total sales last month?", "How much did we sell this year?", "What is our revenue this quarter?",
        "Show me sales by month", "What is the monthly sales trend?", "How much revenue did we invoice last quarter?",
        "Total sales in the last 90 days"], total_sales, uses=("period",),
        keywords=[{"total", "sales"}, {"revenue"}, {"sales", "trend"}, {"sales", "developing"}, {"much", "sell"}, {"sales", "during"}]),
    Intent("total_purchases", "Total purchases for a period", [
        "How much did we spend on purchases last month?", "What was our purchase expenditure this year?",
        "Total purchases this quarter", "How much did we buy from vendors in the last 6 months?",
        "Show me purchases by month", "What is our purchasing spend?"], total_purchases, uses=("period",),
        keywords=[{"total", "purchases"}, {"purchase", "expenditure"}, {"purchasing", "spend"}, {"much", "spend"}, {"much", "spent"},
                  {"procurement"}]),
    Intent("top_products", "Top products by sales", [
        "What were our top five products by sales last month?", "Which products sold the most this year?",
        "Best selling products", "Show the top 10 products by revenue", "What are our best sellers?",
        "Which items bring in the most sales?", "Which goods make us the most money?"], top_products, uses=("period", "top_n"),
        keywords=[{"top", "products"}, {"best", "selling"}, {"best", "sellers"}, {"products", "most"}]),
    Intent("top_customers", "Top customers by sales", [
        "Who are our top customers?", "Which customers bought the most this year?", "Top 5 customers by sales last quarter",
        "Who are our biggest customers by revenue?", "Which clients spend the most with us?",
        "Who buys the most from us?", "Who purchases the most from us?"], top_customers, uses=("period", "top_n"),
        keywords=[{"top", "customers"}, {"biggest", "customers"}, {"customers", "most"}, {"best", "customers"}]),
    Intent("sales_by_category", "Sales by product category", [
        "What are sales by product category?", "Which product categories sell the most?", "Break down sales by category",
        "Sales per category this year", "How do the product groups compare in sales?"], sales_by_category, uses=("period",),
        keywords=[{"sales", "category"}, {"sales", "categories"}, {"categories", "most"}, {"sales", "product", "group"}, {"category", "products"}]),
    Intent("top_suppliers", "Top suppliers by purchases", [
        "Who are our biggest suppliers?", "Which vendors do we buy the most from?", "Top suppliers by purchase amount this year",
        "Which suppliers do we spend the most with?", "Top 5 vendors by spend"], top_suppliers, uses=("period", "top_n"),
        keywords=[{"top", "suppliers"}, {"top", "vendors"}, {"biggest", "suppliers"}, {"vendors", "most"}, {"suppliers", "most"}]),
    Intent("sales_to_customer", "Sales to one customer", [
        "How much did we sell to this customer this year?", "What are our sales to this customer?",
        "Show sales for this customer last quarter", "How much has this customer bought from us?",
        "Revenue from this customer"], sales_to_customer, uses=("period", "bpartner"), requires=("bpartner",),
        keywords=[{"this", "customer", "sales"}, {"this", "customer", "sell"}, {"this", "customer", "buy"}, {"this", "customer", "bought"},
                  {"this", "customer", "revenue"}]),
    Intent("product_sales", "Sales of one product", [
        "How much of this product did we sell last month?", "What are the sales of this product this year?",
        "How many units of this product were sold?", "Show sales for this product", "Revenue from this product"],
        product_sales, uses=("period", "product"), requires=("product",),
        keywords=[{"this", "product", "sales"}, {"this", "product", "sell"}, {"this", "product", "sold"}, {"this", "product", "revenue"}]),
    Intent("declining_sales_high_stock", "Products with declining sales that are still in stock", [
        "Which products have declining sales and high current inventory?", "Which products are selling less but we still hold a lot of stock?",
        "Products with falling sales and stock on hand", "Where are sales dropping while inventory stays high?",
        "Which items have decreasing demand but high stock?", "What is selling worse than before although we hold plenty of it?",
        "Products whose sales went down compared with the previous period that we still stock"], declining_sales_high_stock, uses=("period",),
        keywords=[{"declining", "sales"}, {"falling", "sales"}, {"sales", "dropping"}, {"decreasing", "demand"}]),
    Intent("overdue_receivables", "Overdue customer invoices", [
        "How much money is tied up in overdue invoices?", "What is the total of overdue receivables?", "Which customers have overdue invoices?",
        "How much is past due from customers?", "Which invoices are late being paid?", "Show overdue customer payments"],
        overdue_receivables, uses=("bpartner",),
        keywords=[{"overdue"}, {"past", "due"}, {"late", "paid"}]),
    Intent("open_receivables", "Open customer invoices", [
        "Which customers owe us the most?", "How much do customers owe us?", "What are our outstanding receivables?",
        "Show unpaid customer invoices", "Total open accounts receivable", "How much does this customer owe us?"],
        open_receivables, uses=("bpartner",),
        keywords=[{"owe"}, {"outstanding", "receivables"}, {"unpaid", "invoices"}, {"accounts", "receivable"}, {"open", "invoices"},
                  {"customers", "pay", "us"}]),
    Intent("stock_of_product", "Stock of one product", [
        "How many of this product do we have in stock?", "What is the stock level of this product?",
        "How much of this product is on hand?", "Do we have this product in stock?", "Current inventory of this product",
        "How many units of this product are in the warehouse?", "How many of this product are left?"],
        stock_of_product, uses=("product",), requires=("product",),
        keywords=[{"this", "product", "stock"}, {"this", "product", "warehouse"}, {"this", "product", "hand"}, {"this", "product", "inventory"},
                  {"this", "product", "left"}]),
    Intent("inventory_value", "Inventory value", [
        "What is our inventory worth?", "What is the total value of stock?", "How much is our inventory valued at?",
        "Inventory value by warehouse", "How much money is tied up in stock?"], inventory_value,
        keywords=[{"inventory", "value"}, {"inventory", "worth"}, {"stock", "value"}, {"inventory", "valued"}]),
    Intent("slow_moving", "Slow-moving stock", [
        "Which products are slow moving?", "What stock has not moved recently?", "Show slow-moving inventory",
        "Which items are sitting in the warehouse without selling?", "Dead stock list"], slow_moving,
        keywords=[{"slow", "moving"}, {"dead", "stock"}, {"not", "moved"}, {"stock", "not", "selling"}, {"sitting"}]),
    Intent("stockout_risk", "Products likely to run out of stock", [
        "Which products are likely to run out of stock in the next 30 days?", "What is at risk of stockout?",
        "Which items will we run out of soon?", "Where do we have insufficient stock for forecast demand?",
        "Which products need reordering soon?"], stockout_risk,
        keywords=[{"run", "out"}, {"stockout"}, {"stock", "out"}, {"reordering"}, {"insufficient", "stock"}]),
    Intent("supplier_delays", "Supplier delivery delays", [
        "Which suppliers have the longest delivery delays?", "Which vendors deliver late?", "How reliable are our suppliers on delivery dates?",
        "Supplier on-time delivery performance", "Who is late delivering our purchase orders?"], supplier_delays, uses=("period",),
        keywords=[{"delivery", "delays"}, {"deliver", "late"}, {"late", "delivering"}, {"on", "time", "delivery"}, {"suppliers", "reliable"}]),
    Intent("action_request", "A request to change something", [
        "Create a purchase order for this product", "Post this invoice", "Delete the draft orders", "Change the stock quantity of this product",
        "Reorder this product from the supplier", "Void this invoice", "Update the price of this product", "Pay this vendor invoice"],
        action_request, keywords=[{"create"}, {"delete"}, {"void"}, {"cancel"}, {"post", "invoice"}, {"change", "quantity"}, {"reorder", "from"}]),
    # Topics InsightAI has no data for. A question nearest to one of these is declined, which keeps
    # look-alike questions ("marketing budget", "employees in the warehouse") from being answered wrongly.
    Intent("out_of_scope", "Outside what InsightAI covers", [
        "What are the salaries of our staff?", "How many employees do we have?", "Who works in this department?",
        "What is the marketing budget?", "What is our budget for next year?", "Who is the manager of the company?",
        "What are our competitors doing?", "How is the market developing?", "What is the weather today?",
        "Tell me something funny", "Write a text for me", "Translate this sentence", "What is the meaning of this word?",
        "How do I use this software?", "How do I change my password?", "Explain how accounting works",
        "What is the share price?", "What should our strategy be?", "Hello, how are you?", "What can you do?"],
        action_request),
]
BY_ID = {intent.id: intent for intent in INTENTS}
