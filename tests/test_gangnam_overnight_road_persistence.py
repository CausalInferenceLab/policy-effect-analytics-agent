"""도로의 과거 표본이 메타데이터 변경·날짜 누락으로 조용히 대체되지 않는지 검사한다."""

import importlib
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
module = importlib.import_module("gangnam.overnight_road_persistence")


def test_metadata_change_and_absent_month_keep_original_links():
    expected = pd.DataFrame([{"link_id": "a", "road": "도로", "시점명": "시작", "종점명": "끝", "direction": "상행", "length": 100}])
    actual = expected.assign(month="2025-05", 종점명="다른 끝")
    checked = module.metadata_check(expected, actual, ["2025-05", "2025-06"])
    assert len(checked) == 2
    assert not checked.metadata_pass.any()
    assert checked.metadata_present.tolist() == [True, False]
    assert checked.length_original.tolist() == [100, 100]
    with pytest.raises(ValueError, match="중복"):
        module.metadata_check(expected, pd.concat([actual, actual]), ["2025-05"])


def test_unobserved_link_stays_in_fixed_coverage_denominator():
    selected = pd.DataFrame({"link_id": ["a", "b"], "hour": [17, 17], "length": [100, 100]})
    part = pd.DataFrame({"link_id": ["a"], "hour": [17], "date": ["2025-05-20"], "speed_kmh": [20.]})
    result = module.speed_daily(part, selected, ["2025-05-20", "2025-05-21"], "fixed_length_arithmetic", .8)
    assert result.coverage.tolist() == [.5, 0.]
    assert result["index"].isna().all()
