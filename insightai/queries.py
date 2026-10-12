"""Every figure the dashboard shows.

All SQL here is fixed text over the insightai views. User input only ever arrives as bound
parameters, and every statement is restricted to the session's client and organisations.
Definitions are documented in docs/kpi_definitions.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable

from . import db
from .config import get_settings


@dataclass(frozen=True)
class Scope:
    """What the session may see. Built server-side from ADempiere's access tables."""

    client_id: int
    org_ids: tuple[int, ...]


@dataclass(frozen=True)
class Filters:
    date_from: date
    date_to: date
    warehouse_id: int | None = None
    category_id: int | None = None
    bpartner_id: int | None = None


_DIMENSION_COLUMNS = {
    "warehouse": "m_warehouse_id",
    "category": "m_product_category_id",
    "bpartner": "c_bpartner_id",
}
_DIMENSION_LABELS = {"warehouse": "warehouse", "category": "product category", "bpartner": "business partner"}


def _where(
    scope: Scope,
    filters: Filters,
    *,
    dims: tuple[str, ...],
    date_col: str | None,
    extra: tuple[str, ...] = (),
    alias: str = "",
) -> tuple[str, dict[str, Any], list[str]]:
    """WHERE clause for one view.

    `dims` lists the filters this view can honour. A selected filter the view cannot honour is
    returned in `ignored` so the UI can say so instead of showing a silently unfiltered number.
    """
    p = f"{alias}." if alias else ""
    clauses = [f"{p}ad_client_id = %(client)s", f"{p}ad_org_id = ANY(%(orgs)s::numeric[])", *extra]
    params: dict[str, Any] = {"client": scope.client_id, "orgs": list(scope.org_ids)}
    ignored: list[str] = []
    for dim, column in _DIMENSION_COLUMNS.items():
        value = getattr(filters, f"{dim}_id")
        if value is None:
            continue
        if dim in dims:
            clauses.append(f"{p}{column} = %({dim})s")
            params[dim] = value
        else:
            ignored.append(_DIMENSION_LABELS[dim])
    if date_col:
        clauses.append(f"{p}{date_col} BETWEEN %(date_from)s AND %(date_to)s")
        params["date_from"] = filters.date_from
        params["date_to"] = filters.date_to
    return " AND ".join(clauses), params, ignored


def _period(filters: Filters) -> dict[str, str]:
    return {"from": filters.date_from.isoformat(), "to": filters.date_to.isoformat()}


def _previous(filters: Filters) -> Filters:
    """The period of equal length immediately before the selected one."""
    days = (filters.date_to - filters.date_from).days
    prev_to = filters.date_from - timedelta(days=1)
    return Filters(prev_to - timedelta(days=days), prev_to, filters.warehouse_id, filters.category_id, filters.bpartner_id)


# --------------------------------------------------------------------------------------
# KPI cards
# --------------------------------------------------------------------------------------

def _card(card_id: str, label: str, unit: str, **fields: Any) -> dict[str, Any]:
    card = {"id": card_id, "label": label, "unit": unit, "available": True, "value": None,
            "reason": None, "detail": None, "delta": None, "delta_label": None, "ignored": [], "notes": []}
    card.update(fields)
    return card


def _invoiced(scope: Scope, filters: Filters, issotrx: str) -> tuple[dict[str, Any], list[str]]:
    where, params, ignored = _where(scope, filters, dims=("category", "bpartner"), date_col="date_invoiced",
                                    extra=("issotrx = %(issotrx)s",))
    params["issotrx"] = issotrx
    row = db.query_one(
        f"""SELECT COALESCE(SUM(line_net_amt_base * sign), 0) AS amount,
                   COUNT(DISTINCT c_invoice_id) AS documents,
                   COUNT(*) FILTER (WHERE line_net_amt_base IS NULL) AS unconverted
            FROM v_invoice_line WHERE {where}""",
        params,
    )
    return row, ignored


