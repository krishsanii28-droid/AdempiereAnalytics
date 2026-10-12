"""Command line: python -m insightai.forecast [--mode real|synthetic|both] [--model MODEL_ID]"""
import argparse
import json
import logging

from . import job

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the InsightAI demand forecast and stockout-risk files.")
    parser.add_argument("--mode", choices=("real", "synthetic", "both"), default="both")
    parser.add_argument("--model", help="Chronos model id; default is [forecast] model in config.toml")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpx2", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    modes = job.MODES if args.mode == "both" else (args.mode,)
    for path in job.run(modes, args.model):
        result = json.loads(path.read_text(encoding="utf-8"))
        evaluation = result["evaluation"]
        print(f"\n{path.name}: {'SYNTHETIC' if result['synthetic'] else 'real'} data, {result['counts']}")
        print(f"  model: {result['model']['used']} ({result['model']['requested']})"
              + (f" - fallback: {result['model']['fallback_reason']}" if result['model']['fallback_reason'] else ""))
        if not evaluation["baselines"]:
            print(f"  evaluation: not possible - {evaluation['reason']}")
            continue
        print(f"  evaluation on {evaluation['series_evaluated']} series, {evaluation['windows_evaluated']} hold-out windows of {evaluation['holdout_weeks']} weeks:")
        for name, b in evaluation["baselines"].items():
            flag = "  <- strongest baseline" if name == evaluation["strongest_baseline"] else ""
            print(f"    {name:26} MAE {b['mae']:.3f}  MASE {b['mase']:.3f}{flag}")
        if evaluation["model"]:
            m = evaluation["model"]
            print(f"    {m['name']:26} MAE {m['mae']:.3f}  MASE {m['mase']:.3f}  "
                  f"{m['interval']} range held {m['interval_coverage']:.0%} of actuals, better than the strongest "
                  f"baseline on {m['better_than_strongest_on']} of {evaluation['windows_evaluated']} windows, {m['inference_seconds']:.2f}s")
