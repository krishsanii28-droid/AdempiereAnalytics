-- ADempiere InsightAI - database objects (Stage 2)
--
-- Creates, in the ADempiere database:
--   * role  insightai_owner  NOLOGIN, owns the insightai schema, may read a fixed list of ADempiere tables
--   * role  insightai_ro     the only role the analytics service logs in with (password set by 02_login_role.sql)
--   * schema insightai       read-only analytical views and three helper functions
--
-- Nothing in the adempiere schema is created, altered or dropped. The only change outside
-- the insightai schema is a set of SELECT grants to insightai_owner (removed by 99_uninstall.sql).
--
-- Run as a superuser (the adempiere or postgres role) with:  psql -v ON_ERROR_STOP=1 -1 -f 01_install.sql
-- Safe to re-run.

\set ON_ERROR_STOP on

-- ---------------------------------------------------------------------------------------
-- Roles
-- ---------------------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'insightai_owner') THEN
    CREATE ROLE insightai_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'insightai_ro') THEN
    CREATE ROLE insightai_ro NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT CONNECTION LIMIT 10;
  END IF;
END $$;

CREATE SCHEMA IF NOT EXISTS insightai AUTHORIZATION insightai_owner;
COMMENT ON SCHEMA insightai IS 'ADempiere InsightAI: read-only analytical views. Not part of ADempiere; remove with 99_uninstall.sql';

-- ---------------------------------------------------------------------------------------
-- What the view owner may read. Views run with the owner's rights, so this list is the
-- complete set of ADempiere data that can ever reach the analytics service.
-- ---------------------------------------------------------------------------------------
GRANT USAGE ON SCHEMA adempiere TO insightai_owner;

DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    -- organisation and access model
    'ad_client','ad_clientinfo','ad_org','ad_role','ad_user_roles','ad_role_orgaccess','ad_user_orgaccess',
    'ad_tree','ad_treenode',
    -- currency
    'c_acctschema','c_currency','c_conversion_rate','c_conversiontype','c_conversiontype_default',
    -- documents
    'c_doctype','c_order','c_orderline','c_invoice','c_invoiceline','c_invoicepayschedule','c_paymentterm',
    'c_allocationhdr','c_allocationline','m_inout','m_inoutline',
    -- read inside invoiceOpen() / paymentTermDueDate(). invoiceOpen() swallows errors and returns
    -- NULL, so a missing grant here shows up as "no open invoices", not as an error.
    'c_invoice_v','c_nonbusinessday',
    -- master data
    'c_bpartner','c_bp_group','m_product','m_product_category','c_uom','m_warehouse','m_locator',
    -- stock and cost
    'm_storage','m_transaction','m_cost','m_costelement','m_costtype',
    -- ADempiere's own open-item logic
    'rv_openitem','rv_c_invoice']
  LOOP
    IF to_regclass('adempiere.' || t) IS NOT NULL THEN
      EXECUTE format('GRANT SELECT ON adempiere.%I TO insightai_owner', t);
    END IF;
  END LOOP;
END $$;

-- AD_User holds password columns: grant only the columns needed to show who is logged in.
GRANT SELECT (ad_user_id, ad_client_id, name, isactive) ON adempiere.ad_user TO insightai_owner;

-- ---------------------------------------------------------------------------------------
-- Everything below is created as insightai_owner, so nothing in this schema is superuser-owned.
-- ---------------------------------------------------------------------------------------
SET ROLE insightai_owner;

-- ADempiere's PL/pgSQL helpers (currencyConvert, invoiceOpen ...) read tables with the rights of
-- whoever calls them. insightai_ro has no rights on the adempiere schema, so these three
-- SECURITY DEFINER wrappers run that logic as insightai_owner instead.

CREATE OR REPLACE FUNCTION insightai.base_currency_id(p_client numeric)
RETURNS numeric
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = adempiere, pg_temp
AS $$
  SELECT a.c_currency_id
  FROM adempiere.ad_clientinfo ci
  JOIN adempiere.c_acctschema a ON a.c_acctschema_id = ci.c_acctschema1_id
  WHERE ci.ad_client_id = p_client