def _flow_card(card_id: str, label: str, scope: Scope, filters: Filters, issotrx: str, noun: str) -> dict[str, Any]:
    row, ignored = _invoiced(scope, filters, issotrx)
    card = _card(card_id, label, "currency", value=row["amount"], ignored=ignored,
                 detail=f"{row['documents']} {noun} by invoice date, before tax")
    if row["unconverted"]:
        card["notes"].append(f"{row['unconverted']} line(s) left out: no currency conversion rate in ADempiere")
    if row["documents"] == 0:
        card["detail"] = f"No completed {noun} in this period"
    return card


def kpis(scope: Scope, filters: Filters) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []

    # Sales, with growth against the preceding period of equal length
    sales = _flow_card("sales", "Total sales", scope, filters, "Y", "customer invoices")
    previous, _ = _invoiced(scope, _previous(filters), "Y")
    days = (filters.date_to - filters.date_from).days + 1
    sales["delta_label"] = f"vs previous {days} days"
    if previous["amount"]:
        sales["delta"] = (sales["value"] - previous["amount"]) / abs(previous["amount"])
    else:
        sales["notes"].append("Growth not available: no sales in the previous period")
    cards.append(sales)

    cards.append(_flow_card("purchases", "Purchase expenditure", scope, filters, "N", "vendor invoices"))

    # Receivables: a balance as of today, so the date range does not apply
    where, params, ignored = _where(scope, filters, dims=("bpartner",), date_col=None, extra=("issotrx = 'Y'",))
    ar = db.query_one(
        f"""SELECT COALESCE(SUM(open_amt_base), 0) AS outstanding,
                   COALESCE(SUM(open_amt_base) FILTER (WHERE days_due > 0), 0) AS overdue,
                   COUNT(*) AS items, COUNT(*) FILTER (WHERE days_due > 0) AS overdue_items,
                   COUNT(*) FILTER (WHERE open_amt_base IS NULL) AS unconverted
            FROM v_open_item WHERE {where}""",
        params,
    )
    unconverted = [f"{ar['unconverted']} item(s) left out: no currency conversion rate"] if ar["unconverted"] else []
    cards.append(_card("receivables", "Outstanding receivables", "currency", value=ar["outstanding"], ignored=ignored,
                       detail=f"{ar['items']} open customer invoices, as of today", notes=list(unconverted)))
    cards.append(_card("overdue", "Overdue receivables", "currency", value=ar["overdue"], ignored=ignored,
                       detail=f"{ar['overdue_items']} past their due date, as of today", notes=list(unconverted)))

    # Inventory value: also a balance as of today
    where, params, ignored_stock = _where(scope, filters, dims=("warehouse", "category"), date_col=None)
    stock = db.query_one(
        f"""SELECT COALESCE(SUM(stock_value_base), 0) AS value,
                   COALESCE(SUM(stock_value_base) FILTER (WHERE cost_source = 'ACCT_SCHEMA_COST_TYPE'), 0) AS ledger_value,
                   COALESCE(SUM(stock_value_base) FILTER (WHERE cost_source = 'STANDARD_COST'), 0) AS standard_value,
                   COUNT(DISTINCT m_product_id) FILTER (WHERE qty_on_hand <> 0) AS products,
                   COUNT(DISTINCT m_product_id) FILTER (WHERE qty_on_hand <> 0 AND unit_cost IS NULL) AS uncosted
            FROM v_stock WHERE {where}""",
        params,
    )
    inventory = _card("inventory", "Inventory value", "currency", value=stock["value"], ignored=ignored_stock,
                      detail=f"{stock['products']} products in stock, as of today")
    if stock["products"] == 0:
        inventory.update(available=False, reason="No stock on hand in this selection")
    elif stock["uncosted"] == stock["products"]:
        inventory.update(available=False, reason="None of the products in stock has a cost in ADempiere")
    else:
        if stock["standard_value"]:
            inventory["notes"].append(
                f"Mixed cost basis: {stock['ledger_value']:,.2f} at the ledger's cost, "
                f"{stock['standard_value']:,.2f} at standard cost (no ledger cost recorded)")
        if stock["uncosted"]:
            inventory["notes"].append(f"{stock['uncosted']} product(s) in stock have no cost and count as zero")
    cards.append(inventory)

    # Inventory turnover: cost of goods shipped in the period / inventory value today
    where, params, ignored_ship = _where(scope, filters, dims=("warehouse", "category", "bpartner"),
                                         date_col="movement_date", alias="l",
                                         extra=("l.movementtype IN ('C-', 'C+')",))
    shipped = db.query_one(
        f"""SELECT COALESCE(SUM(CASE WHEN l.movementtype = 'C-' THEN l.movement_qty ELSE -l.movement_qty END * c.unit_cost), 0) AS cogs,
                   COUNT(*) AS lines, COUNT(*) FILTER (WHERE c.unit_cost IS NULL) AS uncosted
            FROM v_inout_line l LEFT JOIN v_product_cost c ON c.m_product_id = l.m_product_id
            WHERE {where}""",
        params,
    )
    turnover = _card("turnover", "Inventory turnover", "ratio", ignored=sorted(set(ignored_stock + ignored_ship)))
    if not inventory["available"] or not stock["value"]:
        turnover.update(available=False, reason="Needs a costed inventory value")
    elif shipped["lines"] == 0:
        turnover.update(available=False, reason="No customer shipments in this period")
    else:
        turnover["value"] = shipped["cogs"] / stock["value"]
        turnover["detail"] = f"Cost of {shipped['lines']} shipment lines in the period / stock value today"
        turnover["notes"].append("Approximate: uses current unit cost and today's stock, not historical values")
        if shipped["uncosted"]:
            turnover["notes"].append(f"{shipped['uncosted']} shipment line(s) have no product cost")
    cards.append(turnover)

    # Supplier delivery performance
    where, params, ignored = _where(scope, filters, dims=("warehouse", "category", "bpartner"),
                                    date_col="movement_date", extra=("movementtype = 'V+'",))
    receipts = db.query_one(
        f"""SELECT COUNT(*) AS lines, COUNT(days_late) AS matched,
                   COUNT(*) FILTER (WHERE days_late <= 0) AS on_time
            FROM v_inout_line WHERE {where}""",
        params,
    )
    supplier = _card("supplier_on_time", "Supplier on-time rate", "percent", ignored=ignored)
    if receipts["lines"] == 0:
        supplier.update(available=False, reason="No vendor receipts in this period")
    elif receipts["matched"] == 0:
        supplier.update(available=False, reason="No receipt is linked to an order line with a promised date")
    else:
        supplier["value"] = receipts["on_time"] / receipts["matched"]
        supplier["detail"] = f"{receipts['on_time']} of {receipts['matched']} receipt lines on or before the promised date"
        unmatched = receipts["lines"] - receipts["matched"]
        if unmatched:
            supplier["notes"].append(f"{unmatched} receipt line(s) not linked to an order line are left out")
    cards.append(supplier)

    cards.append(_card("stockout_risk", "Products at stockout risk", "count", available=False,
                       reason="Needs the demand forecast, which is added in Stage 4"))
    return cards


