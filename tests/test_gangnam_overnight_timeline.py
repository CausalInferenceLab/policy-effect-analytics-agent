"""장기 버스 궤적의 결측 주 보존과 제한된 수준 분할 계산을 검증한다."""

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
module = importlib.import_module("gangnam.overnight_timeline")


def test_weekly_quality_keeps_absent_expected_days_and_short_holiday_weeks():
    dates = ["2024-05-20", "2024-05-21", "2024-05-22", "2024-05-23", "2024-05-24", "2024-05-27", "2024-05-28"]
    frame = pd.DataFrame({"date": dates, "aggregation": "equal_cells", "group": "segment", "index": [100, 100, 100, np.nan, np.nan, 100, 100], "coverage": [1, 1, 1, 0, 0, 1, 1]})
    result = module.weekly_table(frame, {"minimum_valid_days": 3, "minimum_expected_day_coverage": .8})
    assert result.expected_days.tolist() == [5, 2] and result.valid_days.tolist() == [3, 2]
    assert not result.quality_pass.any() and result["index"].isna().all()
    frame.loc[3, ["index", "coverage"]] = [100, 1]
    result = module.weekly_table(frame, {"minimum_valid_days": 3, "minimum_expected_day_coverage": .8})
    assert result.quality_pass.tolist() == [True, False]


def test_two_level_fit_finds_known_step_without_interpolating_missing_week():
    weeks = pd.date_range("2024-01-01", periods=20, freq="W-MON").strftime("%Y-%m-%d")
    frame = pd.DataFrame({"week_start": weeks, "index": [100.] * 10 + [50.] * 10})
    cfg = {"minimum_weeks_each_side": 8, "minimum_observed_week_fraction": .8}
    result = module.single_level_change(frame, cfg)
    assert result["split_week"] == weeks[10] and result["geometric_change_pct"] == pytest.approx(-50)
    assert result["sse_reduction_fraction"] == pytest.approx(1)
    frame.loc[9, "index"] = np.nan
    result = module.single_level_change(frame, cfg)
    assert result["observed_weeks"] == 19 and result["last_pre_observed_week"] == weeks[8]
    frame.loc[:5, "index"] = np.nan
    assert module.single_level_change(frame, cfg)["status"] == "insufficient"


def test_constant_series_and_invalid_logs_are_not_invented_changes():
    frame = pd.DataFrame({"week_start": pd.date_range("2024-01-01", periods=20, freq="W-MON").strftime("%Y-%m-%d"), "index": 100.})
    cfg = {"minimum_weeks_each_side": 8, "minimum_observed_week_fraction": .8}
    result = module.single_level_change(frame, cfg)
    assert result["status"] == "constant" and result["split_week"] is None
    frame.loc[0, "index"] = 0
    with pytest.raises(ValueError, match="양수"):
        module.single_level_change(frame, cfg)
