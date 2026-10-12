"""Simple statistical forecasts and the accuracy measures used to judge the model against them."""
from __future__ import annotations

SEASON_WEEKS = 52


def naive(history: list[float], horizon: int) -> list[float]:
    return [history[-1]] * horizon


def moving_average(history: list[float], horizon: int, window: int) -> list[float]:
    recent = history[-window:]
    return [sum(recent) / len(recent)] * horizon


def seasonal_naive(history: list[float], horizon: int, season: int = SEASON_WEEKS) -> list[float]:
    """The value from the same week one season earlier."""
    return [history[len(history) - season + (i % season)] for i in range(horizon)]


def choose_baseline(history: list[float], window: int) -> str:
    """Seasonal-naive only with two full seasons of history; otherwise moving average, otherwise naive."""
    if len(history) >= 2 * SEASON_WEEKS:
        return "seasonal_naive"
    if len(history) >= window:
        return "moving_average"
    return "naive"


def baseline_forecast(history: list[float], horizon: int, window: int, method: str | None = None) -> tuple[str, list[float]]:
    method = method or choose_baseline(history, window)
    if method == "seasonal_naive":
        return method, seasonal_naive(history, horizon)
    if method == "moving_average":
        return method, moving_average(history, horizon, window)
    return "naive", naive(history, horizon)


def _in_sample_errors(history: list[float], window: int, method: str) -> list[float]:
    """One-step-ahead errors the baseline would have made on its own history."""
    errors = []
    first = {"seasonal_naive": SEASON_WEEKS, "moving_average": window}.get(method, 1)
    for t in range(first, len(history)):
        _, prediction = baseline_forecast(history[:t], 1, window, method)
        errors.append(history[t] - prediction[0])
    return errors


def _quantile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    position = q * (len(sorted_values) - 1)
    low = int(position)
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (position - low)


def baseline_quantiles(history: list[float], horizon: int, window: int, quantiles: list[float],
                       method: str | None = None) -> tuple[str, dict[float, list[float]]]:
    """Baseline point forecast plus an uncertainty range taken from its own past errors."""
    method, point = baseline_forecast(history, horizon, window, method)
    errors = sorted(_in_sample_errors(history, window, method))
    result = {}
    for q in quantiles:
        shift = 0.0 if q == 0.5 else _quantile(errors, q)
        result[q] = [max(p + shift, 0.0) for p in point]
    return method, result


def mae(actual: list[float], predicted: list[float]) -> float:
    return sum(abs(a - p) for a, p in zip(actual, predicted)) / len(actual)


def mase(actual: list[float], predicted: list[float], training: list[float]) -> float | None:
    """MAE scaled by the in-sample MAE of the one-step naive forecast.

    Below 1 means better than repeating last week's value. None when the training series never
    changes (the scale would be zero).
    """
    if len(training) < 2:
        return None
    scale = sum(abs(training[i] - training[i - 1]) for i in range(1, len(training))) / (len(training) - 1)
    if scale == 0:
        return None
    return mae(actual, predicted) / scale
