"""카드 연장에서 정류장 부재·ARS 불일치·시간 공란을 유효 관측으로 바꾸지 않는지 검사한다."""

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
cards = importlib.import_module("gangnam.overnight_card_persistence")


def test_identity_requires_each_month_stop_and_all_ars_values():
    stations = pd.DataFrame({"stop": ["a", "b"], "ars": ["01001", "01002"]})
    frame = pd.DataFrame({"month": ["2025-05"] * 4, "stop": ["a", "a", "b", "b"],
                          "ars": ["01001", "01001", "01002", "99999"]})
    result = cards.identity_rows(frame, stations, ["2025-05", "2025-06"], "daily").set_index(["month", "stop"])
    assert result.loc[("2025-05", "a"), "quality_pass"]
    assert not result.loc[("2025-05", "b"), "quality_pass"]
    assert not result.loc["2025-06", "quality_pass"].any()


def test_monthly_comparison_preserves_missing_hour_and_zero(monkeypatch):
    monkeypatch.setattr(cards, "read_yaml", lambda _: {"bus_exploration": {"bands": {"evening": [17, 18]}}})
    cfg = {"monthly_hours": {"bands_from": "ignored.yaml", "pairs": [["2024-05", "2025-05"]]}}
    data = pd.DataFrame({"month": ["2024-05"] * 2 + ["2025-05"] * 2, "group": ["g"] * 4,
                         "flow": ["boardings"] * 4, "hour": [17, 18] * 2, "value": [31., 31., 62., 0.], "calendar_days": [31] * 4})
    result = cards.monthly_year_changes(data, cfg).set_index("band")
    assert result.loc["evening", "quality_pass"]
    assert result.loc["evening", "change_pct"] == 0
    assert not result.loc["all_day", "quality_pass"]
    data.loc[3, "value"] = np.nan
    result = cards.monthly_year_changes(data, cfg).set_index("band")
    assert not result.loc["evening", "quality_pass"]
    assert np.isnan(result.loc["evening", "change_pct"])
