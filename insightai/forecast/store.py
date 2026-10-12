"""Serves stored forecast results to the API, limited to what the session may see."""
from __future__ import annotations

import json
import threading
from datetime import date, datetime, timedelta
from typing import Any

from .. import db
from ..queries import Filters, Scope
from . import job

_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_LEVEL_ORDER = {"high": 0, "medium": 1, "low": 2, "none": 3, "unknown": 4}


def _load(client_id: int, mode: str) -> dict[str, Any] | None:
    path = job.result_path(client_id, mode)
    if not path.exists():
        return None
    modified = path.stat().st_mtime
    cached = _cache.get(str(path))
    if cached is None or cached[0] != modified:
        cached = (modified, json.loads(path.read_text(encoding="utf-8")))
        _cache[str(path)] = cached
    return cached[1]


def _visible(result: dict[str, Any], scope: Scope, filters: Filters | None) -> list[dict[str, Any]]:
    rows = [x for x in result["series"] if x["org_id"] in scope.org_ids]
    if filters is not None:
        if filters.warehouse_id is not None:
            rows = [x for x in rows if x["warehouse_id"] == filters.warehouse_id]
        if filters.category_id is not None:
            rows = [x for x in rows if x["category_id"] == filters.category_id]
    return rows


def _names(scope: Scope) -> tuple[dict[int, str], dict[int, str]]:
    products = {r["id"]: r["name"] for r in db.query(
        "SELECT m_product_id::int AS id, product_name AS name FROM v_product WHERE ad_client_id = %(c)s", {"c": scope.client_id})}
    warehouses = {r["id"]: r["name"] for r in db.query(
        "SELECT m_warehouse_id::int AS id, warehouse_name AS name FROM v_warehouse WHERE ad_client_id = %(c)s", {"c": scope.client_id})}
    return products, warehouses


def summary(mode: str, scope: Scope, filters: Filters) -> dict[str, Any]:
    result = _load(scope.client_id, mode)
    if result is None:
        return {"available": False, "mode": mode, "synthetic": mode == "synthetic",
                "reason": "No forecast has been run yet. Use Run forecast, or run: python -m insightai.forecast"}
    products, warehouses = _names(scope)
    rows = []
    for x in _visible(result, scope, filters):
        risk = x["risk"]
        rows.append({
            "product_id": x["product_id"], "warehouse_id": x["warehouse_id"],
            "product": products.get(x["product_id"], f"Product {x['product_id']}").strip(),
            "warehouse": warehouses.get(x["warehouse_id"], f"Warehouse {x['warehouse_id']}").strip(),
            "status": x["status"], "method": x["method"], "history_weeks": len(x["history"]),
            "outlier_weeks": len(x["outlier_weeks"]),
            "on_hand": x["stock"]["on_hand"], "reserved": x["stock"]["reserved"], "available": x["stock"]["available"],
            "incoming": x["incoming"]["in_horizon"], "incoming_stale": x["incoming"]["stale"],
            "incoming_later": x["incoming"]["later"], "storage_qty_ordered": x["stock"]["storage_qty_ordered"],
            "level": risk["level"], "reason": risk["reason"],
            "demand_low": risk.get("demand_low"), "demand_median": risk.get("demand_median"), "demand_high": risk.get("demand_high"),
            "probability": risk.get("stockout_probability"), "probability_text": risk.get("stockout_probability_text"),
            "stockout_week": risk.get("stockout_week"), "weeks_of_cover": risk.get("weeks_of_cover"),
            "excess": bool(risk.get("excess")),
        })
    rows.sort(key=lambda r: (_LEVEL_ORDER[r["level"]], -(r["probability"] or 0), r["product"], r["warehouse"]))
    meta = {k: result[k] for k in ("mode", "synthetic", "generated_at", "as_of", "frequency", "history_end_week",
                                   "forecast_start_week", "forecast_end", "horizon_weeks", "quantiles",
                                   "min_history_weeks", "model", "evaluation", "assumptions")}
    counts = {level: sum(1 for r in rows if r["level"] == level) for level in _LEVEL_ORDER}
    counts["series"] = len(rows)
    counts["forecast"] = sum(1 for r in rows if r["status"] == "forecast")
    counts["excess"] = sum(1 for r in rows if r["excess"])
    ignored = [label for label, value in (("business partner", filters.bpartner_id),) if value is not None]
    return {"available": True, **meta, "counts": counts, "rows": rows, "ignored": ignored}


