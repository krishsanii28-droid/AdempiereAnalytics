"""Forecasting tests. The pure-function tests need no database or model; the last group runs the
job against the live database with the model switched off, which is the fallback path."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from insightai import db
from insightai.config import get_settings
from insightai.forecast import baselines, job, model, risk, synthetic
from insightai.forecast.series import flag_outliers, last_complete_week, week_start, weekly_series
from insightai.main import app

MONDAY = date(2026, 10, 12)


# ---- weekly series ----------------------------------------------------------------------

def test_weeks_start_on_monday_and_the_current_week_is_left_out():
    assert week_start(date(2026, 10, 14)) == MONDAY
    assert last_complete_week(date(2026, 10, 14)) == date(2026, 10, 5)
    start, values, _ = weekly_series([(date(2026, 9, 21), 5), (date(2026, 10, 13), 99)], today=date(2026, 10, 14))
    assert start == date(2026, 9, 21)
    assert values == [5, 0, 0]          # weeks of 21 Sep, 28 Sep, 5 Oct; the unfinished week of 12 Oct is excluded


def test_missing_weeks_are_zero_and_same_week_rows_are_summed():
    _, values, _ = weekly_series([(date(2026, 9, 1), 2), (date(2026, 9, 3), 3), (date(2026, 9, 22), 4)], today=MONDAY)
    assert values == [5, 0, 0, 4, 0, 0]


def test_net_negative_weeks_are_clipped_and_counted():
    _, values, clipped = weekly_series([(date(2026, 9, 1), 5), (date(2026, 9, 8), -3)], today=MONDAY)
    assert values[:2] == [5, 0] and clipped == 1


def test_no_rows_gives_an_empty_series():
    assert weekly_series([], today=MONDAY) == (None, [], 0)


def test_outliers_are_flagged_without_flagging_ordinary_weeks():
    values = [10, 11, 9, 10, 12, 10, 9, 11, 60, 10, 0, 0]
    assert flag_outliers(values) == [8]
    assert flag_outliers([5] * 20) == []       # no variation: nothing to flag
    assert flag_outliers([1, 50]) == []        # too short to judge


# ---- baselines and metrics --------------------------------------------------------------

def test_baseline_forecasts():
    history = list(range(1, 105))              # 104 weeks
    assert baselines.naive(history, 3) == [104, 104, 104]
    assert baselines.moving_average(history, 2, window=4) == [102.5, 102.5]
    assert baselines.seasonal_naive(history, 3) == [53, 54, 55]


def test_baseline_choice_follows_available_history():
    assert baselines.choose_baseline([1.0] * 104, window=8) == "seasonal_naive"
    assert baselines.choose_baseline([1.0] * 103, window=8) == "moving_average"
    assert baselines.choose_baseline([1.0] * 5, window=8) == "naive"


def test_mae_and_mase():
    assert baselines.mae([10, 20], [12, 17]) == pytest.approx(2.5)
    training = [10, 12, 11, 15]                # in-sample naive errors 2, 1, 4 -> scale 7/3
    assert baselines.mase([10, 20], [12, 17], training) == pytest.approx(2.5 / (7 / 3))
    assert baselines.mase([1, 1], [1, 1], [5, 5, 5]) is None     # flat training series has no scale


def test_baseline_quantiles_are_ordered_and_never_negative():
    history = [0, 4, 0, 6, 1, 0, 9, 2, 0, 5, 3, 0, 7, 1, 0, 4] * 2
    _, forecast = baselines.baseline_quantiles(history, 4, 8, [0.1, 0.5, 0.9])
    for week in range(4):
        assert 0 <= forecast[0.1][week] <= forecast[0.5][week] <= forecast[0.9][week]


# ---- risk -------------------------------------------------------------------------------

FORECAST = {0.1: [5, 5, 5, 5], 0.5: [10, 10, 10, 10], 0.9: [20, 20, 20, 20]}     # totals 20 / 40 / 80


@pytest.mark.parametrize("available, incoming, level", [
    (30, 0, "high"),        # below the median total of 40
    (30, 10, "medium"),     # 40 covers the median but not the 90th percentile
    (50, 40, "low"),        # 90 covers the 90th percentile
])
def test_risk_levels(available, incoming, level):
    assert risk.assess(available, incoming, FORECAST, 26)["level"] == level


def test_incoming_stock_reduces_risk():
    without = risk.assess(30, 0, FORECAST, 26)
    with_po = risk.assess(30, 60, FORECAST, 26)
    assert with_po["stockout_probability"] < without["stockout_probability"]
    assert without["stockout_week"] == 4 and with_po["stockout_week"] is None


def test_probability_is_interpolated_and_bounded():
    assert risk.assess(40, 0, FORECAST, 26)["stockout_probability"] == pytest.approx(0.5)
    assert risk.assess(60, 0, FORECAST, 26)["stockout_probability"] == pytest.approx(0.3)
    assert risk.assess(10, 0, FORECAST, 26)["stockout_probability_text"] == "over 90%"
    assert risk.assess(500, 0, FORECAST, 26)["stockout_probability_text"] == "under 10%"


def test_excess_and_no_demand():
    assert risk.assess(400, 0, FORECAST, 26)["excess"] is True          # 40 weeks of cover
    assert risk.assess(100, 0, FORECAST, 26)["excess"] is False         # 10 weeks
    flat = {0.1: [0, 0], 0.5: [0, 0], 0.9: [0, 0]}
    result = risk.assess(7, 0, flat, 26)
    assert result["level"] == "none" and result["excess"] is True and result["stockout_probability"] is None


# ---- synthetic data ---------------------------------------------------------------------

def test_synthetic_series_are_repeatable_and_valid():
    first = synthetic.generate_series(1, 100, 200, 50, 156)
    assert first == synthetic.generate_series(1, 100, 200, 50, 156)
    assert first != synthetic.generate_series(2, 100, 200, 50, 156)
    assert len(first[1]) == 156 and min(first[1]) >= 0 and first[0] in synthetic.PROFILES


# ---- fallback and labelling, against the live database -----------------------------------

def test_missing_model_reports_a_reason_instead_of_raising(tmp_path):
    forecaster, reason = model.load("amazon/this-model-does-not-exist", tmp_path)
    assert forecaster is None and "could not be downloaded" in reason


@pytest.fixture(scope="module")
def client_id() -> int:
    return db.query_one("SELECT MIN(ad_client_id)::int AS id FROM v_org")["id"]


def test_without_a_model_the_baseline_is_used_and_said_so(client_id):
    result = job.build(client_id, "synthetic", None, "model switched off for this test")
    assert result["synthetic"] is True and result["model"]["used"] == "baseline"
    assert result["model"]["fallback_reason"] == "model switched off for this test"
    assert result["evaluation"]["model"] is None and result["evaluation"]["baselines"]
    forecast = [x for x in result["series"] if x["status"] == "forecast"]
    assert forecast and all(x["method"] in ("naive", "moving_average", "seasonal_naive") for x in forecast)
    assert all(x["risk"]["level"] in ("high", "medium", "low", "none") for x in forecast)
    assert result["assumptions"][0].startswith("SYNTHETIC DEMAND")


def test_real_mode_does_not_forecast_or_claim_accuracy_without_history(client_id):
    settings = get_settings()
    result = job.build(client_id, "real", None, "model switched off for this test")
    assert result["synthetic"] is False
    for x in result["series"]:
        weeks_with_demand = sum(1 for v in x["history"] if v > 0)
        enough = len(x["history"]) >= settings.min_history_weeks and weeks_with_demand >= settings.min_demand_weeks
        assert (x["status"] == "forecast") == enough
        if not enough:
            assert x["forecast"] is None and x["risk"]["level"] == "unknown" and x["risk"]["reason"]
    if result["counts"]["forecast"] == 0:
        assert result["evaluation"]["baselines"] == {} and result["evaluation"]["reason"]


def test_forecast_api_labels_modes_and_respects_organisations():
    def login(user, role):
        row = db.query_one("SELECT ad_user_id::int AS uid, ad_role_id::int AS rid FROM v_user_role "
                           "WHERE user_name = %(u)s AND role_name = %(r)s", {"u": user, "r": role})
        if not row:
            pytest.skip(f"{user} / {role} not present")
        client = TestClient(app, follow_redirects=False)
        client.get("/dev/login", params={"user_id": row["uid"], "role_id": row["rid"]})
        return client

    admin, restricted = login("GardenAdmin", "GardenWorld Admin"), login("test_salerep", "SalesRep(Restricted)")
    assert TestClient(app).get("/api/forecast").status_code == 401
    assert admin.get("/api/forecast", params={"mode": "anything"}).status_code == 422

    real, demo = admin.get("/api/forecast").json(), admin.get("/api/forecast", params={"mode": "synthetic"}).json()
    if not (real["available"] and demo["available"]):
        pytest.skip("forecast files not generated; run python -m insightai.forecast")
    assert real["synthetic"] is False and demo["synthetic"] is True

    own_warehouses = {w["id"] for w in restricted.get("/api/me").json()["filters"]["warehouses"]}
    mine = restricted.get("/api/forecast", params={"mode": "synthetic"}).json()["rows"]
    assert mine and {r["warehouse_id"] for r in mine} <= own_warehouses
    assert len(mine) < len(demo["rows"])

    other = next(r for r in demo["rows"] if r["warehouse_id"] not in own_warehouses)
    params = {"mode": "synthetic", "product_id": other["product_id"], "warehouse_id": other["warehouse_id"]}
    assert restricted.get("/api/forecast/series", params=params).status_code == 404
    series = admin.get("/api/forecast/series", params=params).json()
    assert series["synthetic"] is True and len(series["forecast"]["0.5"]) == demo["horizon_weeks"]

    # The KPI card among the real figures must come from real data only
    card = next(c for c in admin.get("/api/kpis").json()["cards"] if c["id"] == "stockout_risk")
    assert card["available"] == (real["counts"]["forecast"] > 0)
