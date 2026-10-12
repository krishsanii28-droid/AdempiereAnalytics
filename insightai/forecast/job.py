"""Builds the forecast result files the API serves.

    python -m insightai.forecast                  # real and synthetic, for every client
    python -m insightai.forecast --mode synthetic
    python -m insightai.forecast --model amazon/chronos-2

One JSON file per client and mode is written to data/. Real and synthetic results never share a
file, and each file says which it is.
"""
from __future__ import annotations

import csv
import json
import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .. import db
from ..config import ROOT, Settings, get_settings
from . import baselines, model, risk, synthetic
from .series import flag_outliers, last_complete_week, weekly_series

log = logging.getLogger("insightai.forecast")

DATA_DIR = ROOT / "data"
MODEL_DIR = ROOT / "models"
MODES = ("real", "synthetic")


def result_path(client_id: int, mode: str) -> Path:
    return DATA_DIR / f"forecast_{client_id}_{mode}.json"


# --------------------------------------------------------------------------------------
# Inputs (read through the insightai views; the job sees all organisations of a client,
# and the API filters the stored result by the session's organisations when serving it)
# --------------------------------------------------------------------------------------

def _load_stock(client_id: int) -> dict[tuple[int, int], dict[str, Any]]:
    rows = db.query(
        """SELECT ad_org_id::int AS org_id, m_warehouse_id::int AS warehouse_id, m_product_id::int AS product_id,
                  m_product_category_id::int AS category_id, qty_on_hand, qty_reserved, qty_ordered, qty_available
           FROM v_stock WHERE ad_client_id = %(c)s""", {"c": client_id})
    return {(r["warehouse_id"], r["product_id"]): r for r in rows}


def _load_demand(client_id: int) -> dict[tuple[int, int], dict[str, Any]]:
    rows = db.query(
        """SELECT ad_org_id::int AS org_id, m_warehouse_id::int AS warehouse_id, m_product_id::int AS product_id,
                  m_product_category_id::int AS category_id, demand_date, qty_net
           FROM v_demand_daily WHERE ad_client_id = %(c)s ORDER BY demand_date""", {"c": client_id})
    grouped: dict[tuple[int, int], dict[str, Any]] = {}
    for r in rows:
        entry = grouped.setdefault((r["warehouse_id"], r["product_id"]),
                                   {"org_id": r["org_id"], "category_id": r["category_id"], "daily": []})
        entry["daily"].append((r["demand_date"], r["qty_net"]))
    return grouped


def _load_incoming(client_id: int, today: date, horizon_end: date, grace_days: int) -> dict[tuple[int, int], dict[str, float]]:
    """Open purchase order quantity per product and warehouse, split by whether it can be counted on."""
    rows = db.query(
        """SELECT m_warehouse_id::int AS warehouse_id, m_product_id::int AS product_id, date_promised, qty_open
           FROM v_order_line
           WHERE ad_client_id = %(c)s AND issotrx = 'N' AND NOT is_return AND qty_open > 0 AND m_product_id IS NOT NULL""",
        {"c": client_id})
    result: dict[tuple[int, int], dict[str, float]] = {}
    for r in rows:
        entry = result.setdefault((r["warehouse_id"], r["product_id"]), {"in_horizon": 0.0, "later": 0.0, "stale": 0.0})
        promised = r["date_promised"]
        if promised is None or promised < today - timedelta(days=grace_days):
            entry["stale"] += r["qty_open"]          # long overdue or undated: not counted as incoming
        elif promised <= horizon_end:
            entry["in_horizon"] += r["qty_open"]
        else:
            entry["later"] += r["qty_open"]
    return result


# --------------------------------------------------------------------------------------
# Forecast and evaluation
# --------------------------------------------------------------------------------------

