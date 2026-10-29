"""폐선 구성 비교에서 날짜 선택과 0·행 부재·원본 부재를 구분한다."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
from gangnam.deepening_cohort import (
    STATES,
    accepted_dates_only,
    count_records,
    monthly_states,
    record_grid,
)


def test_fixed_dates_do_not_hide_new_coverage_or_accept_new_days():
    original = pd.DataFrame({"date": ["2024-07-08", "2024-07-09"], "segment": ["south"] * 2,
                             "index": [90., np.nan], "coverage": [12 / 14, 11 / 14]})
    native = original.assign(index=[88., 89.], coverage=[11 / 13, 11 / 13])
    result = accepted_dates_only(native, original)
    assert result["index"].iloc[0] == 88 and pd.isna(result["index"].iloc[1])
    assert result.coverage.tolist() == [11 / 13, 11 / 13]
    with pytest.raises(ValueError, match="원래 분석에 없는"):
        accepted_dates_only(native.assign(date=["2024-07-08", "2024-07-10"]), original)


def test_repeat_stop_counts_are_quarantined_and_zero_survives():
    wide = pd.DataFrame({"date": ["2024-07-08"] * 3, "route": ["r"] * 3,
                         "stop": ["revisit", "revisit", "valid"], "sequence": [1, 9, 2],
                         "h17": [1., 2., 0.], "h18": [1., 2., np.nan]})
    result, repeated = count_records(wide, [17, 18])
    assert repeated == 2 and set(result.stop) == {"valid"}
    assert result.trip_status.tolist() == ["zero", "blank"]


def test_count_support_separates_zero_unknown_and_source_absence():
    days = ["2024-07-08", "2024-07-09", "2024-07-10"]
    legs = pd.DataFrame([{"segment": "south", "stop": "s1", "arrival": "s2"},
                         {"segment": "north", "stop": "n1", "arrival": "n2"}])
    panel = legs.assign(date=days[0], route="r", hour=17, raw_value=10., record_status="positive")
    counts = pd.DataFrame({"date": [days[0]] * 3, "route": ["r"] * 3, "hour": [17] * 3,
                           "stop": ["s1", "s2", "n1"], "trip_value": [0., 1., 2.],
                           "trip_status": ["zero", "positive", "positive"]})
    grid = record_grid(panel, counts, ["r"], [17], days, legs,
                       {"bus_time": set(days[:2]), "bus_trips": set(days[:2])})
    first = grid[grid.date.eq(days[0])].set_index("segment")
    assert first.loc["south", "count_support"] == "both_known_at_least_one_zero"
    assert first.loc["north", "count_support"] == "at_least_one_unknown_or_invalid"
    assert grid[grid.date.eq(days[1])].record_status.eq("row_absent").all()
    assert grid[grid.date.eq(days[2])].record_status.eq("source_date_absent").all()
    monthly = monthly_states(grid)
    assert len(monthly) == 6 and monthly.expected_cell_days.eq(3).all()
    assert monthly[STATES].sum(axis=1).eq(monthly.expected_cell_days).all()