def series(mode: str, scope: Scope, product_id: int, warehouse_id: int) -> dict[str, Any] | None:
    result = _load(scope.client_id, mode)
    if result is None:
        return None
    for x in _visible(result, scope, None):
        if x["product_id"] == product_id and x["warehouse_id"] == warehouse_id:
            start = date.fromisoformat(x["history_start"]) if x["history_start"] else None
            first_forecast = date.fromisoformat(result["forecast_start_week"])
            return {
                "mode": mode, "synthetic": result["synthetic"], "status": x["status"], "method": x["method"],
                "weeks": [(start + timedelta(days=7 * i)).isoformat() for i in range(len(x["history"]))] if start else [],
                "history": x["history"], "outlier_weeks": x["outlier_weeks"],
                "forecast_weeks": [(first_forecast + timedelta(days=7 * i)).isoformat() for i in range(result["horizon_weeks"])],
                "forecast": x["forecast"], "quantiles": result["quantiles"],
                "stock": x["stock"], "incoming": x["incoming"], "risk": x["risk"],
            }
    return None


def stockout_card(scope: Scope, filters: Filters) -> dict[str, Any]:
    """The dashboard KPI. Always from real data: a synthetic number never appears among the real KPIs."""
    data = summary("real", scope, filters)
    card = {"id": "stockout_risk", "label": "Products at stockout risk", "unit": "count", "available": False,
            "value": None, "reason": None, "detail": None, "delta": None, "delta_label": None,
            "ignored": data.get("ignored", []), "notes": []}
    if not data["available"]:
        card["reason"] = "No forecast has been run yet"
        return card
    counts = data["counts"]
    if counts["forecast"] == 0:
        card["reason"] = (f"Demand history is too short to forecast: none of the {counts['series']} "
                          "product and warehouse combinations has enough completed shipments")
        return card
    card.update(available=True, value=counts["high"] + counts["medium"],
                detail=f"{counts['high']} high and {counts['medium']} medium, next {data['horizon_weeks']} weeks, "
                       f"of {counts['forecast']} forecast")
    not_forecast = counts["series"] - counts["forecast"]
    if not_forecast:
        card["notes"].append(f"{not_forecast} combination(s) have too little history to forecast and are not counted")
    return card


# --------------------------------------------------------------------------------------
# Running the job from the UI: one run at a time, in a background thread
# --------------------------------------------------------------------------------------

_run_lock = threading.Lock()
_run_state: dict[str, Any] = {"running": False, "started_at": None, "finished_at": None, "error": None}


def _run() -> None:
    try:
        job.run()
        _run_state["error"] = None
    except Exception as exc:  # noqa: BLE001 - reported to the UI, never raised into the server
        job.log.exception("forecast run failed")
        _run_state["error"] = f"The forecast run failed ({type(exc).__name__}). See the service log."
    finally:
        _run_state.update(running=False, finished_at=datetime.now().isoformat(timespec="seconds"))


def start_run() -> dict[str, Any]:
    with _run_lock:
        if not _run_state["running"]:
            _run_state.update(running=True, started_at=datetime.now().isoformat(timespec="seconds"), finished_at=None, error=None)
            threading.Thread(target=_run, name="insightai-forecast", daemon=True).start()
    return dict(_run_state)


def run_status() -> dict[str, Any]:
    return dict(_run_state)
