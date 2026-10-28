"""추가 자료의 무결성·정류장 재방문 키·학습 경계·저속 누락 집계를 검증한다."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from zipfile import ZipFile

import pandas as pd
import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
spec = importlib.util.spec_from_file_location("gangnam_discover", CASE / "discover.py")
discovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(discovery)


def test_bus_join_keeps_repeated_visits_separate():
    rows = [["20240708", "route", "stop", "1"], ["20240708", "route", "stop", "5"]]
    left = pd.DataFrame(rows, columns=discovery.KEYS)
    right = left.assign(trips=[12, 3])
    joined, rate = discovery.join_bus(left, right, "matched")
    assert rate == 1 and joined.trips.tolist() == [12, 3]
    with pytest.raises(ValueError, match="중복"):
        discovery.join_bus(left, pd.concat([right, right.iloc[[0]]]), "matched")
    right.loc[1, "정류장_순서"] = None
    with pytest.raises(ValueError, match="결측"):
        discovery.join_bus(left, right, "matched")


def test_week_zip_preserves_month_boundary_and_zero(tmp_path):
    path = tmp_path / "202407.zip"
    member = "2024.07.29-08.04.csv"
    d = pd.DataFrame({"기준_날짜": ["20240731", "20240801"], "노선_ID": ["r", "r"],
                      "정류장_ID": ["00150", "00150"], "정류장_순서": ["2", "2"],
                      "버스운행횟수": [4, None], "버스운행횟수_17시": [0, None]})
    with ZipFile(path, "w") as z:
        z.writestr(member, d.to_csv(index=False).encode("cp949"))
    parsed, report = discovery.read_bus_sample(path, member, [17])
    assert report["dates"] == ["20240731", "20240801"]
    assert report["zero_cells"] == 1 and report["missing_cells"] == 1
    assert parsed["정류장_ID"].tolist() == ["00150", "00150"]
    with pytest.raises(ValueError, match="지정 주간"):
        discovery.read_bus_sample(path, "missing.csv", [17])


def test_threshold_rejects_test_period_and_excludes_invalid_values():
    d = pd.DataFrame({"link_id": ["a"] * 3,
                      "interval_start_kst": pd.to_datetime(["2024-03-04 17:00", "2024-03-11 17:00", "2024-03-18 17:00"]).tz_localize("Asia/Seoul"),
                      "speed_kmh": [10.0, 20.0, 0.0], "is_valid": [True, True, False]})
    threshold = discovery.fit_thresholds(d, "2023-01-01", "2024-03-31", 0.1)
    assert threshold.threshold.tolist() == [11.0]
    d.loc[2, "interval_start_kst"] = pd.Timestamp("2024-04-01", tz="Asia/Seoul")
    with pytest.raises(ValueError, match="허용 기간"):
        discovery.fit_thresholds(d, "2023-01-01", "2024-03-31", 0.1)


def test_tail_score_reports_missed_cases_and_undefined_precision():
    d = pd.DataFrame({"y_true": [4, 6, 12], "y_pred": [8, 5, 11], "threshold": [7, 7, 7]})
    score = discovery.tail_score(d)
    assert score["low_speed_n"] == 2 and score["missed_low_speed_n"] == 1
    assert score["recall"] == 0.5 and score["precision"] == 1
    d["y_pred"] = 10
    assert discovery.tail_score(d)["precision"] is None
    assert discovery.tail_score(d)["recall"] == 0


def test_cached_corruption_is_not_overwritten(tmp_path):
    path = tmp_path / "source.csv"
    path.write_bytes(b"changed")
    item = {"file": path.name, "bytes": 7, "sha256": "0" * 64}
    with pytest.raises(ValueError, match="고정 원본"):
        discovery.collect([item], tmp_path)
    assert path.read_bytes() == b"changed"


def test_manifest_path_cannot_leave_data_directory(tmp_path):
    with pytest.raises(ValueError, match="파일명 하나"):
        discovery.collect([{"file": "../outside.csv"}], tmp_path)
