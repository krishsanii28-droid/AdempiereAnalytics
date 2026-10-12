-- Compares the insightai views with ADempiere's own figures and raw tables.
-- Run as the adempiere role through scripts\db_crosscheck.ps1 (the session is read-only).
-- Every row should say PASS. :client is the AD_Client_ID to check (default 11, GardenWorld).

\set ON_ERROR_STOP on
SET client_min_messages = warning;
SET search_path = adempiere;
\if :{?client} \else \set client 11 \endif

WITH checks(name, insightai_value, adempiere_value) AS (
  -- ADempiere's own Performance measure "Invoiced Gross Revenue": RV_C_Invoice, IsSOTrx='Y', Processed='Y'
  SELECT 'Customer invoices this year, gross',
         (SELECT COALESCE(SUM(grand_total_base * sign), 0) FROM insightai.v_invoice
           WHERE ad_client_id = :client AND issotrx = 'Y' AND date_invoiced >= date_trunc('year', current_date)),
         (SELECT COALESCE(SUM(currencybase(grandtotal, c_currency_id, dateacct, ad_client_id, ad_org_id)), 0) FROM rv_c_invoice
           WHERE ad_client_id = :client AND issotrx = 'Y' AND processed = 'Y' AND docstatus IN ('CO', 'CL')
             AND dateinvoiced >= date_trunc('year', current_date))
  UNION ALL
  -- ADempiere's own Performance measure "Open Invoice Amount"
  SELECT 'Open customer invoices, base currency',
         (SELECT COALESCE(SUM(open_amt_base), 0) FROM insightai.v_open_item WHERE ad_client_id = :client AND issotrx = 'Y'),
         (SELECT COALESCE(SUM(currencybase(invoiceopen(c_invoice_id, c_invoicepayschedule_id), c_currency_id, dateacct, ad_client_id, ad_org_id)), 0)
            FROM c_invoice_v WHERE ad_client_id = :client AND issotrx = 'Y' AND processed = 'Y' AND docstatus IN ('CO', 'CL'))
  UNION ALL
  SELECT 'Open item rows (RV_OpenItem)',
         (SELECT COUNT(*) FROM insightai.v_open_item WHERE ad_client_id = :client),
         (SELECT COUNT(*) FROM rv_openitem WHERE ad_client_id = :client)
  UNION ALL
  SELECT 'Quantity on hand (M_Storage)',
         (SELECT COALESCE(SUM(qty_on_hand), 0) FROM insightai.v_stock WHERE ad_client_id = :client),
         (SELECT COALESCE(SUM(qtyonhand), 0) FROM m_storage WHERE ad_client_id = :client)
  UNION ALL
  SELECT 'Quantity reserved (M_Storage)',
         (SELECT COALESCE(SUM(qty_reserved), 0) FROM insightai.v_stock WHERE ad_client_id = :client),
         (SELECT COALESCE(SUM(qtyreserved), 0) FROM m_storage WHERE ad_client_id = :client)
  UNION ALL
  SELECT 'Quantity ordered (M_Storage)',
         (SELECT COALESCE(SUM(qty_ordered), 0) FROM insightai.v_stock WHERE ad_client_id = :client),
         (SELECT COALESCE(SUM(qtyordered), 0) FROM m_storage WHERE ad_client_id = :client)
  UNION ALL
  SELECT 'Completed and closed customer invoices (C_Invoice)',
         (SELECT COUNT(*) FROM insightai.v_invoice WHERE ad_client_id = :client AND issotrx = 'Y'),
         (SELECT COUNT(*) FROM c_invoice WHERE ad_client_id = :client AND issotrx = 'Y' AND isactive = 'Y' AND docstatus IN ('CO', 'CL'))
  UNION ALL
  SELECT 'Completed and closed vendor invoices (C_Invoice)',
         (SELECT COUNT(*) FROM insightai.v_invoice WHERE ad_client_id = :client AND issotrx = 'N'),
         (SELECT COUNT(*) FROM c_invoice WHERE ad_client_id = :client AND issotrx = 'N' AND isactive = 'Y' AND docstatus IN ('CO', 'CL'))
  UNION ALL
  SELECT 'Customer invoice net lines (C_InvoiceLine)',
         (SELECT COALESCE(SUM(line_net_amt), 0) FROM insightai.v_invoice_line WHERE ad_client_id = :client AND issotrx = 'Y'),
         (SELECT COALESCE(SUM(il.linenetamt), 0) FROM c_invoiceline il JOIN c_invoice i ON i.c_invoice_id = il.c_invoice_id
           WHERE i.ad_client_id = :client AND i.issotrx = 'Y' AND i.isactive = 'Y' AND il.isactive = 'Y' AND i.docstatus IN ('CO', 'CL'))
  UNION ALL
  -- Shipment lines for stocked items must agree with the stock ledger
  SELECT 'Customer shipment quantity, stocked items (M_Transaction C-)',
         (SELECT COALESCE(SUM(movement_qty), 0) FROM insightai.v_inout_line WHERE ad_client_id = :client AND movementtype = 'C-' AND is_stocked_item),
         (SELECT COALESCE(-SUM(movementqty), 0) FROM m_transaction WHERE ad_client_id = :client AND movementtype = 'C-')
  UNION ALL
  SELECT 'Demand used for forecasting (M_Transaction C- and C+)',
         (SELECT COALESCE(SUM(qty_net), 0) FROM insightai.v_demand_daily WHERE ad_client_id = :client),
         (SELECT COALESCE(-SUM(movementqty), 0) FROM m_transaction WHERE ad_client_id = :client AND movementtype IN ('C-', 'C+'))
  UNION ALL
  SELECT 'Vendor receipt quantity, stocked items (M_Transaction V+)',
         (SELECT COALESCE(SUM(movement_qty), 0) FROM insightai.v_inout_line WHERE ad_client_id = :client AND movementtype = 'V+' AND is_stocked_item),
         (SELECT COALESCE(SUM(movementqty), 0) FROM m_transaction WHERE ad_client_id = :client AND movementtype = 'V+')
  UNION ALL
  SELECT 'Stock movement rows (M_Transaction)',
         (SELECT COUNT(*) FROM insightai.v_stock_movement WHERE ad_client_id = :client),
         (SELECT COUNT(*) FROM m_transaction WHERE ad_client_id = :client AND isactive = 'Y')
  UNION ALL
  -- Organisation access: roles that use AD_Role_OrgAccess with no summary organisation should match it exactly
  SELECT 'Organisation access rows for roles without summary organisations',
         (SELECT COUNT(DISTINCT (a.ad_role_id, a.ad_org_id)) FROM insightai.v_user_role_org a JOIN ad_role r ON r.ad_role_id = a.ad_role_id
           WHERE r.ad_client_id = :client AND r.isaccessallorgs = 'N' AND r.isuseuserorgaccess = 'N'
             AND NOT EXISTS (SELECT 1 FROM ad_role_orgaccess x JOIN ad_org o ON o.ad_org_id = x.ad_org_id
                             WHERE x.ad_role_id = r.ad_role_id AND x.isactive = 'Y' AND o.issummary = 'Y')),
         (SELECT COUNT(*) FROM ad_role_orgaccess x JOIN ad_role r ON r.ad_role_id = x.ad_role_id JOIN ad_org o ON o.ad_org_id = x.ad_org_id
           WHERE r.ad_client_id = :client AND r.isactive = 'Y' AND x.isactive = 'Y' AND o.isactive = 'Y' AND o.ad_org_id <> 0
             AND r.isaccessallorgs = 'N' AND r.isuseuserorgaccess = 'N'
             AND EXISTS (SELECT 1 FROM ad_user_roles ur JOIN ad_user u ON u.ad_user_id = ur.ad_user_id
                         WHERE ur.ad_role_id = r.ad_role_id AND ur.isactive = 'Y' AND u.isactive = 'Y')
             AND NOT EXISTS (SELECT 1 FROM ad_role_orgaccess y JOIN ad_org o2 ON o2.ad_org_id = y.ad_org_id
                             WHERE y.ad_role_id = r.ad_role_id AND y.isactive = 'Y' AND o2.issummary = 'Y'))
)
SELECT CASE WHEN ABS(COALESCE(insightai_value, 0) - COALESCE(adempiere_value, 0)) < 0.005 THEN 'PASS' ELSE 'FAIL' END AS result,
       name AS "check", round(insightai_value::numeric, 2) AS insightai, round(adempiere_value::numeric, 2) AS adempiere
FROM checks;
