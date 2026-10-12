# Developer Prompt: Implement ADempiere InsightAI (revised for ADempiere 3.9.3)

## 1. Project Overview

Act as a senior ERP software engineer, AI/ML engineer, and full-stack developer.

I am working on a local demo installation of **ADempiere 3.9.3** and want to add an AI-powered business analytics and decision-support module using Hugging Face pretrained models.

The goal is to turn ADempiere's existing transactional data into business insights, predictive analytics, and actionable recommendations.

This must be an extension of the existing ADempiere application, opened from ADempiere's own menu. It is not a separate ERP and not merely a standalone chatbot.

**Project name:** ADempiere InsightAI

**Project objective:** Build an integrated analytics module that helps ERP users understand business performance, identify operational risks, forecast inventory demand, and ask business questions in natural language.

### Known environment (verify each item, do not assume)

- ADempiere 3.9.3, used through the **Java Swing desktop client**. Check whether the ZK web client (webui) is also deployed and running.
- Windows machine.
- PostgreSQL database, managed with pgAdmin 4. ADempiere tables live in the `adempiere` schema.
- **GardenWorld** demo client (normally `AD_Client_ID = 11`; confirm in `AD_Client`).
- Python 3.6.5 is installed (required by another project and must not be disturbed) and Python 3.14 is also installed.
- This is most likely a **binary installation, not a source checkout**. If no source repository is available, all integration must go through the Application Dictionary and a small customization JAR. Do not plan on editing or rebuilding ADempiere core source.

## 2. First Task: Inspect the Existing ADempiere Installation

Before writing or modifying anything, inspect the installation and database.

Determine:

- The exact ADempiere version (Help > About, `AD_System`) and Java version in use.
- Whether you have a source repository or only the installed binaries (`Adempiere/lib`, `Adempiere/packages`, `AdempiereEnv.properties`).
- Whether only the Swing client is used, or the ZK web client as well.
- How the **Performance tab** on the Swing main window works. In stock ADempiere it is driven by the Performance Analysis tables (`PA_Goal`, `PA_Measure`, `PA_MeasureCalc`, `PA_ColorSchema`, `PA_Achievement`, `PA_Ratio`) and the goals assigned to the current user/role. Check which goals and measures GardenWorld already has.
- Whether an **"Ask AI"** menu item exists. Stock ADempiere 3.9.3 does not include one, so if it is present it is a customization or plugin: find its `AD_Menu` record, what it points to (`AD_Process`, `AD_Form`, window), and its class name. If it does not exist, say so and do not invent its behavior.
- The menu tree (`AD_Menu`, `AD_TreeNodeMM`) and where the **Performance Analysis** node sits.
- How custom extensions are registered in this version: `AD_Menu` entries pointing to an `AD_Process` (Java class extending `SvrProcess`) or an `AD_Form` (Swing `FormPanel` / ZK form controller), `ModelValidator`, custom Entity Types, and 2Pack (Pack Out / Pack In) for exporting dictionary changes.
- The security model: `AD_Role`, `AD_User_Roles`, `AD_Role_OrgAccess`, `AD_Window_Access`, `AD_Process_Access`, `AD_Form_Access`, `AD_Record_Access`, and how `MRole.addAccessSQL()` applies client/org filtering in Java.
- Whether any existing API or service layer exists. Stock 3.9.3 has no general REST API for ERP data, so assume an analytics service must be added unless you find one.

Do not assume Odoo, iDempiere (OSGi plugins, `M_StorageOnHand`, REST plugin), or any other ERP's architecture or schema.

Do not rewrite existing files or replace the current Performance tab.

First, produce a concise assessment of the installation, the safest integration point, and the proposed changes. Then implement using only the mechanisms that actually exist in this installation.

## 3. Data Discovery: Expected ADempiere Tables (verify before use)

Use these as starting points and confirm every table, column and view in pgAdmin before writing queries.

