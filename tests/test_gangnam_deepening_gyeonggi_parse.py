"""경기 자료의 표기·시간·잠금 연도와 승하차 합계 스키마를 검사한다."""

import importlib
import sys
from pathlib import Path

import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
pytest.importorskip("pyarrow")
mod = importlib.import_module("gangnam.deepening_gyeonggi_parse")
CFG = {"years": [2024], "locked_year": 2026}


def test_zero_missing_and_midnight_kept_separate():
    row = ['용인시', 2024, '01', '5001A', '시점-종점', '평일', '23시~00시', 0]
    assert mod.normalize(row, 'hourly', 2024, CFG)['v0'] == 0
    row[-1] = None
    assert mod.normalize(row, 'hourly', 2024, CFG)['v0'] is None
    row[-2] = '23시~02시'
    with pytest.raises(ValueError, match='interval'):
        mod.normalize(row, 'hourly', 2024, CFG)


def test_year_gate_precedes_numeric_outcome_read():
    row = ['용인시', 2026, '01', '5001', '시점-종점', '평일', '전일', object()]
    with pytest.raises(ValueError, match='locked'):
        mod.normalize(row, 'daily', 2026, CFG)


def test_route_prefixes_and_explicit_variants_are_not_collapsed():
    names = mod.aliases({'policy_names': ['4403', 'M4403', '1551', '1551B', '5001'],
                         'explicit_ab_variants': ['5001']})
    assert names['4403'] != names['M4403']
    assert names['1551B'] == '1551B'
    assert names['5001A'] == '5001'
    assert '5001-1' not in names
