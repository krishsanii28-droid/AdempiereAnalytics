# Stage 7: testing and acceptance

Run on 2026-10-12 against the live `EV` database. One command runs everything:

```
powershell -ExecutionPolicy Bypass -File scripts\run_tests.ps1
```

| Suite | What it covers | Result |
|---|---|---|
| Python tests (`pytest`) | 125 tests, listed below | 125 passed |
| Read-only role smoke test (`db\verify_ro.sql`) | The service role can read the views and nothing else | 16 views readable, 8 forbidden statements refused |
| Cross-check against ADempiere (`db\crosscheck.sql`) | View figures against ADempiere's own Performance measures, `RV_OpenItem`, `M_Storage`, `M_Transaction` and raw document tables | 14 of 14 match |
| ADempiere launcher (`scripts\test_launcher.ps1`) | The real launcher process in a headless ADempiere environment, for four logins and with the service unreachable | All passed |
| Embedded window (`scripts\test_form.ps1`) | Added after this stage: the InsightAI window opened through ADempiere's form frame for three logins, with the menu tree each role is shown | All passed |

## Python tests

| File | Tests | Covers |
|---|---|---|
| `test_units.py` | 14 | Query scoping (client and organisation always present, filter values never in SQL text), period arithmetic, session tokens, launch signatures |
| `test_views.py` | 21 | Only completed and closed documents, document types and signs, line and header totals agree, currency conversion, stock arithmetic, demand is stocked items only, open-item buckets, organisation access view, and that the service role cannot read ADempiere tables or write anything |
| `test_api.py` | 18 | No session, forged and expired tokens, a role the user does not hold, another organisation's data, bad input, an empty period, a database failure, KPI cards equal their charts, organisation filter partitions the total |
| `test_forecast.py` | 20 | Weekly series, outliers, baselines, MAE and MASE, risk rules, synthetic repeatability, model unavailable, real mode claims no accuracy, synthetic results labelled and kept out of the real KPI |
| `test_assistant.py` | 46 | Periods, top-N, names, SQL-shaped input, unsupported questions, keyword fallback, read-only requests, organisation restriction, four answers against hand-written SQL |
| `test_launch.py` | 6 | Granted and ungranted roles, a role not held, wrong key, stale and replayed requests, single-use links |

The tests run against real data through the read-only role, so they assert rules that must hold for any data rather than fixed GardenWorld amounts.

## What the brief asked to be tested

