"""시간·횟수·승차의 공통 표본과 도착 정류장 연결에서 결측·반복 방문을 검증한다."""

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
model = importlib.import_module("gangnam.overnight_mechanism")


def test_count_panel_preserves_known_zero_but_excludes_revisited_stop():
    d = pd.DataFrame({"date": ["a", "b", "b", "c"], "route": ["r"] * 4, "stop": ["s"] * 4,
                      "sequence": [1, 1, 2, 1], "h17": [0., 2., 3., np.nan]})
    result, repeated = model.count_panel(d, [17], "trips", {"s"})
    assert repeated == 2 and result.date.tolist() == ["a", "c"]
    assert result.trips.iloc[0] == 0. and np.isnan(result.trips.iloc[1])


def test_full_grid_keeps_count_on_missing_time_day_and_masks_all_indexes():
    cell = {"group": "g", "route": "r", "stop": "a", "arrival": "b", "hour": 17}
    panel = pd.DataFrame([{**cell, "date": "2024-05-20", "value": 10.}])
    selected = pd.DataFrame([{**cell, "baseline_2023": 10., "baseline_2024": 10.,
                               "trips_baseline_2023": 2., "trips_baseline_2024": 2.,
                               "boardings_baseline_2023": 3., "boardings_baseline_2024": 3.}])
    dates = ["2024-05-20", "2024-05-21"]
    counts = {name: pd.DataFrame({"date": dates, "route": ["r"] * 2, "count_stop": ["b"] * 2,
                                  "hour": [17] * 2, name: values}) for name, values in [("trips", [0., 2.]), ("boardings", [3., 6.])]}
    grid = model.joint_grid(panel, selected, counts, dates, "arrival")
    assert grid.loc[grid.date.eq(dates[1]), "trips"].iloc[0] == 2.
    result = model.indexes(grid, selected).set_index("date")
    assert result.loc[dates[0], "trips_index"] == 0.
    assert result.loc[dates[0], "time_index"] == 100.
    assert result.loc[dates[1], ["time_index", "trips_index", "boardings_index"]].isna().all()
