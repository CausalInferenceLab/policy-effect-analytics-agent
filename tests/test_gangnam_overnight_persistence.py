"""연장 표본이 사후에 재선택되지 않고 결측 상태와 역사 식별자를 보존하는지 검증한다."""

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
persistence = importlib.import_module("gangnam.overnight_persistence")


def sample():
    cells = pd.DataFrame([("south", "r1", "a", "b", 17, 10.), ("south", "r2", "a", "b", 17, 20.)],
                         columns=persistence.CELL + ["baseline_2024"])
    rows = cells.merge(pd.DataFrame({"date": ["2025-05-20", "2025-05-21", "2025-07-08"]}), how="cross")
    rows["value"] = 10.
    rows["record_status"] = "positive"
    return cells, rows


def test_selection_uses_pre2025_only_and_preserves_old_baseline():
    cells, panel = sample()
    panel.loc[panel.route.eq("r1") & panel.date.eq("2025-07-08"), "value"] = np.nan
    panel.loc[panel.route.eq("r2") & panel.date.eq("2025-05-20"), "value"] = np.nan
    result = persistence.pre_retention(panel, cells, ["2025-05-20", "2025-05-21"], .8)
    assert result.pre2025_eligible.tolist() == [True, False]
    assert result.baseline_2024.tolist() == [10., 20.]


def test_absence_zero_blank_and_missing_source_are_separate():
    cells, panel = sample()
    panel = panel[panel.date.eq("2025-05-20")].copy()
    panel.loc[panel.route.eq("r1"), ["value", "record_status"]] = [np.nan, "zero"]
    panel.loc[panel.route.eq("r2"), ["value", "record_status"]] = [np.nan, "blank"]
    row = persistence.record_states(panel, cells, {"pre": ["2025-05-20", "2025-05-21", "2025-05-22"]},
                                     ["2025-05-20", "2025-05-21"]).iloc[0]
    assert (row.source_missing, row.row_absent, row.zero, row.blank, row.positive) == (2, 2, 1, 1, 0)
    assert row.expected_cell_days == 6


def test_identity_requires_every_station_month_to_match():
    stations = pd.DataFrame({"stop": ["a", "b"]})
    identity = pd.DataFrame({"month": ["2025-05"] * 2, "stop": ["a", "b"], "id_observed": [True, True],
                             "id_ars_pair_observed": [True, True], "all_observed_ars_agree": [True, False]})
    with pytest.raises(ValueError, match="누락 또는 불일치"):
        persistence.verify_identity(identity, stations, ["2025-05"])
    identity["all_observed_ars_agree"] = True
    assert persistence.verify_identity(identity, stations, ["2025-05"]) == 2
    with pytest.raises(ValueError, match="누락 또는 불일치"):
        persistence.verify_identity(identity, stations, ["2025-05", "2025-06"])