$$;
COMMENT ON FUNCTION insightai.base_currency_id(numeric) IS 'Currency of the primary accounting schema of the client';

-- Converts a document amount to the primary accounting schema currency at the document date,
-- using the document's conversion type. Returns NULL when ADempiere has no rate.
CREATE OR REPLACE FUNCTION insightai.to_base(p_amount numeric, p_currency numeric, p_date timestamp,
                                             p_conversiontype numeric, p_client numeric, p_org numeric)
RETURNS numeric
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = adempiere, pg_temp
SET client_min_messages = warning
AS $$
  SELECT adempiere.currencyconvert(p_amount, p_currency, insightai.base_currency_id(p_client),
                                   p_date::timestamptz, p_conversiontype, p_client, p_org)
$$;

-- Open invoices exactly as ADempiere computes them (view RV_OpenItem: completed/closed invoices
-- with a non-zero open amount, pay schedules split out, credit memos negative).
CREATE OR REPLACE FUNCTION insightai.open_items()
RETURNS TABLE (ad_client_id numeric, ad_org_id numeric, c_invoice_id numeric, documentno text,
               c_bpartner_id numeric, issotrx text, c_doctype_id numeric, date_invoiced date,
               due_date date, days_due integer, c_invoicepayschedule_id numeric, c_currency_id numeric,
               grand_total numeric, paid_amt numeric, open_amt numeric, open_amt_base numeric)
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = adempiere, pg_temp
SET client_min_messages = warning
AS $$
  SELECT oi.ad_client_id, oi.ad_org_id, oi.c_invoice_id, oi.documentno::text,
         oi.c_bpartner_id, oi.issotrx::text, oi.c_doctype_id, oi.dateinvoiced::date,
         oi.duedate::date, oi.daysdue::integer, oi.c_invoicepayschedule_id, oi.c_currency_id,
         oi.grandtotal, oi.paidamt, oi.openamt,
         adempiere.currencyconvert(oi.openamt, oi.c_currency_id, insightai.base_currency_id(oi.ad_client_id),
                                   oi.dateinvoiced::timestamptz, oi.c_conversiontype_id, oi.ad_client_id, oi.ad_org_id)
  FROM adempiere.rv_openitem oi
$$;

-- ---------------------------------------------------------------------------------------
-- Access model
-- ---------------------------------------------------------------------------------------