| Asked for | Where |
|---|---|
| Unit tests for KPIs and forecasting | `test_units.py`, `test_forecast.py` |
| Integration tests for views and API | `test_views.py`, `test_api.py`, `db\crosscheck.sql` |
| Unauthorized access | `test_api.py`, `test_launch.py`, `test_views.py`, `test_launcher.ps1` |
| Wrong organisation | `test_api.py` (403 on another organisation or warehouse), `test_forecast.py` (404 on another organisation's series), `test_assistant.py` |
| Invalid questions | `test_assistant.py` with 27 unsupported and 6 SQL-shaped questions |
| Missing data | `test_api.py` (empty period), `test_forecast.py` (no history), `test_assistant.py` (name not found) |
| Model failure | `test_forecast.py` (model cannot load), `test_assistant.py` (keyword fallback), `test_api.py` (database failure) |
| Assistant answers against hand-written SQL | `test_assistant.py`: top products, overdue total, stock of a product, sales to a customer |

## Defects found by this stage

| Defect | Found by | Fix |
|---|---|---|
| Service and expense items on shipment documents (Planting Service, Travel cost, How To Plant) were counted as stock demand: 116 units against 73 in the stock ledger | New cross-check of shipment lines against `M_Transaction` | `v_demand_daily` now holds stocked items only; the real forecast went from 37 series to 33 |
| Any PostgreSQL operational error was reported as "The ADempiere database is not reachable", including errors that had nothing to do with the connection | New test that the service role cannot update a view | `db.py` now treats only connection, shutdown and resource errors that way |

Earlier stages' own testing found and fixed: a missing grant that made `invoiceOpen()` return nothing without an error (Stage 2), the service role being able to create tables after lifting its read-only default (Stage 2), 2018-2019 products with one shipment being "forecast" at near-zero error (Stage 4), and a product name also being read as a similarly named customer (Stage 5).

## Uninstall tests

| Path | Check | Result |
|---|---|---|
| `adempiere_install.ps1 -Uninstall` | Entity types, processes, menus, translations, tree nodes, access rows, package definitions, files in the ADempiere folder | None left; menu and process counts back to 960 and 582 |
| `db_install.ps1 -Uninstall` | Schema, both roles, their table and column grants, the two tightened PostgreSQL defaults | None left; defaults restored; ADempiere's 1,155 tables and views unchanged |

Both were followed by a reinstall, after which the full suite passed again.

## Acceptance criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Opens from the ADempiere Swing menu, only for authorized roles | **Verified by test, not by a person** | The embedded window is opened through ADempiere's own form frame, and the menu tree is built the way the client builds it, for a granted admin, a granted restricted role and an ungranted role (`scripts\test_form.ps1`, see `docs/embedded_window.md`). No person has clicked the entry in the real client. ZK is not supported |
| 2 | A dashboard shows verified GardenWorld data, cross-checked against ADempiere | Met | 14 cross-checks, including two against ADempiere's own Performance goals (2,510.25 and 1,204.45) |
| 3 | Metrics can be filtered by reporting period | Met | Period presets and custom dates; balances are labelled as of today |
| 4 | Forecasting produces results and documents its evaluation against a baseline, real and synthetic clearly labelled | Met on synthetic data only | MASE 0.829 against 0.964 for the strongest baseline, on synthetic demand. On real data nothing can be forecast and no accuracy is claimed |
| 5 | Stockout risk uses actual stock and open purchase quantities | Met | `M_Storage` on hand minus reserved, plus open purchase order lines promised within the horizon |
| 6 | The assistant answers a defined set of questions from verified query results | Met | 16 question types; 24 of 28 held-back questions answered correctly, 1 wrongly, 3 declined |
| 7 | Unsafe or unauthorized queries are rejected; another organisation's data is never returned | Met | SQL-shaped input, unsupported questions, other organisations and warehouses all refused in tests |
| 8 | Existing ADempiere functionality still works, and the 2Pack can be removed cleanly | **Partly verified** | No ADempiere file or existing dictionary record was changed, and removal by script is tested. Not verified: a walk through ADempiere's own windows after install, and importing or removing through PackIn |
| 9 | Missing models and insufficient data are handled gracefully | Met | Baseline and keyword fallbacks with the reason shown; "Data unavailable" and "Not forecast" states with reasons |
| 10 | Setup, architecture, testing and usage documented for Windows | Met | `docs\setup.md`, `docs\architecture.md`, this file, and the stage write-ups |

## Still open

1. **Click-through in the Swing client.** Start ADempiere with `RUN_Adempiere_InsightAI.bat` and open Performance Analysis > InsightAI. The automated test now covers the menu entries per role and the window loading the dashboard, so this is a confirmation by eye, including typing and clicking inside the page.
2. **A look at ADempiere after install.** Open a few standard windows and the Performance tab to confirm nothing looks different. Nothing was changed that should affect them, but it has not been looked at.
3. **Switch off the development login** (`dev_login = false` in `config.toml`) once item 1 works.
4. **PackIn of the 2Pack** on a second ADempiere instance, if one becomes available.
5. **Real forecasting accuracy** can only be measured once there are months of real shipment history.
6. **Returns and credit memos** have sign handling but no real documents to test it on.
7. **The existing Ask AI** still runs as the database superuser, without organisation filtering, for every role. It is outside this project's scope but worth knowing.