| Area | Likely tables/views | Notes |
|---|---|---|
| Sales & purchase orders | `C_Order`, `C_OrderLine` | `IsSOTrx = 'Y'` sales, `'N'` purchase |
| Invoices | `C_Invoice`, `C_InvoiceLine`, view `RV_OpenItem` | `RV_OpenItem` gives open amount and days due; functions like `invoiceOpen()` may help |
| Shipments / receipts | `M_InOut`, `M_InOutLine` | `MovementDate` vs `C_OrderLine.DatePromised` for supplier delivery performance |
| Products | `M_Product`, `M_Product_Category` | |
| Stock | `M_Storage` (verify name; iDempiere uses `M_StorageOnHand`), `M_Transaction`, `M_Warehouse`, `M_Locator` | `QtyOnHand`, `QtyReserved`, `QtyOrdered` |
| Costing / value | `M_Cost`, `M_CostElement`, `M_Product_Price` | Inventory value depends on configured costing; may be incomplete in GardenWorld |
| Partners | `C_BPartner` | `IsCustomer`, `IsVendor` |
| Payments / accounting | `C_Payment`, `C_AllocationHdr`, `C_AllocationLine`, `Fact_Acct` | |
| Currency | `C_Currency`, `C_Conversion_Rate`, `currencyConvert()` / `currencyBase()` | Convert to the accounting schema currency before aggregating |

Rules for every analytical query:

- Filter by `AD_Client_ID` and allowed `AD_Org_ID` values.
- Count only active, posted business documents: `IsActive = 'Y'` and `DocStatus IN ('CO','CL')`. Exclude drafts, voided (`VO`) and reversed (`RE`) documents.
- Treat returns and credit memos explicitly (check `C_DocType.DocBaseType`, e.g. `ARC`, `APC`, and RMA document types) rather than mixing them into gross sales.
- Use the correct date field per metric (`DateOrdered`, `DateInvoiced`, `DateAcct`, `MovementDate`) and state which one was used.
- Reuse existing ADempiere reports/views where they already compute a metric (for example the Aging report and `RV_OpenItem` for receivables).

**Data volume warning:** GardenWorld has very little transaction history, mostly concentrated in a short period. Check row counts and date ranges first. It will almost certainly be insufficient for meaningful forecasting (see Feature B).

## 4. Main Features to Implement

### Feature A: AI Business Analytics Dashboard

Add an analytics workspace opened from a new **"InsightAI"** entry under the **Performance Analysis** menu node.

Where practical, also reuse the native Performance tab: KPIs that can be expressed as `PA_Measure` / `PA_Goal` records (for example, monthly sales against a target) should be created as normal ADempiere goals so they appear in the existing Performance tab without any code changes.

The workspace should include:

**Business KPI cards**
- Total sales and sales growth.
- Purchase expenditure.
- Inventory value and inventory turnover, only if costing data supports it.
- Outstanding and overdue receivables (based on `RV_OpenItem` or equivalent).
- Number of products with potential stockout risk.
- Supplier delivery performance, only if receipts can be matched to promised dates.

**Analytical visualizations**
- Monthly sales trends.
- Sales by product and product category.
- Sales by customer.
- Purchase trends.
- Inventory distribution and slow-moving stock.
- Supplier performance.
- Invoice aging and outstanding receivables.

Filters: date range, organization, warehouse, product category, business partner, limited to what the user's role is allowed to see.

All figures must come from actual, authorized ERP data. Never hardcode illustrative numbers. If a metric cannot be calculated (for example, no costing data), show "data unavailable" with the reason.

### Feature B: Predictive Inventory Intelligence Using Hugging Face

Start by evaluating Amazon's Chronos family:

- `amazon/chronos-t5-small` — https://huggingface.co/amazon/chronos-t5-small
- `amazon/chronos-bolt-small` — faster and lighter on CPU; compare if the T5 model is too slow.
- Check whether a newer Chronos release is available and better suited.

Before integrating, verify the current model availability, license, the `chronos-forecasting` package and PyTorch requirements, CPU-only inference speed on this Windows machine, and Python version compatibility.

**Python environment:** do not use or modify the Python 3.6.5 installation (too old for current PyTorch/Transformers, and needed by another project). Create a dedicated virtual environment. Use Python 3.14 only if PyTorch and all other dependencies have Windows wheels for it; otherwise recommend installing Python 3.11 or 3.12 for this venv and explain why.

Workflow:

1. Retrieve historical demand from completed sales documents (and/or `M_Transaction` shipment movements), with explicit handling of returns and cancellations.
2. Aggregate into consistent daily or weekly series per product (and warehouse if relevant).
3. Fill missing periods with zero demand where appropriate, and flag outliers.
4. Forecast for a configurable horizon.
5. Compare forecasts with current available stock (`QtyOnHand − QtyReserved`) and confirmed incoming purchase quantities (open purchase order lines / `QtyOrdered`).
6. Flag products at risk of stockout or excess inventory.
7. Show results in the dashboard.