-- One row per (user, role, organisation) the user may see through that role.
-- Mirrors MRole.loadOrgAccess: all orgs of the client when IsAccessAllOrgs, AD_User_OrgAccess when
-- IsUseUserOrgAccess, otherwise AD_Role_OrgAccess; summary orgs expand to their children in the
-- client's organisation tree. Org 0 (*) and summary orgs themselves are not returned because no
-- business document carries them.
CREATE OR REPLACE VIEW insightai.v_user_role_org AS
WITH RECURSIVE org_tree AS (
  SELECT ci.ad_client_id, tn.node_id AS ad_org_id, tn.parent_id
  FROM adempiere.ad_clientinfo ci
  JOIN adempiere.ad_treenode tn ON tn.ad_tree_id = ci.ad_tree_org_id
),
expand (ad_client_id, granted_org_id, ad_org_id) AS (
  SELECT o.ad_client_id, o.ad_org_id, o.ad_org_id
  FROM adempiere.ad_org o
  UNION ALL
  SELECT e.ad_client_id, e.granted_org_id, t.ad_org_id
  FROM expand e
  JOIN org_tree t ON t.ad_client_id = e.ad_client_id AND t.parent_id = e.ad_org_id
  WHERE e.ad_org_id <> 0
),
user_role AS (
  SELECT ur.ad_user_id, r.ad_role_id, r.ad_client_id, r.isaccessallorgs, r.isuseuserorgaccess
  FROM adempiere.ad_user_roles ur
  JOIN adempiere.ad_role r ON r.ad_role_id = ur.ad_role_id AND r.isactive = 'Y'
  JOIN adempiere.ad_user u ON u.ad_user_id = ur.ad_user_id AND u.isactive = 'Y'
  WHERE ur.isactive = 'Y'
),
granted AS (
  SELECT x.ad_user_id, x.ad_role_id, x.ad_client_id, o.ad_org_id
  FROM user_role x
  JOIN adempiere.ad_org o ON o.ad_client_id = x.ad_client_id
  WHERE x.isaccessallorgs = 'Y'
  UNION
  SELECT x.ad_user_id, x.ad_role_id, x.ad_client_id, ra.ad_org_id
  FROM user_role x
  JOIN adempiere.ad_role_orgaccess ra ON ra.ad_role_id = x.ad_role_id AND ra.isactive = 'Y'
  WHERE x.isaccessallorgs <> 'Y' AND x.isuseuserorgaccess <> 'Y'
  UNION
  SELECT x.ad_user_id, x.ad_role_id, x.ad_client_id, ua.ad_org_id
  FROM user_role x
  JOIN adempiere.ad_user_orgaccess ua ON ua.ad_user_id = x.ad_user_id AND ua.isactive = 'Y'
  WHERE x.isaccessallorgs <> 'Y' AND x.isuseuserorgaccess = 'Y'
)
SELECT DISTINCT g.ad_user_id, g.ad_role_id, g.ad_client_id, o.ad_org_id
FROM granted g
JOIN expand e ON e.granted_org_id = g.ad_org_id
JOIN adempiere.ad_org o ON o.ad_org_id = e.ad_org_id
WHERE o.isactive = 'Y' AND o.issummary = 'N' AND o.ad_org_id <> 0 AND o.ad_client_id = g.ad_client_id;

CREATE OR REPLACE VIEW insightai.v_user_role AS
SELECT ur.ad_user_id, u.name AS user_name, r.ad_role_id, r.name AS role_name,
       r.ad_client_id, c.name AS client_name, cur.iso_code AS base_currency
FROM adempiere.ad_user_roles ur
JOIN adempiere.ad_user u ON u.ad_user_id = ur.ad_user_id AND u.isactive = 'Y'
JOIN adempiere.ad_role r ON r.ad_role_id = ur.ad_role_id AND r.isactive = 'Y'
JOIN adempiere.ad_client c ON c.ad_client_id = r.ad_client_id
LEFT JOIN adempiere.c_currency cur ON cur.c_currency_id = insightai.base_currency_id(r.ad_client_id)
WHERE ur.isactive = 'Y';

-- ---------------------------------------------------------------------------------------
-- Dimensions (for filters and labels)
-- ---------------------------------------------------------------------------------------
CREATE OR REPLACE VIEW insightai.v_org AS
SELECT o.ad_client_id, o.ad_org_id, o.value AS org_key, o.name AS org_name
FROM adempiere.ad_org o
WHERE o.isactive = 'Y' AND o.issummary = 'N' AND o.ad_org_id <> 0;

CREATE OR REPLACE VIEW insightai.v_warehouse AS
SELECT w.ad_client_id, w.ad_org_id, w.m_warehouse_id, w.value AS warehouse_key, w.name AS warehouse_name
FROM adempiere.m_warehouse w
WHERE w.isactive = 'Y';

CREATE OR REPLACE VIEW insightai.v_product_category AS
SELECT pc.ad_client_id, pc.m_product_category_id, pc.name AS category_name
FROM adempiere.m_product_category pc
WHERE pc.isactive = 'Y';

-- Products are shared across organisations (AD_Org_ID is usually 0), so this view is filtered by client only.
CREATE OR REPLACE VIEW insightai.v_product AS
SELECT p.ad_client_id, p.m_product_id, p.value AS product_key, p.name AS product_name,
       p.m_product_category_id, pc.name AS category_name, u.name AS uom_name,
       p.producttype, p.isstocked, p.issold, p.ispurchased, p.isactive
