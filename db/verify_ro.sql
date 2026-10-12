-- Smoke test, run as insightai_ro (see scripts\db_verify.ps1).
-- Part 1 must succeed; every statement in part 2 must be refused.

\echo == session
SELECT current_user, current_setting('transaction_read_only') AS read_only, current_setting('statement_timeout') AS timeout;

\echo == part 1: row counts per view (GardenWorld, client 11)
SELECT 'v_user_role_org' AS view, count(*) FROM v_user_role_org WHERE ad_client_id = 11
UNION ALL SELECT 'v_user_role', count(*) FROM v_user_role WHERE ad_client_id = 11
UNION ALL SELECT 'v_org', count(*) FROM v_org WHERE ad_client_id = 11
UNION ALL SELECT 'v_warehouse', count(*) FROM v_warehouse WHERE ad_client_id = 11
UNION ALL SELECT 'v_product_category', count(*) FROM v_product_category WHERE ad_client_id = 11
UNION ALL SELECT 'v_product', count(*) FROM v_product WHERE ad_client_id = 11
UNION ALL SELECT 'v_bpartner', count(*) FROM v_bpartner WHERE ad_client_id = 11
UNION ALL SELECT 'v_order_line', count(*) FROM v_order_line WHERE ad_client_id = 11
UNION ALL SELECT 'v_invoice', count(*) FROM v_invoice WHERE ad_client_id = 11
UNION ALL SELECT 'v_invoice_line', count(*) FROM v_invoice_line WHERE ad_client_id = 11
UNION ALL SELECT 'v_inout_line', count(*) FROM v_inout_line WHERE ad_client_id = 11
UNION ALL SELECT 'v_demand_daily', count(*) FROM v_demand_daily WHERE ad_client_id = 11
UNION ALL SELECT 'v_open_item', count(*) FROM v_open_item WHERE ad_client_id = 11
UNION ALL SELECT 'v_product_cost', count(*) FROM v_product_cost WHERE ad_client_id = 11
UNION ALL SELECT 'v_stock', count(*) FROM v_stock WHERE ad_client_id = 11
UNION ALL SELECT 'v_stock_movement', count(*) FROM v_stock_movement WHERE ad_client_id = 11;

\echo == part 2: each of these must fail
\set ON_ERROR_STOP off
SELECT count(*) FROM adempiere.c_invoice;
SELECT password FROM adempiere.ad_user LIMIT 1;
SELECT value FROM adempiere.ad_sysconfig LIMIT 1;
SELECT adempiere.invoiceopen(100, 0);
CREATE TABLE insightai.should_not_exist (id int);
-- the role can lift its own read-only default, so these must be stopped by privileges instead
BEGIN READ WRITE;
CREATE TABLE public.should_not_exist (id int);
ROLLBACK;
BEGIN READ WRITE;
CREATE TEMP TABLE should_not_exist (id int);
ROLLBACK;
BEGIN READ WRITE;
CREATE TABLE insightai.should_not_exist (id int);
ROLLBACK;
