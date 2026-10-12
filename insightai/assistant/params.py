"""Deterministic parameter extraction: periods, top-N, and names checked against the database."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from datetime import date, timedelta

NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "fifty": 50}
MONTHS = {name: i for i, name in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"], start=1)}
MONTHS.update({"jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12})
_NUMBER = r"(\d{1,4}|" + "|".join(NUMBER_WORDS) + ")"
_COMPANY_SUFFIXES = {"inc", "llc", "ltd", "co", "corp", "company", "gmbh", "limited"}


def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9#&]+", " ", text.lower())).strip()


def _to_int(token: str) -> int:
    return int(token) if token.isdigit() else NUMBER_WORDS[token]


# ---- unsafe input ---------------------------------------------------------------------

_SQL_SHAPES = [
    r";",                                                         # statement separators
    r"--|/\*|\*/",                                                # SQL comments
    r"\b(select|insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|execute|union)\b\b.{0,40}\b(from|into|table|set|database|schema|role)\b",
    r"\b(pg_|information_schema|adempiere\.)",
]


def looks_like_sql(question: str) -> bool:
    """True when the text is shaped like SQL rather than a question. Such input is refused outright."""
    lowered = question.lower()
    return any(re.search(pattern, lowered) for pattern in _SQL_SHAPES)


# ---- periods --------------------------------------------------------------------------

@dataclass(frozen=True)
class Period:
    start: date
    end: date
    label: str
    stated: bool = True     # False when the question gave no period and the default was used


def _month_range(year: int, month: int) -> tuple[date, date]:
    first = date(year, month, 1)
    following = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return first, following - timedelta(days=1)


def _shift_month(year: int, month: int, by: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + by
    return index // 12, index % 12 + 1


def _quarter_start(day: date) -> date:
    return date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)


def parse_period(question: str, today: date) -> Period | None:
    """Find a period in the question. Returns None when none is mentioned."""
    q = normalise(question)

    if re.search(r"\b(all time|ever|overall|in total so far|since the beginning)\b", q):
        return Period(date(2000, 1, 1), today, "all time")
    if re.search(r"\b(year to date|ytd|this year|current year|so far this year)\b", q):
        return Period(date(today.year, 1, 1), today, "this year so far")
    if re.search(r"\b(last|previous|prior) year\b", q):
        return Period(date(today.year - 1, 1, 1), date(today.year - 1, 12, 31), "last year")
    if re.search(r"\b(this|current) quarter\b", q):
        return Period(_quarter_start(today), today, "this quarter so far")
    if re.search(r"\b(last|previous|prior) quarter\b", q):
        end = _quarter_start(today) - timedelta(days=1)
        return Period(_quarter_start(end), end, "last quarter")
    if re.search(r"\b(this|current) month\b", q):
        return Period(date(today.year, today.month, 1), today, "this month so far")
    if re.search(r"\b(last|previous|prior) month\b", q):
        start, end = _month_range(*_shift_month(today.year, today.month, -1))
        return Period(start, end, "last month")
    if re.search(r"\b(this|current) week\b", q):
        return Period(today - timedelta(days=today.weekday()), today, "this week so far")
    if re.search(r"\b(last|previous|prior) week\b", q):
        start = today - timedelta(days=today.weekday() + 7)
        return Period(start, start + timedelta(days=6), "last week")

    m = re.search(rf"\b(?:last|past|previous|prior)\s+{_NUMBER}\s+(day|week|month|year)s?\b", q)
    if m:
        count, unit = _to_int(m.group(1)), m.group(2)
        if count < 1:
            return None
        if unit == "day":
            start = today - timedelta(days=count)
        elif unit == "week":
            start = today - timedelta(weeks=count)
        elif unit == "month":
            year, month = _shift_month(today.year, today.month, -count)
            start = date(year, month, min(today.day, _month_range(year, month)[1].day))
        else:
            start = date(today.year - count, today.month, min(today.day, 28))
        return Period(start, today, f"the last {count} {unit}{'s' if count != 1 else ''}")

    month_names = "|".join(sorted(MONTHS, key=len, reverse=True))
    m = re.search(rf"\bsince\s+({month_names})(?:\s+(\d{{4}}))?\b", q)
    if m:
        month = MONTHS[m.group(1)]
        year = int(m.group(2)) if m.group(2) else (today.year if month <= today.month else today.year - 1)
        start = date(year, month, 1)
        return Period(start, today, f"since {start:%B %Y}")
    m = re.search(r"\bsince\s+(\d{4})\b", q)
    if m and 2000 <= int(m.group(1)) <= today.year:
        return Period(date(int(m.group(1)), 1, 1), today, f"since {m.group(1)}")

    m = re.search(rf"\b(?:in|during|for|of)\s+({month_names})(?:\s+(\d{{4}}))?\b", q)
    if m:
        month = MONTHS[m.group(1)]
        year = int(m.group(2)) if m.group(2) else (today.year if month <= today.month else today.year - 1)
        start, end = _month_range(year, month)
        return Period(start, min(end, today), f"{start:%B %Y}")
    m = re.search(r"\b(?:in|during|for|of)\s+(\d{4})\b", q)
    if m and 2000 <= int(m.group(1)) <= today.year:
        year = int(m.group(1))
        return Period(date(year, 1, 1), min(date(year, 12, 31), today), str(year))
    return None


def default_period(today: date, months: int) -> Period:
    year, month = _shift_month(today.year, today.month, -(months - 1))
    return Period(date(year, month, 1), today, f"the last {months} months", stated=False)


def previous_period(period: Period) -> Period:
    days = (period.end - period.start).days
    end = period.start - timedelta(days=1)
    return Period(end - timedelta(days=days), end, "the preceding period of equal length")


# ---- top N ----------------------------------------------------------------------------

def parse_top_n(question: str, default: int, maximum: int) -> tuple[int, bool]:
    """Returns (n, whether the question stated it). n is clamped to 1..maximum."""
    q = normalise(question)
    m = (re.search(rf"\b(?:top|first|best|biggest|largest|worst|bottom)\s+{_NUMBER}\b", q)
         or re.search(rf"\b{_NUMBER}\s+(?:top|best|biggest|largest|worst|most|longest|slowest)\b", q))
    if not m:
        return default, False
    return max(1, min(_to_int(m.group(1)), maximum)), True


# ---- names checked against the database ---------------------------------------------------

@dataclass(frozen=True)
class Entity:
    id: int
    name: str
    matched_text: str      # the words in the question that matched
    exact: bool            # False when found by close spelling rather than an exact phrase


def _variants(name: str) -> set[str]:
    """Ways a name may be typed: as stored, and without a trailing company suffix ("Seed Farm Inc." -> "seed farm")."""
    full = normalise(name)
    out = {full}
    words = full.split()
    while len(words) > 1 and words[-1] in _COMPANY_SUFFIXES:
        words = words[:-1]
        out.add(" ".join(words))
    return {v for v in out if len(v) >= 3}


def _exact(question: str, candidates: list[dict]) -> Entity | None:
    q = f" {normalise(question)} "
    best: tuple[int, dict, str] | None = None
    for candidate in candidates:
        for variant in _variants(candidate["name"]):
            if f" {variant} " in q and (best is None or len(variant) > best[0]):
                best = (len(variant), candidate, variant)
    return Entity(int(best[1]["id"]), best[1]["name"].strip(), best[2], True) if best else None


def _close(question: str, candidates: list[dict]) -> Entity | None:
    words = normalise(question).split()
    lookup = {variant: c for c in candidates for variant in _variants(c["name"])}
    for size in (4, 3, 2, 1):
        for i in range(len(words) - size + 1):
            phrase = " ".join(words[i:i + size])
            if len(phrase) < 5 or "|" in phrase:
                continue
            close = difflib.get_close_matches(phrase, lookup, n=1, cutoff=0.85)
            if close:
                candidate = lookup[close[0]]
                return Entity(int(candidate["id"]), candidate["name"].strip(), phrase, False)
    return None


def find_entities(question: str, products: list[dict], partners: list[dict]) -> tuple[Entity | None, Entity | None]:
    """Which product and which business partner the question names, if any.

    Exact phrases are found first, longest first. Close spellings (difflib ratio 0.85 or more) are
    then looked for only in the words no exact match used, so "Patio Sun Screen" (a product) is not
    also read as the customer "Patio Fun". A close match is reported as inexact so the answer can say so.
    """
    product, partner = _exact(question, products), _exact(question, partners)
    remaining = f" {normalise(question)} "
    for entity in (product, partner):
        if entity is not None:
            remaining = remaining.replace(f" {entity.matched_text} ", " | ", 1)
    if product is None:
        product = _close(remaining, products)
        if product is not None:
            remaining = remaining.replace(f" {product.matched_text} ", " | ", 1)
    if partner is None:
        partner = _close(remaining, partners)
    return product, partner