FROM adempiere.m_product p
JOIN adempiere.m_product_category pc ON pc.m_product_category_id = p.m_product_category_id
LEFT JOIN adempiere.c_uom u ON u.c_uom_id = p.c_uom_id;

-- Business partners are shared across organisations as well.
CREATE OR REPLACE VIEW insightai.v_bpartner AS
SELECT bp.ad_client_id, bp.c_bpartner_id, bp.value AS bpartner_key, bp.name AS bpartner_name,
       g.name AS bp_group_name, bp.iscustomer, bp.isvendor, bp.isactive
FROM adempiere.c_bpartner bp
LEFT JOIN adempiere.c_bp_group g ON g.c_bp_group_id = bp.c_bp_group_id;

-- ---------------------------------------------------------------------------------------
-- Facts. Every fact view:
--   * carries AD_Client_ID and the document header's AD_Org_ID (the service filters on both)
--   * contains only active documents with DocStatus CO or CL
--   * exposes amounts in document currency and in the accounting schema currency (*_base),
--     where *_base is NULL if ADempiere has no conversion rate
--   * keeps returns / credit memos as separate, flagged rows; the signed columns (net_*) subtract them
-- ---------------------------------------------------------------------------------------

-- Sales and purchase order lines. Date basis: DateOrdered.
-- Proposals and quotations (DocSubTypeSO ON / OB) are not orders and are excluded.
CREATE OR REPLACE VIEW insightai.v_order_line AS
SELECT o.ad_client_id, o.ad_org_id, o.c_order_id, o.documentno, ol.c_orderline_id,
       o.issotrx, o.docstatus, dt.name AS doctype_name, dt.docsubtypeso,
       (COALESCE(dt.docsubtypeso, '') = 'RM') AS is_return,
       o.dateordered::date AS date_ordered,
       COALESCE(ol.datepromised, o.datepromised)::date AS date_promised,
       o.c_bpartner_id, COALESCE(ol.m_warehouse_id, o.m_warehouse_id) AS m_warehouse_id,
       ol.m_product_id, p.m_product_category_id, ol.c_charge_id,
       ol.qtyordered AS qty_ordered, ol.qtydelivered AS qty_delivered, ol.qtyinvoiced AS qty_invoiced,
       CASE WHEN o.docstatus = 'CO' THEN GREATEST(ol.qtyordered - ol.qtydelivered, 0) ELSE 0 END AS qty_open,
       ol.priceactual AS price_actual, ol.pricelist AS price_list,
       o.c_currency_id, ol.linenetamt AS line_net_amt,
       insightai.to_base(ol.linenetamt, o.c_currency_id, o.dateordered, o.c_conversiontype_id, o.ad_client_id, o.ad_org_id) AS line_net_amt_base,
       CASE WHEN COALESCE(dt.docsubtypeso, '') = 'RM' THEN -1 ELSE 1 END AS sign
FROM adempiere.c_order o
JOIN adempiere.c_orderline ol ON ol.c_order_id = o.c_order_id AND ol.isactive = 'Y'
JOIN adempiere.c_doctype dt ON dt.c_doctype_id = o.c_doctype_id
LEFT JOIN adempiere.m_product p ON p.m_product_id = ol.m_product_id
WHERE o.isactive = 'Y'
  AND o.docstatus IN ('CO', 'CL')
  AND dt.docbasetype IN ('SOO', 'POO')
  AND COALESCE(dt.docsubtypeso, '') NOT IN ('ON', 'OB');

