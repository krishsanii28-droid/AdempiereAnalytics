"""Turn dated demand rows into a regular weekly series."""
from __future__ import annotations

from datetime import date, timedelta
from statistics import median


def week_start(day: date) -> date:
    """Monday of the ISO week containing `day`."""
    return day - timedelta(days=day.weekday())


def last_complete_week(today: date) -> date:
    """Monday of the most recent week that has fully ended."""
    return week_start(today) - timedelta(days=7)


def weekly_series(daily: list[tuple[date, float]], today: date) -> tuple[date | None, list[float], int]:
    """Aggregate (date, net quantity) rows into weekly totals.

    The series starts at the week of the first demand and ends at the last complete week, so a
    part-finished current week never looks like a drop in demand. Weeks with no rows are zero.
    A week where returns exceed shipments would be negative demand; it is set to zero and counted.

    Returns (first week's Monday, values, number of weeks clipped to zero).
    """
    end = last_complete_week(today)
    rows = [(week_start(d), q) for d, q in daily if week_start(d) <= end]
    if not rows:
        return None, [], 0
    start = min(w for w, _ in rows)
    values = [0.0] * (((end - start).days // 7) + 1)
    for week, quantity in rows:
        values[(week - start).days // 7] += float(quantity)
    clipped = sum(1 for v in values if v < 0)
    return start, [max(v, 0.0) for v in values], clipped


def flag_outliers(values: list[float], threshold: float = 3.5) -> list[int]:
    """Indexes of unusually high weeks, by the median-absolute-deviation rule.

    Outliers are flagged for the reader, not removed: a real promotion or bulk order is still demand.
    Zero weeks are left out of the reference level so intermittent products are not all flagged.
    """
    active = [v for v in values if v > 0]
    if len(active) < 8:
        return []
    centre = median(active)
    mad = median(abs(v - centre) for v in active)
    if mad == 0:
        return []
    limit = centre + threshold * 1.4826 * mad
    return [i for i, v in enumerate(values) if v > limit]