# --------------------------------------------------------------------------------------
# Charts and tables. Each returns {"rows": [...], "ignored": [...], "notes": [...], ...}.
# --------------------------------------------------------------------------------------

def _months(start: date, end: date) -> list[str]:
    out, year, month = [], start.year, start.month
    while (year, month) <= (end.year, end.month):
        out.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def _monthly(scope: Scope, filters: Filters, issotrx: str) -> dict[str, Any]:
    where, params, ignored = _where(scope, filters, dims=("category", "bpartner"), date_col="date_invoiced",
                                    extra=("issotrx = %(issotrx)s",))
    params["issotrx"] = issotrx
    found = db.query(
        f"""SELECT to_char(date_trunc('month', date_invoiced), 'YYYY-MM') AS month,
                   SUM(line_net_amt_base * sign) AS amount, COUNT(DISTINCT c_invoice_id) AS documents
            FROM v_invoice_line WHERE {where} GROUP BY 1 ORDER BY 1""",
        params,
    )
    if not found:
        return {"rows": [], "ignored": ignored, "notes": []}
    by_month = {r["month"]: r for r in found}
    # Months without invoices are shown as zero. For very long ranges, start at the first month with data.
    start, end = filters.date_from, min(filters.date_to, date.today())
    if (end.year - start.year) * 12 + end.month - start.month > 36:
        first = found[0]["month"]
        start = date(int(first[:4]), int(first[5:]), 1)
    rows = [{"month": m, "amount": by_month.get(m, {}).get("amount") or 0.0,
             "documents": by_month.get(m, {}).get("documents") or 0} for m in _months(start, end)]
    return {"rows": rows, "ignored": ignored, "notes": []}


