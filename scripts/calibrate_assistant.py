"""Shows how well the assistant's matcher separates supported from unsupported questions.

    .venv\\Scripts\\python.exe scripts\\calibrate_assistant.py            # development questions, with detail
    .venv\\Scripts\\python.exe scripts\\calibrate_assistant.py --test     # the held-back test questions

For the MiniLM matcher and the keyword fallback it prints what would happen to each question at a
range of thresholds. Use the development set to choose [assistant] threshold in config.toml; use
the test set, which was not looked at while tuning, to report how well that choice holds up.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

import assistant_questions as questions  # noqa: E402

from insightai import db  # noqa: E402
from insightai.assistant import engine, matcher  # noqa: E402
from insightai.assistant.intents import BY_ID  # noqa: E402
from insightai.config import get_settings  # noqa: E402

logging.basicConfig(level=logging.ERROR)
use_test = "--test" in sys.argv
supported_set = questions.TEST_SUPPORTED if use_test else questions.SUPPORTED
unsupported_set = questions.TEST_UNSUPPORTED if use_test else questions.UNSUPPORTED

client_id = db.query_one("SELECT MIN(ad_client_id)::int AS id FROM v_org")["id"]
products = db.query("SELECT m_product_id::int AS id, product_name AS name FROM v_product WHERE ad_client_id = %(c)s", {"c": client_id})
partners = db.query("SELECT c_bpartner_id::int AS id, bpartner_name AS name FROM v_bpartner WHERE ad_client_id = %(c)s", {"c": client_id})


def run(question: str, force: bool):
    text, product, partner, eligible = engine.prepare(question, products, partners)
    return matcher.match(text, eligible=eligible, force_keywords=force), {"product": product, "bpartner": partner}


def decision(match, found, threshold: float) -> str | None:
    """The intent that would be answered, or None if the assistant would decline."""
    intent_id, score = match.ranked[0]
    if score < threshold or intent_id == "out_of_scope":
        return None
    if any(found[name] is None for name in BY_ID[intent_id].requires):
        return None          # "couldn't find a product name in the question"
    return intent_id


print(f"{'TEST' if use_test else 'DEVELOPMENT'} questions: {len(supported_set)} supported, {len(unsupported_set)} unsupported")
for name, force in (("MiniLM", False), ("Keyword fallback", True)):
    print(f"\n===== {name} =====")
    supported = [(q, want, *run(q, force)) for q, want in supported_set]
    unsupported = [(q, *run(q, force)) for q in unsupported_set]
    if not force and supported[0][2].matcher != "minilm":
        print("model not available:", supported[0][2].fallback_reason)
        continue
    configured = 1.0 if force else get_settings().assistant_threshold
    for q, want, m, found in supported:
        got = decision(m, found, configured)
        mark = "ok " if got == want else ("-- " if got is None else "XX ")
        print(f"  {mark} {m.score:.3f}  {q[:64]:64} -> {got or 'declined'}" + ("" if got == want else f"  (wanted {want})"))
    print("  -- should be declined --")
    for q, m, found in unsupported:
        got = decision(m, found, configured)
        print(f"  {'ok ' if got is None else 'XX '} {m.score:.3f}  {q[:64]:64} nearest {m.ranked[0][0]}" + ("" if got is None else "  ANSWERED"))
    print("\n  threshold   supported: right  wrong  declined    unsupported: declined  answered")
    for threshold in ([1.0] if force else [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]):
        got = [(want, decision(m, found, threshold)) for _, want, m, found in supported]
        right = sum(1 for want, g in got if g == want)
        declined = sum(1 for _, g in got if g is None)
        refused = sum(1 for _, m, found in unsupported if decision(m, found, threshold) is None)
        marker = "  <- configured" if threshold == configured else ""
        print(f"  {threshold:9.2f}   {right:>16}  {len(got) - right - declined:>5}  {declined:>8}    "
              f"{refused:>21}  {len(unsupported) - refused:>8}{marker}")
