"""2025년 운영 지수가 2024년 기준을 쓰고 서로 모순되는 횟수의 비율을 보류하는지 검사한다."""

import importlib
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
module = importlib.import_module("gangnam.overnight_operations_persistence")


def test_2025_uses_2024_fixed_baseline_and_joint_mask():
    selected = pd.DataFrame({"group": ["g"], "route": ["r"], "stop": ["a"], "arrival": ["b"], "hour": [17],
                             "baseline_2024": [10.], "trips_baseline_2024": [2.], "boardings_baseline_2024": [20.]})
    grid = pd.concat([selected[module.CELL].assign(date="2025-05-20", time=8., trips=2., boardings=30.),
                      selected[module.CELL].assign(date="2025-05-21", time=8., trips=2., boardings=float("nan"))])
    result = module.normalize_fixed(grid, selected)
    assert result.iloc[0].time_index == 80 and result.iloc[0].boardings_index == 150
    assert result.iloc[1][["time_index", "trips_index", "boardings_index"]].isna().all()


def test_positive_boarding_with_zero_trip_defers_ratio_without_dropping_fixed_denominator():
    selected = pd.DataFrame({"group": ["g", "g"]})
    rows = [{"group": "g", "date": day, "trips": trips, "boardings": boards, "joint_known": True,
             "zero_trips_positive_boardings": trips == 0 and boards > 0}
            for day, trips, boards in [("2024-05-20", 2, 20), ("2024-05-20", 3, 15),
                                       ("2025-05-20", 0, 5), ("2025-05-20", 3, 30)]]
    result = module.daily_ratio(pd.DataFrame(rows), selected, ["2024-05-20", "2025-05-20"], ["2024-05-20"], .8)
    assert result.iloc[0].raw_ratio == 7 and result.iloc[0]["index"] == 100
    assert result.iloc[1].coverage == 1 and pd.isna(result.iloc[1]["index"])
    assert result.iloc[1].zero_trips_positive_boardings == 1