def sales_monthly(scope: Scope, filters: Filters) -> dict[str, Any]:
    return _monthly(scope, filters, "Y")


def purchases_monthly(scope: Scope, filters: Filters) -> dict[str, Any]:
    return _monthly(scope, filters, "N")


def _sales_ranking(scope: Scope, filters: Filters, label_sql: str, join_sql: str, missing_label: str) -> dict[str, Any]:
    where, params, ignored = _where(scope, filters, dims=("category", "bpartner"), date_col="date_invoiced",
                                    alias="l", extra=("l.issotrx = 'Y'",))
    params["top_n"] = get_settings().top_n
    params["missing"] = missing_label
    rows = db.query(
        f"""SELECT COALESCE({label_sql}, %(missing)s) AS label,
                   SUM(l.line_net_amt_base * l.sign) AS amount, SUM(l.qty_invoiced * l.sign) AS quantity
            FROM v_invoice_line l {join_sql}
            WHERE {where}
            GROUP BY 1 ORDER BY 2 DESC NULLS LAST, 1 LIMIT %(top_n)s""",
        params,
    )
    return {"rows": rows, "ignored": ignored, "notes": []}


def sales_by_product(scope: Scope, filters: Filters) -> dict[str, Any]:
    return _sales_ranking(scope, filters, "p.product_name",
                          "LEFT JOIN v_product p ON p.m_product_id = l.m_product_id", "Charges and other lines")


def sales_by_category(scope: Scope, filters: Filters) -> dict[str, Any]:
    return _sales_ranking(scope, filters, "c.category_name",
                          "LEFT JOIN v_product_category c ON c.m_product_category_id = l.m_product_category_id",
                          "Charges and other lines")


def sales_by_customer(scope: Scope, filters: Filters) -> dict[str, Any]:
    return _sales_ranking(scope, filters, "b.bpartner_name",
                          "LEFT JOIN v_bpartner b ON b.c_bpartner_id = l.c_bpartner_id", "Unknown partner")


def _inventory_by(scope: Scope, filters: Filters, label_sql: str, join_sql: str) -> dict[str, Any]:
    where, params, ignored = _where(scope, filters, dims=("warehouse", "category"), date_col=None, alias="s",
                                    extra=("s.qty_on_hand <> 0",))
    params["max_rows"] = get_settings().max_rows
    rows = db.query(
        f"""SELECT {label_sql} AS label, COALESCE(SUM(s.stock_value_base), 0) AS value,
                   SUM(s.qty_on_hand) AS quantity, COUNT(DISTINCT s.m_product_id) AS products,
                   COUNT(DISTINCT s.m_product_id) FILTER (WHERE s.unit_cost IS NULL) AS uncosted
            FROM v_stock s {join_sql}
            WHERE {where}
            GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT %(max_rows)s""",
        params,
    )
    notes = []
    uncosted = sum(r["uncosted"] for r in rows)
    if uncosted:
        notes.append(f"{uncosted} product(s) have no cost in ADempiere and count as zero value")
    return {"rows": rows, "ignored": ignored, "notes": notes}


def inventory_by_warehouse(scope: Scope, filters: Filters) -> dict[str, Any]:
    return _inventory_by(scope, filters, "w.warehouse_name", "JOIN v_warehouse w ON w.m_warehouse_id = s.m_warehouse_id")


