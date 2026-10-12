# Architecture

## Parts

```
 ADempiere desktop client (Swing, Java 8)             Browser
 ┌───────────────────────────────────┐               ┌─────────────────────────┐
 │ Menu: Performance Analysis        │               │ Dashboard page          │
 │   ├─ InsightAI                    │  shows page   │  Ask InsightAI          │
 │   │    └─ InsightAIForm: window ──┼──────────────▶│  KPI cards and charts   │
 │   │       with embedded web view  │               │  Forecast panel         │
 │   └─ InsightAI (browser)          │  opens link   │                         │
 │        └─ InsightAILauncher ──────┼──────────────▶│ (same page, in the      │
 │           (both in insightai.jar) │               │  default browser)       │
 └───────────────┬───────────────────┘               └───────────┬─────────────┘
                 │ signed request for a one-time link            │ session cookie
                 ▼                                               ▼
 ┌───────────────────────────────────────────────────────────────────────────────┐
 │ InsightAI service (Python 3.12, FastAPI, 127.0.0.1:8765)                      │
 │   launch.py     hand-off from ADempiere        auth.py    signed sessions     │
 │   queries.py    KPI and chart SQL              assistant/ intents, matching   │
 │   forecast/     weekly demand, Chronos, risk   static/    the page            │
 └───────────────┬──────────────────────────────────────────────┬────────────────┘
                 │ SELECT only, as role insightai_ro            │ files
                 ▼                                              ▼
 ┌───────────────────────────────────────────────┐   ┌─────────────────────────┐
 │ PostgreSQL database EV                        │   │ models/  Chronos, MiniLM│
 │   schema insightai   18 views, 3 functions    │   │ data/    forecast JSON, │
 │        │ owned by insightai_owner             │   │          synthetic CSV  │
 │        ▼ reads a fixed list of tables         │   └─────────────────────────┘
 │   schema adempiere   ADempiere's own tables   │
 └───────────────────────────────────────────────┘
```

## Who can do what

| Actor | Database rights | Notes |
|---|---|---|
| ADempiere | `adempiere` role, as before | Unchanged |
| `insightai_owner` | SELECT on a fixed list of ADempiere tables and views; 4 non-secret columns of `AD_User` | Cannot log in. Owns the `insightai` views, so this list is all the ADempiere data that can reach the service |
| `insightai_ro` | SELECT on the `insightai` views, EXECUTE on 3 helper functions | The only login the service uses. No rights on schema `adempiere`; cannot create anything, even after switching off its read-only default |
| The browser | None | Holds a signed cookie naming a user and role. Cannot name a client or organisation |

## How a request is restricted

1. The session cookie is verified (HMAC-SHA256, 8-hour expiry).
2. The user's role and the organisations that role may see are read from `insightai.v_user_role_org`, which reproduces ADempiere's `MRole` rules: all organisations, `AD_Role_OrgAccess`, or `AD_User_OrgAccess`, with summary organisations expanded through the organisation tree. This happens on every request, so a change in ADempiere takes effect at once.
3. An organisation or warehouse filter from the page is accepted only if it is inside that set.
4. Every query is fixed SQL with bound parameters and carries `ad_client_id = ... AND ad_org_id = ANY(...)`.

## Design decisions

| Decision | Reason |
|---|---|
| A separate service and web page, shown in an ADempiere window through an embedded web view | Swing cannot draw this kind of dashboard natively, and model inference must not run in the ADempiere client or server. The window only displays the page |
| Views in a separate schema, read through a role that sees nothing else | The service cannot read passwords, API keys or any table not listed, whatever bug it has |
| Organisation rules in a view, not in Python | One definition, checkable against ADempiere, and used identically by every query |
| Separate jar on the launcher classpath | No `RUN_setup`, no change to `Adempiere.jar` or `customization.jar`, removable by deleting one file |
| Dictionary records by SQL script under entity type `INSAI` | Transparent, transactional, and fully reversible; the existing Ask AI records were made the same way. A 2Pack is also exported |
| Forecast results in files, not database tables | Keeps the service's database role strictly read-only |
| Assistant picks from approved intents with an embedding model | No generated SQL, no text sent outside, and a question it cannot place is declined |
| Synthetic demand kept in separate files and labelled at every level | Real GardenWorld history cannot be forecast, and a synthetic number must never be mistaken for a real one |
| Kept separate from the existing Ask AI | Ask AI runs model-written SQL as the database superuser and sends rows to an external service |

## Packages

| Package | Why it is needed |
|---|---|
| `fastapi`, `uvicorn` | The HTTP API and the server that runs it |
| `psycopg` | PostgreSQL driver and connection pool |
| `plotly` | Only for the `plotly.min.js` it bundles, so charts work offline |
| `torch` | Runs the two models, CPU only |
| `chronos-forecasting` | Amazon Chronos forecasting models; brings `numpy`, `pandas`, `transformers` |
| `sentence-transformers` | Runs `all-MiniLM-L6-v2` for question matching |
| `pytest`, `httpx` | Tests only |

No paid API is used. The only outbound connections are to PyPI at install time and to Hugging Face for the first download of each model.

## Where things are

| Path | Contents |
|---|---|
| `db\` | Schema install, uninstall, smoke test and cross-check SQL |
| `insightai\` | The service |
| `adempiere\` | Launcher source, dictionary install and uninstall SQL, start script, exported 2Pack |
| `scripts\` | Install, run and test scripts |
| `tests\` | Python tests, the two Java harnesses, assistant question sets |
| `docs\` | Stage write-ups, KPI definitions, setup guide |
| `config.toml` | Settings |
| `.env`, `.venv\`, `data\`, `models\`, `build\` | Generated; not in git |
