"""승객 가중 비교의 동일 날짜 조건과 사전 가중치 집중도 계산을 검증한다."""

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
analysis = importlib.import_module("gangnam.overnight_covered_passengers")


def test_mismatched_daily_availability_is_excluded_on_both_sides():
    equal = pd.DataFrame({"group": ["north"] * 3, "date": ["a", "b", "c"], "index": [90., 100., np.nan]})
    weighted = equal.assign(index=[91., np.nan, 111.])
    left, right = analysis.match_valid_dates(equal, weighted)
    assert left["index"].notna().tolist() == right["index"].notna().tolist() == [True, False, False]
    assert left["index"].iloc[0] == 90.
    assert right["index"].iloc[0] == 91.


def test_weight_concentration_distinguishes_zero_and_missing():
    result = analysis.weight_concentration(pd.DataFrame({"weight": [3., 1., 0., np.nan]}))
    assert result["total_pre_weight"] == 4.
    assert result["effective_weight_cells"] == pytest.approx(1.6)
    assert result["zero_weight_cells"] == 1
    assert result["positive_weight_cells"] == 2
    with pytest.raises(ValueError, match="비음수"):
        analysis.weight_concentration(pd.DataFrame({"weight": [-1.]}))
