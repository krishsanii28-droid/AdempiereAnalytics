"""Compare Chronos models on the synthetic series, on this machine's CPU.

    python -m insightai.forecast.benchmark amazon/chronos-bolt-tiny amazon/chronos-bolt-small amazon/chronos-t5-small amazon/chronos-2

Prints load time, inference time and hold-out accuracy for each. Models are downloaded to models/ on first use.
"""
import logging
import sys

from .. import db
from ..config import get_settings
from . import job, model

if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    settings = get_settings()
    names = sys.argv[1:] or [settings.forecast_model]
    client_id = db.query_one("SELECT MIN(ad_client_id)::int AS id FROM v_org")["id"]
    series = job.build(client_id, "synthetic", None, "benchmark")["series"]
    print(f"{len(series)} synthetic series, horizon {settings.horizon_weeks} weeks, {settings.evaluation_windows} windows each\n")
    print(f"{'model':28} {'load s':>7} {'infer s':>8} {'MAE':>7} {'MASE':>6} {'in range':>9} {'beats baseline':>15}")
    baseline_printed = False
    for name in names:
        forecaster, reason = model.load(name, job.MODEL_DIR)
        if forecaster is None:
            print(f"{name:28} could not load: {reason}")
            continue
        evaluation = job._evaluate(series, forecaster, settings)
        if not baseline_printed:
            for method, b in evaluation["baselines"].items():
                print(f"{method:28} {'':>7} {'':>8} {b['mae']:7.3f} {b['mase']:6.3f}")
            baseline_printed = True
        m = evaluation["model"]
        print(f"{name:28} {forecaster.load_seconds:7.1f} {m['inference_seconds']:8.2f} {m['mae']:7.3f} {m['mase']:6.3f} "
              f"{m['interval_coverage']:9.0%} {m['better_than_strongest_on']:>7} of {evaluation['windows_evaluated']}")
