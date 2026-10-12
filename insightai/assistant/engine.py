"""Answer one question: screen it, match it to an approved intent, validate parameters, run the template."""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

from .. import db, queries
from ..auth import Session
from ..config import get_settings
from . import matcher, params
from .intents import BY_ID, INTENTS, Context

log = logging.getLogger("insightai.assistant")


def supported_questions() -> list[dict[str, str]]:
    return [{"intent": i.id, "title": i.title, "example": i.examples[0]} for i in INTENTS
            if i.id not in ("action_request", "out_of_scope")]


def _entities(scope: queries.Scope) -> tuple[list[dict], list[dict]]:
    products = db.query("SELECT m_product_id::int AS id, product_name AS name FROM v_product "
                        "WHERE ad_client_id = %(c)s AND isactive = 'Y'", {"c": scope.client_id})
    partners = db.query("SELECT c_bpartner_id::int AS id, bpartner_name AS name FROM v_bpartner "
                        "WHERE ad_client_id = %(c)s AND isactive = 'Y'", {"c": scope.client_id})
    return products, partners


def prepare(question: str, products: list[dict], partners: list[dict]) -> tuple[str, Any, Any, set[str]]:
    """What the matcher sees, and which intents it may choose from.

    Names are swapped for neutral words, so "Joe Block" or "Oak Tree" cannot pull the question
    towards the wrong intent; the example phrasings use the same neutral words. An intent that
    needs a product is not offered when the question names only a customer, and the reverse.
    """
    product, partner = params.find_entities(question, products, partners)
    generic = f" {params.normalise(question)} "
    for entity, word in ((partner, "this customer"), (product, "this product")):
        if entity is not None:
            generic = generic.replace(f" {entity.matched_text} ", f" {word} ", 1)
    found = {"product": product is not None, "bpartner": partner is not None}
    eligible = set()
    for intent in INTENTS:
        missing = [name for name in intent.requires if not found[name]]
        if missing and any(found.values()):
            continue      # e.g. a product question when only a customer was named
        eligible.add(intent.id)
    return generic.strip(), product, partner, eligible


def _unsupported(question: str, message: str, match: matcher.Match | None = None) -> dict[str, Any]:
    closest = []
    if match is not None:
        closest = [{"intent": i, "title": BY_ID[i].title, "example": BY_ID[i].examples[0]}
                   for i, _ in match.ranked[:5] if i not in ("action_request", "out_of_scope")][:3]
    return {"supported": False, "question": question, "answer": message, "closest": closest,
            "supported_questions": supported_questions(),
            "matcher": match.matcher if match else None, "confidence": match.score if match else None,
            "matcher_note": _matcher_note(match) if match else None}


def _matcher_note(match: matcher.Match) -> str | None:
    if match.matcher == "keyword":
        return f"Matched by keywords, because the language model is unavailable: {match.fallback_reason}."
    return None


def ask(session: Session, question: str, *, today: date | None = None, force_keywords: bool = False) -> dict[str, Any]:
    settings = get_settings()
    today = today or date.today()
    question = re.sub(r"\s+", " ", question or "").strip()

    if len(question) < 3:
        return _unsupported(question, "Please type a question.")
    if len(question) > settings.assistant_max_chars:
        return _unsupported(question, f"That question is too long. Please keep it under {settings.assistant_max_chars} characters.")
    if params.looks_like_sql(question):
        log.info("refused SQL-shaped input")
        return _unsupported(question, "That looks like a database command, not a question. InsightAI does not run SQL: "
                                      "it only answers the business questions listed below.")

    scope = queries.Scope(session.client_id, session.org_ids)
    products, partners = _entities(scope)
    generic, product, partner, eligible = prepare(question, products, partners)
    match = matcher.match(generic, eligible=eligible, force_keywords=force_keywords)

    if match.intent_id is None:
        return _unsupported(question, "That isn't one of the questions InsightAI can answer from ADempiere data.", match)

    intent = BY_ID[match.intent_id]
    entities = {"product": product, "bpartner": partner}
    for name in intent.requires:
        if entities[name] is None:
            kind, pool = ("product", products) if name == "product" else ("customer or supplier", partners)
            samples = ", ".join(sorted(p["name"].strip() for p in pool)[:5])
            response = _unsupported(question, f"I read that as \"{intent.title}\", but couldn't find a {kind} name in the question "
                                              f"that exists in ADempiere. For example: {samples}.", match)
            response["intent"], response["title"] = intent.id, intent.title
            return response

    period = params.parse_period(question, today) if "period" in intent.uses else None
    top_n, top_n_stated = params.parse_top_n(question, settings.assistant_default_top_n, settings.assistant_max_top_n)
    context = Context(
        scope=scope, currency=session.currency, today=today, settings=settings,
        period=period or params.default_period(today, settings.default_months),
        top_n=top_n, top_n_stated=top_n_stated,
        product=product if "product" in intent.uses else None,
        bpartner=partner if "bpartner" in intent.uses else None,
    )
    result = intent.handler(context)

    understood: list[str] = []
    notes = list(result["notes"])
    if "period" in intent.uses:
        understood.append(f"Period: {context.period.start.isoformat()} to {context.period.end.isoformat()}")
        if not context.period.stated:
            notes.insert(0, f"No period was given, so {context.period.label} were used.")
    elif params.parse_period(question, today) is not None and intent.id != "action_request":
        notes.insert(0, "This is a position as of today; the period in the question does not apply.")
    if "top_n" in intent.uses:
        understood.append(f"Top {context.top_n}" + ("" if top_n_stated else " (default)"))
    for name, label in (("product", "Product"), ("bpartner", "Business partner")):
        entity = getattr(context, name)
        if entity is not None:
            understood.append(f"{label}: {entity.name}")
            if not entity.exact:
                notes.insert(0, f"\"{entity.matched_text}\" was read as {entity.name}.")
    for name, entity, kind in (("product", product, "product"), ("bpartner", partner, "business partner")):
        if entity is not None and name not in intent.uses and intent.id != "action_request":
            notes.insert(0, f"The {kind} named in the question ({entity.name}) is not used in this answer.")
    understood.append(f"Organisations: {len(scope.org_ids)} your role can access")

    return {
        "supported": True, "question": question, "intent": intent.id, "title": intent.title,
        "confidence": match.score, "matcher": match.matcher, "matcher_note": _matcher_note(match),
        "answer": result["answer"], "understood": understood,
        "columns": result["columns"], "rows": result["rows"], "chart": result["chart"],
        "basis": result["basis"], "notes": notes, "currency": session.currency,
    }
