"""휴일·주말의 상호 배타 분류와 같은 주 전체의 짝 제외를 확인한다."""

import importlib
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
module = importlib.import_module("gangnam.overnight_confirmation_review")


def test_public_holiday_has_priority_over_weekend_and_timezone_is_required():
    times = pd.Series(pd.to_datetime(["2025-10-05", "2025-10-11", "2025-10-10"]).tz_localize("Asia/Seoul"))
    assert module.calendar_groups(times, {times.iloc[0].date()}).tolist() == ["public_holiday", "nonholiday_weekend", "nonholiday_weekday"]
    with pytest.raises(ValueError, match="서울"):
        module.week_labels(times.dt.tz_convert("UTC"))


def test_leave_week_removes_all_link_hours_and_preserves_pair_alignment():
    time = pd.to_datetime(["2025-09-01", "2025-09-02", "2025-09-08"]).tz_localize("Asia/Seoul")
    left = pd.DataFrame({"link_id": ["a", "a", "a"], "target_start": time, "speed_kmh": [10., 10., 10.],
                         "q10": [9., 9., 9.], "q50": [10., 10., 10.], "q90": [11., 11., 11.]})
    right = left.copy()
    right.loc[:1, "q90"] = 13.
    right.loc[2, "q90"] = 15.
    result, weekly = module.leave_week_out(left, right.iloc[::-1])
    assert result.set_index("omitted_week").loc["2025-09-01", "remaining_rows"] == 1
    assert result.set_index("omitted_week").loc["2025-09-01", "difference"] == -4
    assert result.set_index("omitted_week").loc["2025-09-08", "difference"] == -2
    assert weekly.rows.tolist() == [2, 1]