-- Customer (AR) and vendor (AP) invoice headers. Date basis: DateInvoiced (DateAcct also exposed).
-- Credit memos (DocBaseType ARC / APC) are flagged and carry sign = -1.
CREATE OR REPLACE VIEW insightai.v_invoice AS
SELECT i.ad_client_id, i.ad_org_id, i.c_invoice_id, i.documentno, i.issotrx, i.docstatus,
       dt.name AS doctype_name, dt.docbasetype, (dt.docbasetype IN ('ARC', 'APC')) AS is_credit_memo,
       i.dateinvoiced::date AS date_invoiced, i.dateacct::date AS date_acct,
       i.c_bpartner_id, i.c_order_id, i.ispaid, i.c_currency_id,
       i.totallines AS total_lines, i.grandtotal AS grand_total,
       insightai.to_base(i.totallines, i.c_currency_id, i.dateinvoiced, i.c_conversiontype_id, i.ad_client_id, i.ad_org_id) AS total_lines_base,
       insightai.to_base(i.grandtotal, i.c_currency_id, i.dateinvoiced, i.c_conversiontype_id, i.ad_client_id, i.ad_org_id) AS grand_total_base,
       CASE WHEN dt.docbasetype IN ('ARC', 'APC') THEN -1 ELSE 1 END AS sign
FROM adempiere.c_invoice i
JOIN adempiere.c_doctype dt ON dt.c_doctype_id = i.c_doctype_id
WHERE i.isactive = 'Y'
  AND i.docstatus IN ('CO', 'CL')
  AND dt.docbasetype IN ('ARI', 'ARC', 'API', 'APC');

-- Invoice lines, for breakdowns by product / category / partner. LineNetAmt excludes tax
-- (unless the price list is tax-inclusive). Lines without a product are charges or comments.
CREATE OR REPLACE VIEW insightai.v_invoice_line AS
SELECT i.ad_client_id, i.ad_org_id, i.c_invoice_id, i.documentno, il.c_invoiceline_id,
       i.issotrx, i.docstatus, dt.docbasetype, (dt.docbasetype IN ('ARC', 'APC')) AS is_credit_memo,
       i.dateinvoiced::date AS date_invoiced, i.dateacct::date AS date_acct,
       i.c_bpartner_id, il.m_product_id, p.m_product_category_id, il.c_charge_id, il.c_orderline_id,
       il.qtyinvoiced AS qty_invoiced, il.priceactual AS price_actual,
       i.c_currency_id, il.linenetamt AS line_net_amt,
       insightai.to_base(il.linenetamt, i.c_currency_id, i.dateinvoiced, i.c_conversiontype_id, i.ad_client_id, i.ad_org_id) AS line_net_amt_base,
       CASE WHEN dt.docbasetype IN ('ARC', 'APC') THEN -1 ELSE 1 END AS sign
FROM adempiere.c_invoice i
JOIN adempiere.c_invoiceline il ON il.c_invoice_id = i.c_invoice_id AND il.isactive = 'Y'
JOIN adempiere.c_doctype dt ON dt.c_doctype_id = i.c_doctype_id
LEFT JOIN adempiere.m_product p ON p.m_product_id = il.m_product_id
WHERE i.isactive = 'Y'
  AND i.docstatus IN ('CO', 'CL')
  AND dt.docbasetype IN ('ARI', 'ARC', 'API', 'APC');

-- Shipment and receipt lines. Date basis: MovementDate.
-- MovementType: C- customer shipment, C+ customer return, V+ vendor receipt, V- vendor return.
-- days_late compares a vendor receipt with the promised date of the order line it fulfils
-- (NULL when the receipt line is not linked to an order line).
CREATE OR REPLACE VIEW insightai.v_inout_line AS
SELECT io.ad_client_id, io.ad_org_id, io.m_inout_id, io.documentno, iol.m_inoutline_id,
       io.issotrx, io.docstatus, io.movementtype, (io.movementtype IN ('C+', 'V-')) AS is_return,
       io.movementdate::date AS movement_date,
       io.c_bpartner_id, io.m_warehouse_id, iol.m_product_id, p.m_product_category_id,
       iol.movementqty AS movement_qty,
       iol.c_orderline_id, ol.datepromised::date AS date_promised,
       CASE WHEN io.movementtype = 'V+' AND ol.datepromised IS NOT NULL
            THEN io.movementdate::date - ol.datepromised::date END AS days_late
