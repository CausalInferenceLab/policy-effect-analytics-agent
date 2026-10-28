"""지하철의 별칭 중복 거부, 관측 0과 부재 분모, 일·월 합계 완전성을 검증한다."""

import csv
import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
module = importlib.import_module("gangnam.overnight_subway")
data = importlib.import_module("gangnam.overnight_subway_data")


def test_station_aliases_are_not_summed_and_counts_are_strict(tmp_path):
    path = tmp_path / "daily.csv"
    header = ["사용일자", "노선명", "역명", "승차총승객수", "하차총승객수"]
    rows = [["20240501", "3호선", "양재(서초구청)", "0", "10"], ["20240501", "3호선", "양재", "5", "6"]]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows([header, *rows])
    validation = data.validate(path, "2024-05", "daily")
    with pytest.raises(ValueError, match="행 중복"):
        module.selected_rows(path, validation, "daily", [{"line": "3호선", "base_name": "양재", "key": "yangjae_3"}])
    assert module.base_name("양재(서초구청)") == "양재"
    assert module.base_name("앞(가운데)뒤") == "앞(가운데)뒤"
    assert module.count("0") == 0 and module.count("1,000") == 1000 and np.isnan(module.count(""))
    for value in ["-1", "1.5", "NaN", "1,2"]:
        with pytest.raises(ValueError, match="비음수"):
            module.count(value)


def test_missing_dates_stay_in_denominator_and_monthly_blank_is_not_zero():
    rows = pd.DataFrame([{"date": "2024-05-01", "station": "gangnam_2", "flow": "boardings", "value": 0, "row_present": True},
                         {"date": "2024-05-02", "station": "gangnam_2", "flow": "boardings", "value": np.nan, "row_present": True}])
    daily = module.complete_grid(rows, ["gangnam_2"], ["2024-05"], "daily")
    boarding = daily[daily.flow.eq("boardings")]
    assert len(boarding) == 31 and boarding.coverage.mean() == 1 / 31
    assert boarding.record_status.value_counts().to_dict() == {"row_absent": 29, "zero": 1, "blank": 1}
    hourly = pd.DataFrame([{"month": "2024-05", "station": "gangnam_2", "flow": flow, "hour": h, "value": 0}
                           for flow in module.FLOWS for h in range(24)])
    incomplete = module.reconciliation(daily, hourly)
    assert incomplete.status.eq("incomplete").all() and incomplete.difference.isna().all()
    daily["value"] = 0
    assert module.reconciliation(daily, hourly).status.eq("exact").all()
    hourly.loc[0, "value"] = np.nan
    assert module.reconciliation(daily, hourly).set_index("flow").loc["boardings", "status"] == "incomplete"
    hourly.loc[0, "value"] = 1
    assert module.reconciliation(daily, hourly).set_index("flow").loc["boardings", "status"] == "different"
