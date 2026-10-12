# ADempiere InsightAI

Analytics and decision support for a local ADempiere 3.9.3 installation on PostgreSQL, opened from ADempiere's own menu. It shows business KPIs from ADempiere's transactional data, forecasts stock demand with a pretrained Hugging Face model, flags stockout risk, and answers a fixed set of business questions in plain English.

It is an extension of ADempiere, not a separate ERP: figures come only from ADempiere documents the logged-in role may see, and nothing in ADempiere is changed by using it.

The original brief is in `ADempiere_InsightAI_prompt_v2.md`.

## What it does

- **Dashboard.** Sales, purchases, receivables, inventory value and turnover, supplier delivery performance; monthly trends, rankings by product, category and customer, receivables aging, slow-moving stock. Filters for period, organisation, warehouse, category and business partner.
- **Demand forecast and stockout risk.** Weekly demand per product and warehouse forecast with Amazon Chronos-Bolt, compared with actual stock and open purchase orders. Evaluated against simple baselines. A clearly labelled synthetic demo mode exists because GardenWorld's real history is too thin to forecast.
- **Ask InsightAI.** 16 kinds of business question matched with a local embedding model to fixed, approved queries. No SQL is generated and nothing is sent to an outside service.
- **Inside ADempiere.** The dashboard opens as an ADempiere window, signed in automatically.
- **Access.** The session comes from the ADempiere login. Client and organisations are taken from ADempiere's own role tables on every request. The service reads through a database role that can see only InsightAI's views.

## Getting started

Install, daily use, troubleshooting and removal are in **[docs/setup.md](docs/setup.md)**. In short:

```
powershell -ExecutionPolicy Bypass -File scripts\db_install.ps1
powershell -ExecutionPolicy Bypass -File scripts\setup_service.ps1 -ML
.venv\Scripts\python.exe -m insightai.forecast
powershell -ExecutionPolicy Bypass -File scripts\adempiere_install.ps1
powershell -ExecutionPolicy Bypass -File scripts\run_service.ps1
```

Then start ADempiere with `RUN_Adempiere_InsightAI.bat` and open **Performance Analysis > InsightAI**. The dashboard opens in an ADempiere window; **InsightAI (browser)** opens it in your web browser instead.

To check an installation: `powershell -ExecutionPolicy Bypass -File scripts\run_tests.ps1`

## Documentation

| Document | Contents |
|---|---|
| [docs/setup.md](docs/setup.md) | Requirements, install, daily use, troubleshooting, removal |
| [docs/architecture.md](docs/architecture.md) | Parts, access model, design decisions, packages |
| [docs/kpi_definitions.md](docs/kpi_definitions.md) | Exactly how each figure is calculated, and known limits |
| [docs/stage7_testing.md](docs/stage7_testing.md) | Test results, acceptance criteria, what is still open |
| [docs/stage1_assessment.md](docs/stage1_assessment.md) | The ADempiere installation as found |
| [docs/stage2_data_discovery.md](docs/stage2_data_discovery.md) | Data volume, document rules, the `insightai` schema |
| [docs/stage4_forecasting.md](docs/stage4_forecasting.md) | Model comparison, evaluation, synthetic mode, limits |
| [docs/stage5_assistant.md](docs/stage5_assistant.md) | Supported questions, matching accuracy, limits |
| [docs/stage6_integration.md](docs/stage6_integration.md) | Menu entry, launcher, sign-in hand-off, 2Pack |
| [docs/embedded_window.md](docs/embedded_window.md) | The dashboard inside an ADempiere window: how it works, tests, limits |

## Status

All seven stages of the brief are built. Three things to know before relying on it:

1. **Nobody has yet clicked the entry in the real ADempiere client.** An automated test opens the embedded window through ADempiere's own window code and checks what it shows for three roles, but it does not click or type inside the page.
2. **Forecast accuracy is measured on synthetic demand only.** GardenWorld has shipments for 6 stocked products on 7 days in total, so nothing real can be forecast or evaluated yet.
3. **The development login is on by default** (`dev_login = true` in `config.toml`). Switch it off before anyone else uses the machine.
