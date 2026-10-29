"""양방향의 동일 노선·날짜 선택, 고정 누락 분모, 공동 주 재표집을 검증한다."""

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
module = importlib.import_module("gangnam.overnight_matched_directions")


def test_one_missing_direction_hour_removes_both_and_preserves_future_denominator():
    dates = ["2023-06-01", "2024-06-01", "2024-07-01"]
    rows = pd.DataFrame([{"date": day, "route": route, "segment": segment, "hour": hour, "value": 10.}
                         for day in dates for route in ["a", "b"] for segment in ["south", "north"] for hour in [7, 17]])
    reference = {"pre2023": [dates[0]], "pre2024": [dates[1]]}
    matrix, joint = module.joint_directions(rows, ["a", "b"], [7, 17], dates)
    support, baseline, _ = module.select_routes(matrix, joint, reference, .8)
    rows.loc[rows.date.eq(dates[2]) & rows.route.eq("b") & rows.segment.eq("north") & rows.hour.eq(7), "value"] = np.nan
    changed, mask = module.joint_directions(rows, ["a", "b"], [7, 17], dates)
    assert changed.loc[(dates[2], "b")].isna().all()
    other_support, other_baseline, normalized = module.select_routes(changed, mask, reference, .8)
    pd.testing.assert_frame_equal(support, other_support)
    pd.testing.assert_frame_equal(baseline, other_baseline)
    daily = module.daily_paired(normalized, 2, dates, [17], .8)
    future = daily[daily.date.eq(dates[2])]
    assert future.coverage.eq(.5).all() and future["index"].isna().all()
    assert daily[~daily.date.eq(dates[2])]["index"].eq(100).all()


def test_joint_direction_key_validation_and_zero_are_not_missing_only_on_one_side():
    rows = pd.DataFrame([{"date": "2024-06-01", "route": "a", "segment": segment, "hour": 17, "value": value}
                         for segment, value in [("south", 10.), ("north", 0.)]])
    matrix, joint = module.joint_directions(rows, ["a"], [17], ["2024-06-01"])
    assert matrix.isna().all().all() and not joint.any()
    with pytest.raises(ValueError, match="중복"):
        module.joint_directions(pd.concat([rows, rows]), ["a"], [17], ["2024-06-01"])


def test_week_bootstrap_preserves_direction_pairing_and_input_order():
    before = pd.bdate_range("2024-05-01", periods=20).strftime("%Y-%m-%d").tolist()
    after = pd.bdate_range("2024-07-01", periods=20).strftime("%Y-%m-%d").tolist()
    rows = [{"date": day, "segment": segment, "index": (100 + 5 * index) * scale}
            for index, day in enumerate(before + after) for segment, scale in [("south", 1.), ("north", 2.)]]
    daily = pd.DataFrame(rows)
    result = module.paired_gap(daily, before, after, draws=200, seed=9)
    assert result["gap_percentage_points"] == pytest.approx(0, abs=1e-10)
    assert result["week_bootstrap_low"] == pytest.approx(0, abs=1e-10)
    assert result["week_bootstrap_high"] == pytest.approx(0, abs=1e-10)
    assert result == module.paired_gap(daily.sample(frac=1, random_state=2), before, after, draws=200, seed=9)
