# ADempiere InsightAI

Analytics and decision-support module for a local ADempiere 3.9.3 installation (PostgreSQL, GardenWorld demo client). The full brief is in `ADempiere_InsightAI_prompt_v2.md`.

## Status

| Stage | State |
|---|---|
| 1. Installation assessment | Done: `docs/stage1_assessment.md` |
| 2. Data discovery, `insightai` schema, read-only role, KPI definitions | Done: `docs/stage2_data_discovery.md`, `docs/kpi_definitions.md` |
| 3. FastAPI service and dashboard | Not started |
| 4. Forecasting | Not started |
| 5. Assistant | Not started |
| 6. ADempiere menu integration | Not started |
| 7. Testing and documentation | Not started |

## Database setup (Windows)

Requires PostgreSQL's `psql` and an ADempiere installation whose `AdempiereEnv.properties` points at the database.

```
powershell -ExecutionPolicy Bypass -File scripts\db_install.ps1
powershell -ExecutionPolicy Bypass -File scripts\db_verify.ps1
```

`db_install.ps1` creates the `insightai` schema, the `insightai_owner` and `insightai_ro` roles, and writes the service login to `.env` (ignored by git). It is safe to re-run. `db_verify.ps1` runs the smoke test as `insightai_ro`.

To remove everything:

```
powershell -ExecutionPolicy Bypass -File scripts\db_install.ps1 -Uninstall
```