def inventory_by_category(scope: Scope, filters: Filters) -> dict[str, Any]:
    return _inventory_by(scope, filters, "c.category_name",
                         "JOIN v_product_category c ON c.m_product_category_id = s.m_product_category_id")


def slow_moving(scope: Scope, filters: Filters) -> dict[str, Any]:
    """Stock on hand whose last outbound movement is older than the configured threshold (or never happened)."""
    settings = get_settings()
    where, params, ignored = _where(scope, filters, dims=("warehouse", "category"), date_col=None, alias="s",
                                    extra=("s.qty_on_hand > 0",))
    params.update(threshold=settings.slow_moving_days, max_rows=settings.max_rows)
    rows = db.query(
        f"""SELECT p.product_name AS product, w.warehouse_name AS warehouse, s.qty_on_hand AS quantity,
                   s.stock_value_base AS value, m.last_out AS last_outbound,
                   (CURRENT_DATE - m.last_out) AS days_since
            FROM v_stock s
            JOIN v_product p ON p.m_product_id = s.m_product_id
            JOIN v_warehouse w ON w.m_warehouse_id = s.m_warehouse_id
            LEFT JOIN LATERAL (
                SELECT MAX(t.movement_date) AS last_out FROM v_stock_movement t
                WHERE t.m_product_id = s.m_product_id AND t.m_warehouse_id = s.m_warehouse_id
                  AND t.ad_client_id = s.ad_client_id AND t.movement_qty < 0
            ) m ON true
            WHERE {where} AND (m.last_out IS NULL OR CURRENT_DATE - m.last_out > %(threshold)s)
            ORDER BY s.stock_value_base DESC NULLS LAST, p.product_name LIMIT %(max_rows)s""",
        params,
    )
    for row in rows:
        if row["last_outbound"] is not None:
            row["last_outbound"] = row["last_outbound"].isoformat()
    return {"rows": rows, "ignored": ignored,
            "notes": [f"Rule: stock on hand with no outbound movement in the last {settings.slow_moving_days} days"]}


def supplier_performance(scope: Scope, filters: Filters) -> dict[str, Any]:
    where, params, ignored = _where(scope, filters, dims=("warehouse", "category", "bpartner"),
                                    date_col="movement_date", alias="l", extra=("l.movementtype = 'V+'",))
    params["max_rows"] = get_settings().max_rows
    rows = db.query(
        f"""SELECT b.bpartner_name AS supplier, COUNT(*) AS receipt_lines, COUNT(l.days_late) AS matched_lines,
                   COUNT(*) FILTER (WHERE l.days_late <= 0) AS on_time_lines,
                   CASE WHEN COUNT(l.days_late) > 0
                        THEN COUNT(*) FILTER (WHERE l.days_late <= 0)::numeric / COUNT(l.days_late) END AS on_time_rate,
                   AVG(l.days_late) AS avg_days_late, MAX(l.days_late) AS max_days_late
            FROM v_inout_line l JOIN v_bpartner b ON b.c_bpartner_id = l.c_bpartner_id
            WHERE {where}
            GROUP BY 1 ORDER BY 5 NULLS LAST, 2 DESC, 1 LIMIT %(max_rows)s""",
        params,
    )
    return {"rows": rows, "ignored": ignored,
            "notes": ["On time = received on or before the order line's promised date. "
                      "Receipt lines not linked to an order line cannot be rated."]}


AGING_BUCKETS = ["Not due", "1-30", "31-60", "61-90", "Over 90"]


def receivables_aging(scope: Scope, filters: Filters) -> dict[str, Any]:
    where, params, ignored = _where(scope, filters, dims=("bpartner",), date_col=None, extra=("issotrx = 'Y'",))
    found = {r["bucket"]: r for r in db.query(
        f"""SELECT aging_bucket AS bucket, SUM(open_amt_base) AS amount, COUNT(*) AS items
            FROM v_open_item WHERE {where} GROUP BY 1""",
        params,
    )}
    if not found:
        return {"rows": [], "ignored": ignored, "notes": []}
    rows = [{"bucket": b, "amount": found.get(b, {}).get("amount") or 0.0, "items": found.get(b, {}).get("items") or 0}
            for b in AGING_BUCKETS]
    return {"rows": rows, "ignored": ignored, "notes": []}


