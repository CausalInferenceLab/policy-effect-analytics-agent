"""노선 이름 차이·숫자 공란·정류장 부재가 합계 검증과 공개 조건에 미치는 영향을 확인한다."""

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
cards = importlib.import_module("gangnam.overnight_card_records")


def test_route_label_variants_reconcile_without_global_rename():
    d = pd.DataFrame({"month": ["2024-08"] * 3, "stop": ["s"] * 3, "flow": ["boardings"] * 3,
                      "route_label": ["0411", "411", "402"], "source_membership": ["left_only", "right_only", "both"],
                      "record_sum_daily": [100, np.nan, 20], "record_sum_monthly": [np.nan, 100, 20],
                      "exact_duplicate_rows_daily": [0, np.nan, 0], "exact_duplicate_rows_monthly": [np.nan, 0, 0],
                      "daily_source_month_complete": [True] * 3})
    result = cards.station_reconciliation(d)
    assert result.iloc[0].record_sum_daily == 120
    assert result.iloc[0].quality_pass
    d.loc[2, "record_sum_daily"] = np.nan
    assert not cards.station_reconciliation(d).iloc[0].quality_pass


def test_group_total_requires_every_fixed_station_and_preserves_zero():
    stations = pd.DataFrame({"stop": ["a", "b"], "group": ["g", "g"]})
    d = pd.DataFrame({"date": ["2024-07-08"] * 2 + ["2024-07-09"] * 2,
                      "group": ["g"] * 4, "stop": ["a", "b", "a", "b"], "flow": ["boardings"] * 4,
                      "value": [0, 20, 30, np.nan]})
    result = cards.group_records(d, stations, ["g"]).set_index("date")
    assert result.loc["2024-07-08", "index"] == 20
    assert result.loc["2024-07-09", "coverage"] == .5
    assert np.isnan(result.loc["2024-07-09", "index"])
