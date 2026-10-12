# KPI definitions

Every figure comes from the `insightai` views (`db/01_install.sql`). Rules that apply to all of them:

- **Scope:** one `AD_Client_ID`, and only the organisations in `v_user_role_org` for the logged-in user and role. Organisation is the document header's `AD_Org_ID`; for stock it is the warehouse's organisation.
- **Documents counted:** active, `DocStatus` `CO` or `CL`. Drafts, in-progress, invalid, voided and reversed documents are excluded. Proposals and quotations are not orders and are excluded.
- **Currency:** amounts are converted to the primary accounting schema currency (USD for GardenWorld) with ADempiere's `currencyConvert()`, at the document date and the document's conversion type. If ADempiere has no rate the converted amount is NULL, and the KPI must report how many documents were left out instead of silently dropping them.
- **Returns and credit memos:** kept as separate flagged rows with `sign = -1`. "Net" figures multiply by `sign`; "gross" figures exclude the flagged rows.
- **Tax:** line amounts (`LineNetAmt`) exclude tax; header `GrandTotal` includes it.

## KPI cards

| KPI | Definition | View | Date basis |
|---|---|---|---|
| Total sales | Sum of `line_net_amt_base * sign` on customer invoice lines (`issotrx = 'Y'`): invoiced revenue net of credit memos, before tax | `v_invoice_line` | `DateInvoiced` |
| Sales growth | (Total sales this period − total sales in the preceding period of equal length) ÷ the preceding period. "Not available" when the preceding period is zero | `v_invoice_line` | `DateInvoiced` |
| Order intake (secondary) | Sum of `line_net_amt_base * sign` on sales order lines | `v_order_line` | `DateOrdered` |
| Purchase expenditure | Sum of `line_net_amt_base * sign` on vendor invoice lines (`issotrx = 'N'`), net of vendor credit memos, before tax | `v_invoice_line` | `DateInvoiced` |
| Purchase commitments (secondary) | Sum of `line_net_amt_base * sign` on purchase order lines | `v_order_line` | `DateOrdered` |
| Outstanding receivables | Sum of `open_amt_base` where `issotrx = 'Y'` | `v_open_item` | As of today |
| Overdue receivables | Outstanding receivables where `days_due > 0` | `v_open_item` | As of today |
| Inventory value | Sum of `stock_value_base` = on-hand quantity × unit cost | `v_stock` | As of today |
| Inventory turnover | Cost of goods shipped in the period (customer shipment quantity × current unit cost) ÷ inventory value today. Approximation: see limits below | `v_inout_line`, `v_stock` | `MovementDate` |
| Stockout risk count | Products where forecast demand over the horizon exceeds `qty_available` + incoming purchase quantity due in the horizon. Defined fully in Stage 4 | `v_stock`, `v_order_line`, `v_demand_daily` | As of today |
| Supplier on-time rate | Share of vendor receipt lines with `days_late <= 0`, among lines linked to an order line | `v_inout_line` | `MovementDate` vs order line `DatePromised` |

Receivables are not filtered by the dashboard's date range: they are a balance as of today. Aging buckets (`Not due`, `1-30`, `31-60`, `61-90`, `Over 90`) come from `days_due`, which ADempiere computes from the payment term or pay schedule.

## Checked against ADempiere

Run on 2026-10-12 against GardenWorld, all organisations.

| Check | InsightAI view | ADempiere's own figure | Result |
|---|---|---|---|
| Customer invoices this year, gross | 2,510.25 | 2,510.25 (Performance goal "Invoice Revenue") | Match |
| Open customer invoices | 1,204.45 | 1,204.45 (Performance goal "Open Invoices") | Match |
| Quantity on hand | 739 | 739 (`M_Storage`) | Match |
| Quantity reserved / ordered | 12 / 337 | 12 / 337 (`M_Storage`) | Match |
| Open-item rows | 17 | 17 (`RV_OpenItem`) | Match |

## Known limits in this database

- **Inventory value mixes two cost bases.** The accounting schema values stock at Average Invoice cost, but only 5 of the 20 products in stock have one. The rest fall back to standard cost. Current split: 7,509.25 at Average Invoice cost and 4,598.90 at standard cost. `cost_source` records which was used, and the dashboard must show the split.
- **Inventory turnover is an approximation.** It uses today's unit cost and today's stock value, not historical cost or average stock, and there are only 13 customer shipment lines in total. Show it with that caveat or as "data unavailable".
- **Supplier performance has no signal.** 21 of 26 receipt lines link to an order line and every one arrived on the promised date. The KPI is computable but will read 100% until real late receipts exist.
- **Two versions of "incoming stock" disagree.** Open purchase order lines total 617 units; `M_Storage.QtyOrdered` totals 337. 381 of the open units are on 2019 purchase orders that were never received against. Stage 4 should use open order lines with a promised date inside the horizon and show `QtyOrdered` next to it.
- **No returns or credit memos exist yet**, so the sign handling is untested on real rows.
- **Demand history is far too thin to forecast:** 6 stocked products, 7 product-days, at most 2 shipment days per product. Synthetic mode is required for Stage 4.