FROM adempiere.m_inout io
JOIN adempiere.m_inoutline iol ON iol.m_inout_id = io.m_inout_id AND iol.isactive = 'Y'
LEFT JOIN adempiere.c_orderline ol ON ol.c_orderline_id = iol.c_orderline_id
LEFT JOIN adempiere.m_product p ON p.m_product_id = iol.m_product_id
WHERE io.isactive = 'Y'
  AND io.docstatus IN ('CO', 'CL')
  AND io.movementtype IN ('C-', 'C+', 'V+', 'V-');

-- Daily demand per product and warehouse from customer shipments, with returns kept separate.
-- Days without a shipment have no row; the forecasting code fills them with zero.
CREATE OR REPLACE VIEW insightai.v_demand_daily AS
SELECT l.ad_client_id, l.ad_org_id, l.m_warehouse_id, l.m_product_id, l.m_product_category_id,
       l.movement_date AS demand_date,
       SUM(CASE WHEN l.movementtype = 'C-' THEN l.movement_qty ELSE 0 END) AS qty_shipped,
       SUM(CASE WHEN l.movementtype = 'C+' THEN l.movement_qty ELSE 0 END) AS qty_returned,
       SUM(CASE WHEN l.movementtype = 'C-' THEN l.movement_qty ELSE -l.movement_qty END) AS qty_net
FROM insightai.v_inout_line l
WHERE l.movementtype IN ('C-', 'C+') AND l.m_product_id IS NOT NULL
GROUP BY l.ad_client_id, l.ad_org_id, l.m_warehouse_id, l.m_product_id, l.m_product_category_id, l.movement_date;

-- Open receivables and payables, from ADempiere's RV_OpenItem. days_due > 0 means overdue.
CREATE OR REPLACE VIEW insightai.v_open_item AS
SELECT oi.ad_client_id, oi.ad_org_id, oi.c_invoice_id, oi.documentno, oi.c_bpartner_id, oi.issotrx,
       dt.docbasetype, oi.date_invoiced, oi.due_date, oi.days_due,
       CASE WHEN oi.days_due <= 0 THEN 'Not due'
            WHEN oi.days_due <= 30 THEN '1-30'
            WHEN oi.days_due <= 60 THEN '31-60'
            WHEN oi.days_due <= 90 THEN '61-90'
            ELSE 'Over 90' END AS aging_bucket,
       oi.c_invoicepayschedule_id, oi.c_currency_id,
       oi.grand_total, oi.paid_amt, oi.open_amt, oi.open_amt_base
FROM insightai.open_items() oi
JOIN adempiere.c_doctype dt ON dt.c_doctype_id = oi.c_doctype_id;

-- Unit cost per product in the accounting schema currency.
-- First choice: the material cost for the accounting schema's own cost type (how ADempiere values
-- stock in the ledger). Fallback: the standard-cost cost type. cost_source says which was used;
-- unit_cost is NULL when neither holds a non-zero cost.
CREATE OR REPLACE VIEW insightai.v_product_cost AS
WITH material AS (
  SELECT c.ad_client_id, c.m_product_id, c.m_costtype_id, ct.costingmethod,
         (c.m_costtype_id = a.m_costtype_id) AS is_schema_costtype,
         AVG(c.currentcostprice) AS cost
  FROM adempiere.m_cost c
  JOIN adempiere.m_costelement ce ON ce.m_costelement_id = c.m_costelement_id AND ce.costelementtype = 'M' AND ce.isactive = 'Y'
  JOIN adempiere.m_costtype ct ON ct.m_costtype_id = c.m_costtype_id
  JOIN adempiere.ad_clientinfo ci ON ci.ad_client_id = c.ad_client_id
  JOIN adempiere.c_acctschema a ON a.c_acctschema_id = ci.c_acctschema1_id AND a.c_acctschema_id = c.c_acctschema_id
  WHERE c.isactive = 'Y' AND c.currentcostprice <> 0
  GROUP BY c.ad_client_id, c.m_product_id, c.m_costtype_id, ct.costingmethod, a.m_costtype_id
)
SELECT p.ad_client_id, p.m_product_id,
       COALESCE(s.cost, d.cost) AS unit_cost,
       CASE WHEN s.cost IS NOT NULL THEN 'ACCT_SCHEMA_COST_TYPE'
            WHEN d.cost IS NOT NULL THEN 'STANDARD_COST' END AS cost_source
