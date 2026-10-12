"""Synthetic weekly demand, for developing and demonstrating the forecast when real history is too thin.

Nothing here is written to ADempiere. The series exist only in memory and in data/synthetic/*.csv,
and every result built from them is tagged synthetic.

The series are attached to real product and warehouse ids so they can be compared with real stock,
but the demand itself is invented: its level is derived from the current stock so that the demo
contains a spread of well-covered, at-risk and over-stocked products.
"""
from __future__ import annotations

import math
import random

PROFILES = ("steady", "seasonal", "trend_up", "trend_down", "intermittent")


def generate_series(seed: int, product_id: int, warehouse_id: int, qty_on_hand: float, weeks: int) -> tuple[str, list[float]]:
    """One deterministic series: same seed and ids always give the same numbers."""
    rng = random.Random(f"{seed}:{product_id}:{warehouse_id}")
    profile = rng.choice(PROFILES)
    cover_weeks = rng.choice((1.5, 3, 5, 8, 12, 20, 40, 80))      # how long today's stock would last
    level = max(qty_on_hand, 4.0) / cover_weeks
    phase = rng.uniform(0, 2 * math.pi)
    amplitude = rng.uniform(0.3, 0.6)
    idle_share = rng.uniform(0.5, 0.7)

    values = []
    for t in range(weeks):
        mean = level
        if profile == "seasonal":
            mean *= 1 + amplitude * math.sin(2 * math.pi * t / 52 + phase)
        elif profile == "trend_up":
            mean *= 0.6 + 0.8 * t / weeks
        elif profile == "trend_down":
            mean *= 1.4 - 0.8 * t / weeks
        elif profile == "intermittent":
            mean = 0.0 if rng.random() < idle_share else level / (1 - idle_share)
        value = rng.gauss(mean, math.sqrt(max(mean, 0.25)) * 0.8) if mean > 0 else 0.0
        if mean > 0 and rng.random() < 0.02:                       # an occasional bulk order
            value *= rng.uniform(3, 5)
        values.append(float(max(round(value), 0)))
    return profile, values
