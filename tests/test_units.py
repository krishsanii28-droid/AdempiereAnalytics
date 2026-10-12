"""Unit tests for logic that needs no database: query scoping, periods, session tokens, launch signatures."""
import hashlib
import hmac
import time
from datetime import date

import pytest

from insightai import auth, launch, main, queries
from insightai.queries import Filters, Scope

SCOPE = Scope(client_id=11, org_ids=(11, 50001))


def _filters(**overrides) -> Filters:
    values = dict(date_from=date(2026, 1, 1), date_to=date(2026, 3, 31), warehouse_id=None, category_id=None, bpartner_id=None)
    values.update(overrides)
    return Filters(**values)


# ---- every query is scoped to client and organisations -------------------------------------

def test_where_always_restricts_client_and_organisations():
    sql, params, ignored = queries._where(SCOPE, _filters(), dims=(), date_col=None)
    assert sql == "ad_client_id = %(client)s AND ad_org_id = ANY(%(orgs)s::numeric[])"
    assert params == {"client": 11, "orgs": [11, 50001]} and ignored == []


def test_where_applies_supported_filters_and_reports_the_rest():
    sql, params, ignored = queries._where(SCOPE, _filters(warehouse_id=103, category_id=5, bpartner_id=9),
                                          dims=("category", "bpartner"), date_col="date_invoiced", alias="l")
    assert "l.m_product_category_id = %(category)s" in sql and "l.c_bpartner_id = %(bpartner)s" in sql
    assert "m_warehouse_id" not in sql and ignored == ["warehouse"]
    assert "l.date_invoiced BETWEEN %(date_from)s AND %(date_to)s" in sql
    assert params["category"] == 5 and params["bpartner"] == 9 and "warehouse" not in params
    assert sql.startswith("l.ad_client_id = %(client)s AND l.ad_org_id = ANY(%(orgs)s::numeric[])")


def test_filter_values_never_appear_in_the_sql_text():
    sql, _, _ = queries._where(SCOPE, _filters(warehouse_id=123456, category_id=654321, bpartner_id=777777),
                               dims=("warehouse", "category", "bpartner"), date_col="movement_date")
    for value in ("123456", "654321", "777777", "2026", "50001"):
        assert value not in sql


# ---- periods -------------------------------------------------------------------------------

def test_previous_period_has_equal_length_and_ends_the_day_before():
    previous = queries._previous(_filters())                    # 1 Jan to 31 Mar 2026 = 90 days
    assert (previous.date_to, previous.date_from) == (date(2025, 12, 31), date(2025, 10, 3))
    assert (previous.date_to - previous.date_from) == (date(2026, 3, 31) - date(2026, 1, 1))
    one_day = queries._previous(_filters(date_from=date(2026, 5, 5), date_to=date(2026, 5, 5)))
    assert (one_day.date_from, one_day.date_to) == (date(2026, 5, 4), date(2026, 5, 4))


def test_previous_period_keeps_the_other_filters():
    previous = queries._previous(_filters(warehouse_id=1, category_id=2, bpartner_id=3))
    assert (previous.warehouse_id, previous.category_id, previous.bpartner_id) == (1, 2, 3)


def test_months_between_dates_crosses_year_ends():
    assert queries._months(date(2025, 11, 20), date(2026, 2, 3)) == ["2025-11", "2025-12", "2026-01", "2026-02"]
    assert queries._months(date(2026, 7, 31), date(2026, 7, 1)) == ["2026-07"]


@pytest.mark.parametrize("today, expected", [
    (date(2026, 10, 12), date(2025, 11, 1)),
    (date(2026, 1, 31), date(2025, 2, 1)),
    (date(2026, 12, 1), date(2026, 1, 1)),
])
def test_default_range_is_twelve_calendar_months(today, expected):
    assert main._default_from(today) == expected


def test_every_chart_states_its_basis_and_whether_dates_apply():
    for name, (function, basis, uses_dates) in queries.CHARTS.items():
        assert callable(function) and len(basis) > 15 and isinstance(uses_dates, bool), name
    balances = {n for n, (_, _, uses_dates) in queries.CHARTS.items() if not uses_dates}
    assert {"receivables_aging", "inventory_by_warehouse", "slow_moving"} <= balances


# ---- session tokens ------------------------------------------------------------------------

def test_token_round_trip_and_rejection():
    token = auth.issue_token(101, 102, 60)
    assert auth.read_token(token) == (101, 102)
    payload, signature = token.split(".")
    assert auth.read_token(payload + "." + "A" * len(signature)) is None       # forged signature
    assert auth.read_token(payload) is None and auth.read_token("") is None    # malformed
    assert auth.read_token(auth.issue_token(101, 102, -5)) is None              # expired


def test_token_payload_cannot_be_swapped():
    admin, other = auth.issue_token(101, 102, 60), auth.issue_token(104, 1000000, 60)
    assert auth.read_token(other.split(".")[0] + "." + admin.split(".")[1]) is None


# ---- launch signatures ---------------------------------------------------------------------

def test_launch_signature_matches_the_documented_scheme():
    """The Java launcher computes the same thing: hex HMAC-SHA256 of "user:role:time:nonce"."""
    expected = hmac.new(b"k", b"101:102:1700000000:abcdef12", hashlib.sha256).hexdigest()
    assert launch.sign("k", 101, 102, 1700000000, "abcdef12") == expected
    assert launch.sign("k", 101, 103, 1700000000, "abcdef12") != expected
    assert launch.sign("other", 101, 102, 1700000000, "abcdef12") != expected


def test_launch_codes_expire_and_work_once(monkeypatch):
    launch._codes["live"] = (1, 2, time.time() + 30)
    launch._codes["stale"] = (1, 2, time.time() - 1)
    assert launch.redeem_code("stale") is None
    assert launch.redeem_code("live") == (1, 2)
    assert launch.redeem_code("live") is None