def _evaluate(series: list[dict[str, Any]], forecaster: model.ChronosForecaster | None, s: Settings) -> dict[str, Any]:
    """Chronological holdout: hide `horizon` weeks, forecast them, compare with what happened.

    The model is compared with every baseline that applies to all evaluated series, and the
    strongest of those (lowest MASE) is the one it has to beat.
    """
    horizon = s.horizon_weeks
    low, high = s.quantiles[0], s.quantiles[-1]
    candidates = [x for x in series if x["status"] == "forecast" and len(x["history"]) >= s.min_history_weeks + horizon]
    summary: dict[str, Any] = {"holdout_weeks": horizon, "series_evaluated": len(candidates),
                               "model": None, "baselines": {}, "strongest_baseline": None}
    if not candidates:
        summary["reason"] = (f"No series has enough history: {s.min_history_weeks + horizon} weeks "
                             f"({s.min_history_weeks} to forecast from plus {horizon} held out) "
                             f"with demand in at least {s.min_demand_weeks} of them")
        return summary

    # Rolling origin: each series is cut at up to `evaluation_windows` points, `horizon` weeks apart,
    # always forecasting weeks the model has not seen.
    trains, actuals = [], []
    for x in candidates:
        history = x["history"]
        for k in range(s.evaluation_windows):
            cut = len(history) - horizon * (k + 1)
            if cut < s.min_history_weeks:
                break
            trains.append(history[:cut])
            actuals.append(history[cut:cut + horizon])
    summary["windows_evaluated"] = len(trains)

    def score(predictions: list[list[float]]) -> dict[str, Any]:
        maes = [baselines.mae(a, p) for a, p in zip(actuals, predictions)]
        mases = [baselines.mase(a, p, t) for a, p, t in zip(actuals, predictions, trains)]
        defined = [m for m in mases if m is not None]
        return {"mae": sum(maes) / len(maes), "mase": sum(defined) / len(defined) if defined else None,
                "per_series_mae": maes}

    shortest = min(len(t) for t in trains)
    methods = ["naive", "moving_average"] + (["seasonal_naive"] if shortest >= 2 * baselines.SEASON_WEEKS else [])
    scores = {m: score([baselines.baseline_forecast(t, horizon, s.moving_average_weeks, m)[1] for t in trains]) for m in methods}
    summary["baselines"] = {m: {"mae": v["mae"], "mase": v["mase"]} for m, v in scores.items()}
    strongest = min(methods, key=lambda m: scores[m]["mase"] if scores[m]["mase"] is not None else float("inf"))
    summary["strongest_baseline"] = strongest
    if "seasonal_naive" not in methods:
        summary["note"] = "Seasonal-naive needs two full years of history and was not applicable"

    if forecaster is not None:
        started = time.perf_counter()
        forecasts = forecaster.forecast(trains, horizon, list(s.quantiles))
        seconds = time.perf_counter() - started
        model_score = score([f[0.5] for f in forecasts])
        inside = sum(1 for f, a in zip(forecasts, actuals) for i, v in enumerate(a) if f[low][i] <= v <= f[high][i])
        summary["model"] = {
            "name": forecaster.name, "mae": model_score["mae"], "mase": model_score["mase"],
            "interval_coverage": inside / (len(trains) * horizon),
            "interval": f"{round(low * 100)}-{round(high * 100)}%",
            "interval_nominal": high - low,
            "better_than_strongest_on": sum(1 for m, b in zip(model_score["per_series_mae"], scores[strongest]["per_series_mae"]) if m < b),
            "inference_seconds": seconds,
        }
    return summary


def _forecast_all(series: list[dict[str, Any]], forecaster: model.ChronosForecaster | None, s: Settings) -> float:
    """Fill in `forecast` and `method` for every series long enough. Returns inference seconds."""
    ready = [x for x in series if x["status"] == "forecast"]
    seconds = 0.0
    if forecaster is not None and ready:
        started = time.perf_counter()
        forecasts = forecaster.forecast([x["history"] for x in ready], s.horizon_weeks, list(s.quantiles))
        seconds = time.perf_counter() - started
        for x, f in zip(ready, forecasts):
            x["method"], x["forecast"] = "chronos", {str(q): v for q, v in f.items()}
    else:
        for x in ready:
            method, f = baselines.baseline_quantiles(x["history"], s.horizon_weeks, s.moving_average_weeks, list(s.quantiles))
            x["method"], x["forecast"] = method, {str(q): v for q, v in f.items()}
    return seconds


