# Stage 1: installation assessment

Inspected on 2026-10-12. Read-only: nothing in the installation or database was changed.

## Environment

| Item | Finding |
|---|---|
| Version | Release 3.9.3, DB version 2019-12-01 (`AD_System`), 720 migrations applied |
| Java | JDK 1.8.0_501 with `javac`; no Ant or Maven on PATH |
| Install type | Binary only at `C:\Adempiere`: no source checkout, no git repo |
| Database | PostgreSQL 14.24; database `EV`, tables in schema `adempiere` (972 tables, 183 views) |
| DB roles | `adempiere` (superuser), `postgres`, `erp_ai_reader` |
| Client | GardenWorld, `AD_Client_ID = 11`, 9 organisations including the non-stock "MEKAR AIR HANDLING UNITS LLC" |
| Swing client | In use; connects straight to the database (no app server); started with `RUN_Adempiere_AI.bat` |
| ZK web client | Deployed in Tomcat (`webui`, port 8888) and used occasionally; not always running |
| Python | 3.6.5 (`C:\Python36`, must not be touched), 3.11.0, 3.12.10, 3.14.8 |
| Hardware | Intel Core 5 120U, 12 threads, 15.7 GB RAM, integrated graphics only |

## Existing "Ask AI" customization

Not stock ADempiere. Built locally (jar manifest: "ADempiere AI Assistant").

- `AD_Menu` 1000000 "Ask AI" → `AD_Process` 1000001, class `com.teksalah.ai.AskAIProcess` (`SvrProcess`), one parameter `Question`. Entity Type `U`. Sits at the menu root.
- An external LLM (default endpoint Groq) picks tables, writes SQL and summarises the result. The API key is in `AD_SysConfig` (`AI_API_KEY`).
- Safety checks: single statement, SELECT/WITH only, keyword blocklist, read-only transaction, 15 s timeout. It checks only that the text `ad_client_id` appears; there is no organisation or role filtering. It runs on ADempiere's own connection, i.e. as the `adempiere` superuser.
- Granted to every role.
- Three copies of the classes: `lib\teksalah_ai.jar` (newest, first on the launcher classpath), `lib\customization.jar`, and an older build merged into `Adempiere.jar`.
- `C:\erp_ai` is a Python command-line prototype of the same idea; it created `erp_ai_reader`, which has SELECT on every relation in `adempiere`.

**Decision:** InsightAI's assistant stays separate and Ask AI is left untouched. Ask AI runs model-generated SQL and sends ERP rows to an outside API; InsightAI allows neither.

## Performance tab

- Swing: `org.adempiere.apps.graph.PAPanel` / `PerformanceIndicator`, JFreeChart in `AdempiereCLib.jar`. ZK: `DPPerformance`.
- GardenWorld has 4 goals, none tied to a user or role: Invoice Revenue, Open Invoices, Service Requests (Quarter), Total Open Service Requests.
- 4 measures in GardenWorld and 6 system measure calculations (net and gross revenue, sales margin, number of customers, paid quantities, open invoice amount).

## Menu and extension mechanisms

- One menu tree (`AD_Tree_ID = 10`). Performance Analysis is node 278 at the root.
- `SvrProcess`, `FormPanel`, `ModelValidator`, `PackIn` and `PackOut` are present. No 2Pack has been imported before.
- Only stock entity types exist. New dictionary records get IDs from 1,000,000 up.
- `RUN_setup` merges `customization.jar` into `Adempiere.jar` and re-signs it.

## Security model

- GardenWorld Admin: all organisations. GardenWorld User: 5 granted, one of them the summary organisation "Stores". `SalesRep(Restricted)` with user `test_salerep`: MEKAR only.
- `AD_Record_Access`, `AD_User_OrgAccess`, `AD_Column_Access` and `AD_Private_Access` are empty.
- The only existing API is the SOAP `ADInterface`; there is no REST layer for analytics.

## Integration path

1. New `insightai` schema and read-only role in `EV`; no changes to `adempiere` tables.
2. FastAPI service in a new venv on the existing Python 3.12.
3. "InsightAI" menu entry under node 278 → small `SvrProcess` launcher, new entity type, selected roles only, exported as a 2Pack.
4. Separate `insightai.jar` on the Swing launcher classpath rather than merged into `customization.jar`. The ZK client will not see it until a deliberate setup run.
5. Simple KPIs added as ordinary `PA_Measure` / `PA_Goal` records.
