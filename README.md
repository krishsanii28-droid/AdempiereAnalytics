# ADempiere InsightAI

Analytics and decision-support module for a local ADempiere 3.9.3 installation (PostgreSQL, GardenWorld demo client). The full brief is in `ADempiere_InsightAI_prompt_v2.md`.

## Status

| Stage | State |
|---|---|
| 1. Installation assessment | Done: `docs/stage1_assessment.md` |
| 2. Data discovery, `insightai` schema, read-only role, KPI definitions | Done: `docs/stage2_data_discovery.md`, `docs/kpi_definitions.md` |
| 3. FastAPI service and dashboard | Done: KPI cards, sales, purchase, inventory and receivables views, filters |
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

## Analytics service (Windows)

Requires Python 3.12 (`py -3.12`). Everything installs into `.venv` in this folder; no other Python on the machine is touched.

```
powershell -ExecutionPolicy Bypass -File scripts\setup_service.ps1
powershell -ExecutionPolicy Bypass -File scripts\run_service.ps1
```

Then open http://127.0.0.1:8765. Until the ADempiere menu entry exists (Stage 6), the page asks which ADempiere user and role to act as. That development login is controlled by `dev_login` in `config.toml` and only answers on this machine.

Settings are in `config.toml` (port, default period, ranking size, slow-moving threshold). Secrets are in `.env`.

### How access is enforced

- The session token holds only the user and role, and is signed by the service. Client and organisations are read from ADempiere's access tables on every request; the browser cannot supply them.
- Every query is fixed SQL over the `insightai` views with bound parameters, restricted to the session's client and organisations.
- A filter that a figure cannot honour (for example warehouse on invoice-based sales) is reported next to that figure rather than silently ignored.

### Packages

| Package | Why |
|---|---|
| `fastapi`, `uvicorn` | The HTTP API and the server that runs it |
| `psycopg` | PostgreSQL driver and connection pool |
| `plotly` | Only for the `plotly.min.js` it bundles, so charts work without internet access |

### Tests

```
powershell -ExecutionPolicy Bypass -File scripts\setup_service.ps1 -Dev
.venv\Scripts\python.exe -m pytest
```

The tests run against the live database through the read-only role. They check access rules and consistency between figures, not specific amounts.