def build(client_id: int, mode: str, forecaster: model.ChronosForecaster | None, model_reason: str | None,
          today: date | None = None) -> dict[str, Any]:
    s = get_settings()
    today = today or date.today()
    last_week = last_complete_week(today)
    first_forecast_week = last_week + timedelta(days=7)
    horizon_end = first_forecast_week + timedelta(days=7 * s.horizon_weeks - 1)

    stock = _load_stock(client_id)
    incoming = _load_incoming(client_id, today, horizon_end, s.overdue_grace_days)
    series: list[dict[str, Any]] = []

    if mode == "real":
        demand = _load_demand(client_id)
        keys = {k for k, v in stock.items() if v["qty_on_hand"] or v["qty_reserved"] or v["qty_ordered"]} | set(demand)
        for key in sorted(keys):
            source = demand.get(key) or stock[key]
            start, values, clipped = weekly_series(demand[key]["daily"], today) if key in demand else (None, [], 0)
            series.append({"warehouse_id": key[0], "product_id": key[1], "org_id": source["org_id"],
                           "category_id": source["category_id"], "history_start": start.isoformat() if start else None,
                           "history": values, "weeks_clipped_to_zero": clipped})
    else:
        start = last_week - timedelta(days=7 * (s.synthetic_weeks - 1))
        for key, item in sorted(stock.items()):
            if item["qty_on_hand"] <= 0:
                continue
            profile, values = synthetic.generate_series(s.synthetic_seed, key[1], key[0], item["qty_on_hand"], s.synthetic_weeks)
            series.append({"warehouse_id": key[0], "product_id": key[1], "org_id": item["org_id"],
                           "category_id": item["category_id"], "history_start": start.isoformat(),
                           "history": values, "weeks_clipped_to_zero": 0, "synthetic_profile": profile})
        _write_synthetic_csv(client_id, series)

    for x in series:
        weeks = len(x["history"])
        x["outlier_weeks"] = flag_outliers(x["history"])
        x["forecast"], x["method"] = None, None
        demand_weeks = sum(1 for v in x["history"] if v > 0)
        if weeks >= s.min_history_weeks and demand_weeks >= s.min_demand_weeks:
            x["status"] = "forecast"
        elif weeks >= s.min_history_weeks:
            x["status"] = "insufficient_history"
            x["status_reason"] = (f"Only {demand_weeks} week(s) with any demand in {weeks} weeks; "
                                  f"{s.min_demand_weeks} are needed")
        elif weeks == 0:
            x["status"], x["status_reason"] = "no_history", "No completed customer shipments for this product in this warehouse"
        else:
            x["status"] = "insufficient_history"
            x["status_reason"] = f"Only {weeks} week(s) of history; {s.min_history_weeks} are needed"

    evaluation = _evaluate(series, forecaster, s)
    forecast_seconds = _forecast_all(series, forecaster, s)

    for x in series:
        key = (x["warehouse_id"], x["product_id"])
        item = stock.get(key, {"qty_on_hand": 0.0, "qty_reserved": 0.0, "qty_ordered": 0.0, "qty_available": 0.0})
        inbound = incoming.get(key, {"in_horizon": 0.0, "later": 0.0, "stale": 0.0})
        x["stock"] = {"on_hand": item["qty_on_hand"], "reserved": item["qty_reserved"],
                      "available": item["qty_available"], "storage_qty_ordered": item["qty_ordered"]}
        x["incoming"] = inbound
        if x["forecast"] is None:
            x["risk"] = {"level": "unknown", "reason": x["status_reason"]}
        else:
            quantile_forecast = {float(q): v for q, v in x["forecast"].items()}
            x["risk"] = risk.assess(item["qty_available"], inbound["in_horizon"], quantile_forecast, s.excess_cover_weeks)

    return {
        "client_id": client_id,
        "mode": mode,
        "synthetic": mode == "synthetic",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of": today.isoformat(),
        "frequency": "weekly",
        "history_end_week": last_week.isoformat(),
        "forecast_start_week": first_forecast_week.isoformat(),
        "forecast_end": horizon_end.isoformat(),
        "horizon_weeks": s.horizon_weeks,
        "quantiles": list(s.quantiles),
        "min_history_weeks": s.min_history_weeks,
        "model": {
            "requested": s.forecast_model if forecaster is None else forecaster.name,
            "used": "chronos" if forecaster is not None else "baseline",
            "fallback_reason": model_reason,
            "load_seconds": forecaster.load_seconds if forecaster else None,
            "loaded_from": forecaster.source if forecaster else None,
            "forecast_seconds": forecast_seconds,
        },
        "evaluation": evaluation,
        "counts": {
            "series": len(series),
            "forecast": sum(1 for x in series if x["status"] == "forecast"),
            "insufficient_history": sum(1 for x in series if x["status"] == "insufficient_history"),
            "no_history": sum(1 for x in series if x["status"] == "no_history"),
        },
        "assumptions": _assumptions(s, mode),
        "series": series,
    }