Display: historical demand, forecast with uncertainty range, horizon, available stock, known incoming replenishment, estimated stockout risk, and assumptions/limitations.

Evaluate against a baseline (seasonal-naive if enough seasonal history exists, otherwise naive or moving average) using MAE and MASE on a chronological holdout. Do not claim accuracy before evaluating.

**Synthetic data:** because GardenWorld history is thin, provide a clearly labelled synthetic-data mode for development. Generate synthetic series in a separate `insightai` schema (or files), never inserted into ADempiere business tables, and tag every synthetic result as synthetic in the API and UI. Never mix synthetic and real records silently.

### Feature C: Natural-Language ERP Analytics Assistant

Let authorized users ask business questions in plain English, for example:

- "What were our top five products by sales last month?"
- "Which products have declining sales and high current inventory?"
- "Which suppliers have the longest delivery delays?"
- "How much money is tied up in overdue invoices?"
- "Which products are likely to run out of stock in the next 30 days?"

If an "Ask AI" item already exists (see Section 2), decide whether to extend it or keep InsightAI's assistant separate, and explain the choice.

Use `sentence-transformers/all-MiniLM-L6-v2` (https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) for **intent matching**: embed each approved question template and match the user's question to the closest one. MiniLM is an embedding model; it cannot generate SQL or answers by itself.

Controlled query architecture:

