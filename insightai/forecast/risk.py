"""Compare forecast demand with what is, and will be, in the warehouse."""
from __future__ import annotations


def _probability_demand_exceeds(supply: float, totals: dict[float, float]) -> tuple[float, str]:
    """P(demand over the horizon > supply), read off the forecast quantiles.

    Only the forecast quantiles are known, so the result is interpolated between them and reported
    as a bound outside them. Returns (number for sorting, text for display).
    """
    points = sorted((total, q) for q, total in totals.items())   # (demand, cumulative probability)
    lowest, highest = points[0], points[-1]
    if supply < lowest[0]:
        return 1 - lowest[1], f"over {round((1 - lowest[1]) * 100)}%"
    if supply >= highest[0]:
        return 1 - highest[1], f"under {round((1 - highest[1]) * 100)}%"
    for (d0, q0), (d1, q1) in zip(points, points[1:]):
        if d0 <= supply < d1:
            cumulative = q0 + (q1 - q0) * (supply - d0) / (d1 - d0)
            return 1 - cumulative, f"about {round((1 - cumulative) * 100)}%"
    return 1 - highest[1], f"under {round((1 - highest[1]) * 100)}%"


def assess(available: float, incoming: float, forecast: dict[float, list[float]],
           excess_cover_weeks: int) -> dict:
    """Stockout and excess assessment for one product in one warehouse.

    available  QtyOnHand - QtyReserved today
    incoming   open purchase order quantity promised within the horizon
    forecast   quantile -> weekly demand over the horizon (must include 0.5)

    Simplifications, stated in the UI: the horizon total for each quantile is the sum of the weekly
    quantiles (which widens the range slightly), and incoming stock is treated as arriving at the
    start of the horizon.
    """
    totals = {q: sum(values) for q, values in forecast.items()}
    low_q, high_q = min(totals), max(totals)
    median_total = totals[0.5]
    supply = available + incoming
    horizon = len(forecast[0.5])

    result = {
        "demand_low": totals[low_q], "demand_median": median_total, "demand_high": totals[high_q],
        "supply": supply, "projected_balance": supply - median_total,
        "stockout_probability": None, "stockout_probability_text": None,
        "stockout_week": None, "weeks_of_cover": None, "excess": False,
    }

    if totals[high_q] <= 0:
        result["level"] = "none"
        result["reason"] = "No demand is forecast in the horizon"
        result["excess"] = available > 0
        return result

    probability, text = _probability_demand_exceeds(supply, totals)
    result["stockout_probability"], result["stockout_probability_text"] = probability, text
    if supply < median_total:
        result["level"] = "high"
        result["reason"] = "Stock plus incoming is below the median forecast demand"
    elif supply < totals[high_q]:
        result["level"] = "medium"
        result["reason"] = f"Stock plus incoming is below the {round(high_q * 100)}th-percentile forecast demand"
    else:
        result["level"] = "low"
        result["reason"] = f"Stock plus incoming covers the {round(high_q * 100)}th-percentile forecast demand"

    # First week in which cumulative median demand uses up the supply
    running = 0.0
    for week, demand in enumerate(forecast[0.5], start=1):
        running += demand
        if running > supply:
            result["stockout_week"] = week
            break

    if median_total > 0:
        result["weeks_of_cover"] = max(available, 0.0) / (median_total / horizon)
        result["excess"] = result["weeks_of_cover"] > excess_cover_weeks
    return result