def _assumptions(s: Settings, mode: str) -> list[str]:
    low, high = round(s.quantiles[0] * 100), round(s.quantiles[-1] * 100)
    items = [
        "Demand is completed customer shipments minus customer returns, by movement date, summed per week (Monday to Sunday). "
        "Weeks without shipments count as zero. Voided and reversed documents are excluded.",
        f"The forecast covers the next {s.horizon_weeks} weeks. The range shown is the {low}th to {high}th percentile.",
        "Available stock is quantity on hand minus quantity reserved, as of the time the forecast was run.",
        f"Incoming stock is open purchase order quantity promised no more than {s.overdue_grace_days} days ago and no later than "
        "the end of the horizon, treated as arriving at the start of it. Older or undated open purchase lines are not counted.",
        "The horizon total for each percentile is the sum of the weekly percentiles, which makes the range slightly too wide.",
        f"Stock that would last more than {s.excess_cover_weeks} weeks at the median forecast rate is flagged as excess.",
        "Outlier weeks are flagged, not removed.",
        "Results are advisory. Nothing is ordered, posted or changed in ADempiere.",
    ]
    if mode == "synthetic":
        items.insert(0, "SYNTHETIC DEMAND: the demand history is generated, not taken from ADempiere. Its level is derived "
                        "from current stock so the demo shows a spread of situations. Stock and purchase quantities are real.")
    return items


def _write_synthetic_csv(client_id: int, series: list[dict[str, Any]]) -> None:
    folder = DATA_DIR / "synthetic"
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / f"demand_weekly_{client_id}.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["synthetic", "warehouse_id", "product_id", "profile", "week_start", "quantity"])
        for x in series:
            start = date.fromisoformat(x["history_start"])
            for i, value in enumerate(x["history"]):
                writer.writerow(["SYNTHETIC", x["warehouse_id"], x["product_id"], x["synthetic_profile"],
                                 (start + timedelta(days=7 * i)).isoformat(), value])


def run(modes: tuple[str, ...] = MODES, model_name: str | None = None) -> list[Path]:
    s = get_settings()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    forecaster, reason = model.load(model_name or s.forecast_model, MODEL_DIR)
    if forecaster is None:
        log.warning("using the baseline forecast: %s", reason)
    written = []
    clients = [r["id"] for r in db.query("SELECT DISTINCT ad_client_id::int AS id FROM v_org ORDER BY 1")]
    for client_id in clients:
        for mode in modes:
            result = build(client_id, mode, forecaster, reason)
            path = result_path(client_id, mode)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(result), encoding="utf-8")
            temporary.replace(path)            # the API never reads a half-written file
            written.append(path)
            log.info("client %s %s: %s series, %s forecast, model=%s", client_id, mode,
                     result["counts"]["series"], result["counts"]["forecast"], result["model"]["used"])
    return written