1. Match the question to an approved intent (with a confidence threshold; below it, say the question isn't supported and list supported ones).
2. Extract and validate parameters (date range, product, partner, top-N) against the database.
3. Check permissions.
4. Run a parameterized, read-only query template or analytical function.
5. Return results with figures, filters and reporting period.
6. Produce a short explanation. Start with deterministic, template-based wording. A local instruction-following model is optional and only if CPU performance on this machine is acceptable. Do not use a paid API unless I explicitly approve it.
7. Show a chart or table where useful.

**SQL and data security:**
- No arbitrary model-generated SQL. Only approved, parameterized templates.
- Connect with a **dedicated read-only PostgreSQL role** that has `SELECT` only on InsightAI views in the `insightai` schema. Never use the `adempiere` superuser account from the analytics service.
- Reject writes, DDL and multi-statement input; set `statement_timeout` and row limits.
- Enforce ADempiere client, organization and role restrictions (see Section 5).
- Keep database credentials out of the frontend, the model prompt and logs.

If the assistant cannot answer from available data, it must say so.

### Feature D: Business Risk Alerts

Add an insights panel listing candidate issues, for example:
- Rising demand with insufficient stock.
- Slow-moving products holding significant value.
- Unusual purchase price changes (compare `C_OrderLine.PriceActual` / invoice prices to the product's history or price list).
- Overdue invoices needing follow-up.
- Suppliers with worsening delivery performance.

Use transparent SQL rules and simple statistics first; use ML only where it clearly adds value. Use Hugging Face models only where text interpretation is useful.

Each alert shows: affected entity, supporting data, triggering rule or threshold, severity, recommended next step, reporting period and assumptions.

Do not label anything as fraud. Alerts are investigation candidates.

Recommendations are advisory only. Do not create purchase orders, post invoices, or change inventory.

## 5. Integration With ADempiere (Swing client first)

Swing cannot render a modern web dashboard well, so the expected approach is:

1. **Analytics service:** a Python FastAPI service running locally, reading ADempiere data through read-only views.
2. **Web dashboard:** served by that service (or a small frontend), styled to sit comfortably next to ADempiere.
3. **Menu entry:** a new `AD_Menu` record under Performance Analysis, using a custom **Entity Type** (not `D`) so it survives migrations. It points to a small `AD_Process` (Java class extending `SvrProcess`) packaged in a customization JAR. The process reads the current context (`AD_Client_ID`, `AD_Org_ID`, `AD_Role_ID`, `AD_User_ID`), requests a short-lived signed token from the service, and opens the dashboard in the default browser (`java.awt.Desktop.browse()`).
4. **Access control:** grant the process only to selected roles via `AD_Process_Access`. The service must derive allowed clients/orgs from `AD_Role_OrgAccess` for the role in the token and apply them to every query. The browser must never be able to choose its own client, org or role.
5. **ZK web client (if deployed):** optionally add the same menu entry opening the dashboard in a new tab or embedded frame.
6. Export all dictionary changes (menu, process, access, entity type) as a **2Pack** so they can be installed or removed cleanly.

Alternatives (only if inspection shows they fit better): a native Swing `FormPanel` using JFreeChart, which ADempiere already ships for the Performance tab, or new `PA_Measure` records for simple KPIs.

Choose the least invasive option, and explain the choice. Do not modify core ADempiere classes or core dictionary records.

## 6. Technical Architecture

**ERP layer:** existing ADempiere 3.9.3, PostgreSQL, existing roles and access rules.

**Database:**
- New `insightai` schema in the same database for read-only analytical views, cached results, configuration and any synthetic data.
- No changes to ADempiere's own tables.
- Read-only database role for the service.

**Analytics service:** Python (dedicated venv), FastAPI, pandas, `psycopg` or SQLAlchemy.

**AI/ML:** `chronos-forecasting` + PyTorch (CPU), `sentence-transformers`, plus simple statistical baselines and rule-based anomaly checks.

**Visualization:** Plotly (or similar) in the web dashboard.

**ADempiere glue:** one small Java customization JAR (launcher process) and a 2Pack.

Only add components that are actually needed, and explain each new dependency.

## 7. Non-Functional Requirements

- Existing ADempiere functionality must keep working.
- Real ERP data only for reporting; synthetic data clearly separated.
- Model inference runs in the Python service, never in the ADempiere client or server thread.
- Clear loading, error, empty-data and model-unavailable states.
- Fallback when Hugging Face models cannot be downloaded or loaded (baseline forecasts, keyword-based intent matching).
- Cache downloaded models locally so the demo works offline.
- No credentials or sensitive ERP data in logs.
- Configuration file for DB connection, ports, model names and horizons.
- Runs on Windows; document every setup step.
- No paid APIs unless approved.

## 8. Development Stages

**Stage 1 — Installation assessment:** version, Java, client type, source vs binary, Performance tab setup, "Ask AI" status, menu tree, extension mechanisms.

**Stage 2 — Data discovery:** confirm tables and columns, DocStatus/DocType handling, currency conversion, org restrictions; measure GardenWorld data volume and date range; create `insightai` schema, views and read-only role; write KPI definitions.

**Stage 3 — Functional MVP:** FastAPI service plus dashboard with KPI cards, sales and inventory charts, date filters, real data, error/empty states.

**Stage 4 — Forecasting:** venv setup, Chronos integration, baseline comparison (MAE/MASE), stockout risk, synthetic-data mode if needed, documented limitations and hardware needs.

**Stage 5 — Assistant:** approved intents and templates, MiniLM matching, parameter validation, verified answers with tables/charts.

**Stage 6 — ADempiere integration:** customization JAR, `AD_Menu` + `AD_Process` + access records under a custom Entity Type, token handoff, 2Pack export; test from the Swing client with GardenWorld Admin and a restricted role.

**Stage 7 — Testing and documentation:** unit tests for KPIs and forecasting; integration tests for views and API; tests for unauthorized access, wrong org, invalid questions, missing data and model failure; compare assistant answers with hand-written SQL; setup, troubleshooting and uninstall instructions.

## 9. Acceptance Criteria

1. InsightAI opens from the ADempiere Swing client menu (and ZK if deployed), only for authorized roles.
2. At least one dashboard shows verified GardenWorld data, cross-checked against ADempiere's own windows/reports.
3. Metrics can be filtered by reporting period.
4. Forecasting produces results and documents its evaluation against a baseline, with real vs synthetic data clearly labelled.
5. Stockout risk uses actual stock and open purchase quantities.
6. The assistant answers a defined set of questions from verified query results.
7. Unsafe or unauthorized queries are rejected; another org's data is never returned.
8. Existing ADempiere functionality still works, and the 2Pack can be removed cleanly.
9. Missing models and insufficient data are handled gracefully.
10. Setup, architecture, testing and usage are documented for Windows.

## 10. How You Should Work

- Inspect before implementing.
- Explain important decisions.
- Write working code, not mockups.
- Do not invent table names, columns, APIs, menu items or model capabilities. Confirm in the database or installation first.
- Do not touch the Python 3.6.5 installation or ADempiere core files.
- Keep changes focused, reversible and packaged (custom entity type, 2Pack, separate schema).
- If something is uncertain, check and state the uncertainty.
- If a feature doesn't fit ADempiere 3.9.3, propose a compatible alternative.
- After each stage, report what changed, what was tested and what remains.

Begin by assessing the installation and identifying the safest integration path. Then build the smallest complete working version of ADempiere InsightAI and expand it step by step.