FROM adempiere.m_product p
LEFT JOIN material s ON s.m_product_id = p.m_product_id AND s.is_schema_costtype
LEFT JOIN LATERAL (
  SELECT AVG(m.cost) AS cost FROM material m
  WHERE m.m_product_id = p.m_product_id AND NOT m.is_schema_costtype AND m.costingmethod = 'S'
) d ON true;

-- Stock per product and warehouse. Organisation is the warehouse's organisation.
-- qty_available = QtyOnHand - QtyReserved; qty_ordered = quantity on open purchase orders.
CREATE OR REPLACE VIEW insightai.v_stock AS
SELECT s.ad_client_id, w.ad_org_id, w.m_warehouse_id, s.m_product_id, p.m_product_category_id,
       SUM(s.qtyonhand) AS qty_on_hand, SUM(s.qtyreserved) AS qty_reserved, SUM(s.qtyordered) AS qty_ordered,
       SUM(s.qtyonhand - s.qtyreserved) AS qty_available,
       c.unit_cost, c.cost_source,
       SUM(s.qtyonhand) * c.unit_cost AS stock_value_base
FROM adempiere.m_storage s
JOIN adempiere.m_locator l ON l.m_locator_id = s.m_locator_id
JOIN adempiere.m_warehouse w ON w.m_warehouse_id = l.m_warehouse_id
JOIN adempiere.m_product p ON p.m_product_id = s.m_product_id
LEFT JOIN insightai.v_product_cost c ON c.m_product_id = s.m_product_id
GROUP BY s.ad_client_id, w.ad_org_id, w.m_warehouse_id, s.m_product_id, p.m_product_category_id, c.unit_cost, c.cost_source;

-- Every stock movement (M_Transaction). MovementQty is signed: negative leaves the warehouse.
-- Used for slow-moving stock (last movement date) and inventory turnover.
CREATE OR REPLACE VIEW insightai.v_stock_movement AS
SELECT t.ad_client_id, w.ad_org_id, w.m_warehouse_id, t.m_product_id, p.m_product_category_id,
       t.movementdate::date AS movement_date, t.movementtype, t.movementqty AS movement_qty
FROM adempiere.m_transaction t
JOIN adempiere.m_locator l ON l.m_locator_id = t.m_locator_id
JOIN adempiere.m_warehouse w ON w.m_warehouse_id = l.m_warehouse_id
JOIN adempiere.m_product p ON p.m_product_id = t.m_product_id
WHERE t.isactive = 'Y';

RESET ROLE;

-- ---------------------------------------------------------------------------------------
-- What the service login may do: read the insightai views, call the three helpers. Nothing else.
-- ---------------------------------------------------------------------------------------
REVOKE ALL ON SCHEMA insightai FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA insightai FROM PUBLIC;

GRANT USAGE ON SCHEMA insightai TO insightai_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA insightai TO insightai_ro;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA insightai TO insightai_ro;
ALTER DEFAULT PRIVILEGES FOR ROLE insightai_owner IN SCHEMA insightai GRANT SELECT ON TABLES TO insightai_ro;

-- PostgreSQL 14 lets every role create tables in schema public and temp tables in the database.
-- A session can switch default_transaction_read_only off again, so "read-only" has to rest on
-- privileges. These two revokes close that gap for all non-superuser roles (the adempiere role
-- is a superuser and is not affected). 99_uninstall.sql restores both defaults.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
DO $$ BEGIN EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC', current_database()); END $$;

ALTER ROLE insightai_ro SET default_transaction_read_only = on;
ALTER ROLE insightai_ro SET statement_timeout = '15s';
ALTER ROLE insightai_ro SET search_path = insightai;
ALTER ROLE insightai_ro SET client_min_messages = warning;
