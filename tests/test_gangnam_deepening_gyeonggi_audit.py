"""설명 중복을 합산하지 않고 충돌·누락된 시간 합계를 별도 판정한다."""

import importlib
import sys
from pathlib import Path

import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
pd = pytest.importorskip("pandas")
pytest.importorskip("pyarrow")
pytest.importorskip("openpyxl")
mod = importlib.import_module("gangnam.deepening_gyeonggi_audit")


def test_description_repeat_is_not_sum_and_value_conflict_is_excluded():
    base = dict(year=2024, city='용인시', month=7, route='5001', day_type='평일', detail='전일')
    frame = pd.DataFrame([{**base, 'terminal': 'A-B', 'v0': 10},
                          {**base, 'terminal': 'C-D', 'v0': 10},
                          {**base, 'route': '5002', 'terminal': 'A-B', 'v0': 10},
                          {**base, 'route': '5002', 'terminal': 'A-B', 'v0': 11}])
    kept, _, report = mod.canonical_records(frame, 'daily')
    assert kept.v0.tolist() == [10]
    assert kept.terminal_versions.tolist() == [2]
    assert report['full_keys_with_conflicting_values'] == 1
    assert report['natural_keys_with_conflicting_values'] == 1


def test_partial_hours_do_not_pass_when_observed_sum_happens_to_match():
    frame = pd.DataFrame([dict(year=2024, city='용인시', month=7, route='5001', day_type='평일',
                              observed_hours=12, required_hours=24)])
    check = mod.compare_pair(frame, 'hour_sum', pd.Series([10]), pd.Series([10]), pd.Series([False]))
    assert check.status.tolist() == ['incomplete_hour_coverage']
