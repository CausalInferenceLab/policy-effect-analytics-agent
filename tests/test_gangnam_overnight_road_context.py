"""도로의 사전 고정과 길이 관측률이 사후 누락에 의해 바뀌지 않는지 검증한다."""

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
road = importlib.import_module("gangnam.overnight_road_context")


def test_extra_weekday_column_does_not_shift_hours():
    metadata = ["일자", "요일", "요일(2)", "지점명", "지점번호", "방향", "구분"]
    hours = [f"{h}시" for h in range(24)]
    road.validate_volume_header(metadata + hours)
    with pytest.raises(ValueError, match="헤더 변경"):
        road.validate_volume_header(metadata + hours[1:] + ["24시"])


def test_fixed_selection_and_length_coverage():
    data = pd.DataFrame([
        (date, link, 17, length, value)
        for date in ["2023-05-22", "2024-05-20", "2024-07-08"]
        for link, length, value in [("a", 100, 10.0), ("b", 300, np.nan if date == "2024-07-08" else 30.0)]
    ], columns=["date", "link_id", "hour", "length", "speed_kmh"])
    periods = {"pre2023": ["2023-05-22"], "pre2024": ["2024-05-20"]}
    chosen = road.select_speed(data, periods, .8)
    assert set(chosen.link_id) == {"a", "b"}
    daily = road.speed_daily(data, chosen, ["2024-05-20", "2024-07-08", "2024-07-09"], "fixed_length_arithmetic", .8).set_index("date")
    assert daily.loc["2024-05-20", "index"] == pytest.approx(25)
    assert daily.loc["2024-07-08", "coverage"] == pytest.approx(.25)
    assert np.isnan(daily.loc["2024-07-08", "index"])
    assert daily.loc["2024-07-09", "coverage"] == 0
    equal = road.speed_daily(data, chosen, ["2024-05-20"], "equal_cells", .8)
    assert equal.iloc[0]["index"] == pytest.approx(20)
