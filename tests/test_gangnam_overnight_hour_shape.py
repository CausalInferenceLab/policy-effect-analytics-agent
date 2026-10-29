"""모든 시간의 공동 관측과 사후 값에 독립적인 노선 선택을 검증한다."""

import importlib
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
module = importlib.import_module("gangnam.overnight_hour_shape")


def test_missing_hour_invalidates_route_day_and_selection_ignores_future():
    dates = ["2023-06-01", "2024-06-01", "2024-07-01"]
    rows = pd.DataFrame([{"date": day, "route": route, "hour": hour, "value": 10.}
                         for day in dates for route in ["a", "b"] for hour in [7, 17]])
    rows.loc[rows.date.eq(dates[0]) & rows.route.eq("b") & rows.hour.eq(7), "value"] = 0
    matrix, joint = module.joint_hours(rows, ["a", "b"], [7, 17], dates)
    assert matrix.loc[(dates[0], "b")].isna().all()
    ref = {"pre2023": [dates[0]], "pre2024": [dates[1]]}
    support, baseline, normalized = module.select_routes(matrix, joint, ref, .8)
    assert support.loc[support.eligible, "route"].tolist() == ["a"]
    assert normalized.eq(100).all().all()
    future = rows[~(rows.date.eq(dates[2]) & rows.route.eq("a") & rows.hour.eq(7))]
    changed, mask = module.joint_hours(future, ["a", "b"], [7, 17], dates)
    other_support, other_baseline, altered = module.select_routes(changed, mask, ref, .8)
    pd.testing.assert_frame_equal(support, other_support)
    pd.testing.assert_frame_equal(baseline, other_baseline)
    daily = module.daily_profile(altered, 1, dates, .8)
    assert daily[daily.date.eq(dates[2])]["index"].isna().all()
    assert daily[daily.date.eq(dates[2])].coverage.eq(0).all()


def test_zero_eligible_routes_stays_missing_and_duplicate_keys_rejected():
    rows = pd.DataFrame([{"date": "2024-06-01", "route": "a", "hour": 7, "value": 0.}])
    matrix, joint = module.joint_hours(rows, ["a"], [7, 17], ["2024-06-01"])
    support, baseline, normalized = module.select_routes(matrix, joint, {"pre2024": ["2024-06-01"]}, .8)
    assert not support.eligible.any() and baseline.empty
    daily = module.daily_profile(normalized, 0, ["2024-06-01"], .8)
    assert daily["index"].isna().all() and daily.coverage.eq(0).all()
    with pytest.raises(ValueError, match="중복"):
        module.joint_hours(pd.concat([rows, rows]), ["a"], [7, 17], ["2024-06-01"])
