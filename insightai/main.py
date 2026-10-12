"""HTTP layer: session handling, the JSON API and the dashboard page."""
from __future__ import annotations

import html
import logging
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth, db, launch, queries
from .auth import Session
from .config import get_settings
from .assistant import engine as assistant_engine
from .assistant import matcher as assistant_matcher
from .forecast import store as forecast_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("insightai")

STATIC = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_settings()  # fail at start-up, not on the first request, if configuration is incomplete
    assistant_matcher.warm_up()   # load the embedding model in the background
    yield
    db.close_pool()


app = FastAPI(title="ADempiere InsightAI", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.exception_handler(db.DatabaseUnavailable)
async def database_unavailable(_: Request, exc: db.DatabaseUnavailable) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def unexpected(_: Request, exc: Exception) -> JSONResponse:
    # Log the type only: exception text can carry SQL or connection details.
    log.exception("unhandled %s", type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": "InsightAI hit an unexpected error. See the service log."})


# --------------------------------------------------------------------------------------
# Scope and filters
# --------------------------------------------------------------------------------------

def _default_from(today: date) -> date:
    """First day of the month that makes the default range span `default_months` calendar months."""
    months_back = get_settings().default_months - 1
    year, month = today.year, today.month - months_back
    while month < 1:
        year, month = year - 1, month + 12
    return date(year, month, 1)


def _scope_and_filters(
    session: Session = Depends(auth.require_session),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    org_id: int | None = Query(None),
    warehouse_id: int | None = Query(None),
    category_id: int | None = Query(None),
    bpartner_id: int | None = Query(None),
) -> tuple[queries.Scope, queries.Filters]:
    today = date.today()
    date_to = date_to or today
    date_from = date_from or _default_from(today)
    if date_from > date_to:
        raise HTTPException(status_code=422, detail="The start date is after the end date.")

    # The organisation filter can only narrow what the role already allows.
    org_ids = session.org_ids
    if org_id is not None:
        if org_id not in session.org_ids:
            raise HTTPException(status_code=403, detail="Your role has no access to that organisation.")
        org_ids = (org_id,)
    scope = queries.Scope(session.client_id, org_ids)

    if warehouse_id is not None or category_id is not None or bpartner_id is not None:
        options = queries.filter_options(queries.Scope(session.client_id, session.org_ids))
        if warehouse_id is not None and warehouse_id not in {w["id"] for w in options["warehouses"]}:
            raise HTTPException(status_code=403, detail="Your role has no access to that warehouse.")
        if category_id is not None and category_id not in {c["id"] for c in options["categories"]}:
            raise HTTPException(status_code=422, detail="Unknown product category.")
        if bpartner_id is not None and bpartner_id not in {b["id"] for b in options["bpartners"]}:
            raise HTTPException(status_code=422, detail="Unknown business partner.")

    return scope, queries.Filters(date_from, date_to, warehouse_id, category_id, bpartner_id)


# --------------------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------------------

@app.get("/api/health")
def health() -> dict[str, str]:
    db.query_one("SELECT 1 AS ok")
    return {"status": "ok"}


@app.get("/api/me")
def me(session: Session = Depends(auth.require_session)) -> dict:
    settings = get_settings()
    today = date.today()
    return {
        "user": session.user_name,
        "role": session.role_name,
        "client": session.client_name,
        "currency": session.currency,
        "filters": queries.filter_options(queries.Scope(session.client_id, session.org_ids)),
        "default_from": _default_from(today).isoformat(),
        "default_to": today.isoformat(),
        "top_n": settings.top_n,
    }


@app.get("/api/kpis")
def kpis(scoped: tuple[queries.Scope, queries.Filters] = Depends(_scope_and_filters)) -> dict:
    scope, filters = scoped
    cards = queries.kpis(scope, filters)
    cards.append(forecast_store.stockout_card(scope, filters))
    return {"period": {"from": filters.date_from.isoformat(), "to": filters.date_to.isoformat()}, "cards": cards}


@app.get("/api/charts/{name}")
def chart(name: str, scoped: tuple[queries.Scope, queries.Filters] = Depends(_scope_and_filters)) -> dict:
    if name not in queries.CHARTS:
        raise HTTPException(status_code=404, detail="Unknown chart.")
    scope, filters = scoped
    return queries.chart(name, scope, filters)


class Question(BaseModel):
    question: str = Field(max_length=2000)


@app.post("/api/assistant/ask")
def assistant_ask(body: Question, session: Session = Depends(auth.require_session)) -> dict:
    return assistant_engine.ask(session, body.question)


@app.get("/api/assistant/questions")
def assistant_questions(_: Session = Depends(auth.require_session)) -> list:
    return assistant_engine.supported_questions()


@app.get("/api/forecast")
def forecast(mode: str = Query("real", pattern="^(real|synthetic)$"),
             scoped: tuple[queries.Scope, queries.Filters] = Depends(_scope_and_filters)) -> dict:
    scope, filters = scoped
    return forecast_store.summary(mode, scope, filters)


@app.get("/api/forecast/series")
def forecast_series(product_id: int, warehouse_id: int, mode: str = Query("real", pattern="^(real|synthetic)$"),
                    session: Session = Depends(auth.require_session)) -> dict:
    # Looked up within the session's organisations only, so another organisation's series is "not found".
    found = forecast_store.series(mode, queries.Scope(session.client_id, session.org_ids), product_id, warehouse_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No forecast series for that product and warehouse.")
    return found


@app.post("/api/forecast/run")
def forecast_run(_: Session = Depends(auth.require_session)) -> dict:
    return forecast_store.start_run()


@app.get("/api/forecast/status")
def forecast_status(_: Session = Depends(auth.require_session)) -> dict:
    return forecast_store.run_status()


# --------------------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------------------

def _set_session_cookie(response, user_id: int, role_id: int) -> None:
    ttl = get_settings().session_hours * 3600
    response.set_cookie(auth.COOKIE, auth.issue_token(user_id, role_id, ttl), max_age=ttl,
                        httponly=True, samesite="strict", path="/")


@app.get("/", include_in_schema=False)
def index(request: Request):
    token = request.cookies.get(auth.COOKIE)
    if not (token and auth.read_token(token)):
        if get_settings().dev_login:
            return RedirectResponse("/dev/login", status_code=303)
        return HTMLResponse("<h1>InsightAI</h1><p>Open InsightAI from the ADempiere menu.</p>", status_code=401)
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


class LaunchRequest(BaseModel):
    user_id: int
    role_id: int
    timestamp: int
    nonce: str = Field(min_length=8, max_length=64)
    signature: str = Field(min_length=64, max_length=64)


@app.post("/auth/launch-token", include_in_schema=False)
def launch_token(body: LaunchRequest) -> JSONResponse:
    """Called by the ADempiere launcher process, not by a browser."""
    try:
        code = launch.issue_code(body.user_id, body.role_id, body.timestamp, body.nonce, body.signature)
    except launch.LaunchRefused as refused:
        log.warning("launch refused for user %s role %s: %s", body.user_id, body.role_id, refused.message)
        return JSONResponse(status_code=refused.status, content={"detail": refused.message})
    return JSONResponse({"url": f"{get_settings().public_url}/launch?code={code}", "expires_in": launch.CODE_TTL_SECONDS})


@app.get("/launch", include_in_schema=False)
def launch_page(code: str = ""):
    ids = launch.redeem_code(code)
    if ids is None:
        return HTMLResponse("<!doctype html><meta charset='utf-8'><title>InsightAI</title>"
                            "<link rel='stylesheet' href='/static/styles.css'><main class='dev-login'>"
                            "<h1>This link has expired</h1><p>InsightAI links from ADempiere work once and for one minute. "
                            "Open InsightAI again from the ADempiere menu.</p></main>", status_code=401)
    response = RedirectResponse("/", status_code=303)
    _set_session_cookie(response, *ids)
    return response


@app.get("/logout", include_in_schema=False)
def logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(auth.COOKIE, path="/")
    return response


def _require_dev_login(request: Request) -> None:
    client = request.client.host if request.client else ""
    if not get_settings().dev_login or client not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(status_code=404, detail="Not found.")


@app.get("/dev/login", include_in_schema=False)
def dev_login(request: Request, user_id: int | None = None, role_id: int | None = None):
    """Development stand-in for the ADempiere launcher: choose which user and role to act as."""
    _require_dev_login(request)
    if user_id is not None and role_id is not None:
        if auth.load_session(user_id, role_id) is None:
            raise HTTPException(status_code=403, detail="That user does not hold that role in ADempiere.")
        response = RedirectResponse("/", status_code=303)
        _set_session_cookie(response, user_id, role_id)
        return response

    rows = db.query("SELECT ad_user_id::int AS uid, user_name, ad_role_id::int AS rid, role_name, client_name "
                    "FROM v_user_role WHERE ad_client_id <> 0 ORDER BY client_name, user_name, role_name")
    items = "".join(
        f'<li><a href="/dev/login?user_id={r["uid"]}&role_id={r["rid"]}">{html.escape(r["user_name"])} '
        f'as {html.escape(r["role_name"])}</a> <span>{html.escape(r["client_name"])}</span></li>'
        for r in rows
    )
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'><title>InsightAI development login</title>"
        "<link rel='stylesheet' href='/static/styles.css'>"
        "<main class='dev-login'><h1>InsightAI development login</h1>"
        "<p>Pick the ADempiere user and role to act as. This page exists only while "
        "<code>dev_login = true</code> in config.toml and only answers on this machine.</p>"
        f"<ul>{items}</ul></main>"
    )


@app.get("/vendor/plotly.min.js", include_in_schema=False)
def plotly_js():
    """Serve the plotly.js bundled with the Python plotly package, so charts work offline."""
    import plotly

    path = Path(plotly.__file__).resolve().parent / "package_data" / "plotly.min.js"
    if not path.exists():
        raise HTTPException(status_code=404, detail="plotly.min.js not found in the plotly package.")
    return FileResponse(path, media_type="application/javascript", headers={"Cache-Control": "max-age=86400"})
