"""인접 구간과 단일 사전 단위 제외가 정류장 순서·고정 기준을 보존하는지 확인한다."""

import importlib
import sys
from pathlib import Path

import pandas as pd
import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
segments = importlib.import_module("gangnam.overnight_persistence_segments")


def test_nonadjacent_and_opposite_direction_cells_are_not_reassigned():
    registry = pd.DataFrame({"stop": ["a", "b", "c", "d"], "group": ["south", "south", "south", "north"],
                             "order": [0, 1, 2, 1], "ars": ["1", "2", "3", "4"], "name": ["A", "B", "C", "D"]})
    cells = pd.DataFrame({"group": ["south"] * 3, "route": ["r"] * 3, "stop": ["a"] * 3,
                         "arrival": ["b", "c", "d"], "hour": [17] * 3, "baseline_2024": [10., 20., 30.]})
    kept, omitted = segments.adjacent_cells(cells, registry)
    assert kept.arrival.tolist() == ["b"]
    assert set(omitted.arrival) == {"c", "d"}
    assert kept.baseline_2024.tolist() == [10.]


def test_leave_one_out_changes_only_selected_unit_and_keeps_baselines():
    cells = pd.DataFrame({"route": ["r1", "r2", "r1"], "segment": ["a", "a", "b"], "baseline_2024": [10., 20., 30.]})
    data = cells.assign(date="2025-07-08", index=[90., 110., 120.])
    remaining, observed = segments.remove_unit(cells, data, "route", "r1")
    assert remaining.baseline_2024.tolist() == [20.]
    assert observed["index"].tolist() == [110.]
    with pytest.raises(ValueError, match="사전 선택에 없는"):
        segments.remove_unit(cells, data, "route", "new2025")
