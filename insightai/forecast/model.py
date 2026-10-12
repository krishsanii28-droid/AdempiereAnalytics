"""Chronos pretrained forecasting models.

Importing this module never fails: torch and chronos are loaded only inside load(), and every
failure there is reported as a reason so the caller can fall back to the statistical baseline.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

log = logging.getLogger("insightai.forecast")


class ChronosForecaster:
    def __init__(self, pipeline, name: str, load_seconds: float, source: str):
        self._pipeline = pipeline
        self.name = name
        self.load_seconds = load_seconds
        self.source = source          # "local cache" or "downloaded"

    def forecast(self, histories: list[list[float]], horizon: int, quantiles: list[float]) -> list[dict[float, list[float]]]:
        """Quantile forecasts for a batch of series. Negative values are clipped: demand cannot be negative."""
        import torch

        if not histories:
            return []
        inputs = [torch.tensor(h, dtype=torch.float32) for h in histories]
        with torch.no_grad():
            result, _ = self._pipeline.predict_quantiles(inputs, prediction_length=horizon, quantile_levels=list(quantiles))
        forecasts = []
        for i in range(len(histories)):
            # Chronos and Chronos-Bolt return one [series, horizon, quantile] tensor;
            # Chronos-2 returns a list of [variates, horizon, quantile] tensors.
            block = result[i]
            if block.dim() == 3:
                block = block[0]
            forecasts.append({q: [max(float(v), 0.0) for v in block[:, j]] for j, q in enumerate(quantiles)})
        return forecasts


def load(model_name: str, cache_dir: Path) -> tuple[ChronosForecaster | None, str | None]:
    """Load a model from the local cache, downloading it on first use.

    Returns (forecaster, None) or (None, reason it could not be loaded).
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(cache_dir))                 # keep downloads inside the project
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")    # Windows without developer mode
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    try:
        import torch
        from chronos import BaseChronosPipeline
        from transformers.utils import logging as transformers_logging

        transformers_logging.disable_progress_bar()
    except ImportError as exc:
        return None, f"Forecasting packages are not installed ({exc.name}). Run scripts\\setup_service.ps1 -ML."

    started = time.perf_counter()
    last_error = "unknown error"
    # Try the local cache first so a machine that has the model never needs the network.
    for local_only, source in ((True, "local cache"), (False, "downloaded")):
        try:
            pipeline = BaseChronosPipeline.from_pretrained(
                model_name, device_map="cpu", torch_dtype=torch.float32, local_files_only=local_only)
            return ChronosForecaster(pipeline, model_name, time.perf_counter() - started, source), None
        except Exception as exc:  # noqa: BLE001 - any load failure means "use the baseline"
            last_error = f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"
            if not local_only:
                log.warning("could not load %s: %s", model_name, last_error)
    return None, f"Model {model_name} is not in the local cache and could not be downloaded ({last_error})"
