"""공통 운영 셀의 구간 연결이 원래 사전 표본을 보존하고 집계 비율 기준을 분리하는지 검사한다."""

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
module = importlib.import_module("gangnam.overnight_segment_operations")


def test_segment_join_rejects_unselected_cells_instead_of_silently_dropping_them():
    original = pd.DataFrame({"group": ["s", "s"], "route": ["a", "b"], "stop": "1", "arrival": "2", "hour": 17,
                             "segment": "s|1|2", "from_ars": "001", "to_ars": "002", "from_order": 0,
                             "from_name": "출발", "to_name": "도착"})
    selected = original[module.CELL].iloc[:1].assign(baseline_2024=10.)
    result = module.attach_segments(selected, original)
    assert len(result) == 1 and result.segment.iloc[0] == "s|1|2"
    with pytest.raises(ValueError, match="포함"):
        module.attach_segments(selected.assign(route="unknown"), original)
    with pytest.raises(ValueError, match="중복"):
        module.attach_segments(pd.concat([selected, selected]), original)


def test_segment_ratio_uses_own_baseline_and_preserves_day_missingness():
    selected = pd.DataFrame({"group": ["s|1|2", "s|2|3"]})
    dates = ["2024-05-20", "2025-05-20"]
    data = pd.DataFrame({"group": ["s|1|2", "s|2|3", "s|1|2", "s|2|3"], "date": [dates[0], dates[0], dates[1], dates[1]],
                         "trips": [10., 1., 5., np.nan], "boardings": [20., 20., 20., np.nan],
                         "joint_known": [True, True, True, False], "zero_trips_positive_boardings": False})
    out = module.daily_ratio(data, selected, dates, [dates[0]], .8).set_index(["group", "date"])
    assert out.loc[("s|1|2", dates[1]), "index"] == 200.
    assert out.loc[("s|2|3", dates[0]), "ratio_baseline_2024"] == 20.
    assert np.isnan(out.loc[("s|2|3", dates[1]), "index"])