def receivables_open(scope: Scope, filters: Filters) -> dict[str, Any]:
    where, params, ignored = _where(scope, filters, dims=("bpartner",), date_col=None, alias="o", extra=("o.issotrx = 'Y'",))
    params["max_rows"] = get_settings().max_rows
    rows = db.query(
        f"""SELECT o.documentno AS invoice, b.bpartner_name AS customer, o.date_invoiced, o.due_date,
                   o.days_due, o.aging_bucket AS bucket, o.open_amt_base AS open_amount
            FROM v_open_item o JOIN v_bpartner b ON b.c_bpartner_id = o.c_bpartner_id
            WHERE {where} ORDER BY o.days_due DESC, o.documentno LIMIT %(max_rows)s""",
        params,
    )
    for row in rows:
        row["date_invoiced"] = row["date_invoiced"].isoformat()
        row["due_date"] = row["due_date"].isoformat() if row["due_date"] else None
    return {"rows": rows, "ignored": ignored, "notes": []}


# name -> (function, basis shown under the chart title, True when the date range applies)
CHARTS: dict[str, tuple[Callable[[Scope, Filters], dict[str, Any]], str, bool]] = {
    "sales_monthly": (sales_monthly, "Customer invoice lines by invoice date, net of credit memos, before tax", True),
    "sales_by_product": (sales_by_product, "Customer invoice lines by invoice date, before tax", True),
    "sales_by_category": (sales_by_category, "Customer invoice lines by invoice date, before tax", True),
    "sales_by_customer": (sales_by_customer, "Customer invoice lines by invoice date, before tax", True),
    "purchases_monthly": (purchases_monthly, "Vendor invoice lines by invoice date, net of credit memos, before tax", True),
    "inventory_by_warehouse": (inventory_by_warehouse, "Quantity on hand x unit cost, as of today", False),
    "inventory_by_category": (inventory_by_category, "Quantity on hand x unit cost, as of today", False),
    "slow_moving": (slow_moving, "Stock on hand and stock movements, as of today", False),
    "supplier_performance": (supplier_performance, "Vendor receipt lines by movement date", True),
    "receivables_aging": (receivables_aging, "Open customer invoices by days past due, as of today", False),
    "receivables_open": (receivables_open, "Open customer invoices, as of today", False),
}


def chart(name: str, scope: Scope, filters: Filters) -> dict[str, Any]:
    function, basis, uses_dates = CHARTS[name]
    result = function(scope, filters)
    result["basis"] = basis
    result["period"] = _period(filters) if uses_dates else None
    return result


# --------------------------------------------------------------------------------------
# Filter options
# --------------------------------------------------------------------------------------

def filter_options(scope: Scope) -> dict[str, list[dict[str, Any]]]:
    params = {"client": scope.client_id, "orgs": list(scope.org_ids), "max_rows": 1000}
    return {
        "orgs": db.query(
            "SELECT ad_org_id::int AS id, org_name AS name FROM v_org "
            "WHERE ad_client_id = %(client)s AND ad_org_id = ANY(%(orgs)s::numeric[]) ORDER BY 2", params),
        "warehouses": db.query(
            "SELECT m_warehouse_id::int AS id, warehouse_name AS name, ad_org_id::int AS org_id FROM v_warehouse "
            "WHERE ad_client_id = %(client)s AND ad_org_id = ANY(%(orgs)s::numeric[]) ORDER BY 2", params),
        "categories": db.query(
            "SELECT m_product_category_id::int AS id, category_name AS name FROM v_product_category "
            "WHERE ad_client_id = %(client)s ORDER BY 2", params),
        "bpartners": db.query(
            "SELECT c_bpartner_id::int AS id, bpartner_name AS name FROM v_bpartner "
            "WHERE ad_client_id = %(client)s AND isactive = 'Y' AND (iscustomer = 'Y' OR isvendor = 'Y') "
            "ORDER BY 2 LIMIT %(max_rows)s", params),
    }
