"""경기 자료의 표기·시간·잠금 연도와 승하차 합계 스키마를 검사한다."""

import importlib
import io
import re
import sys
import zipfile
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


def test_only_fully_blank_formatting_rows_can_be_excluded():
    assert mod.blank_row([None, '', None, None])
    assert not mod.blank_row(['용인시', None, None, None])
    assert not mod.blank_row([0, None, None, None])


def test_wrong_dimensions_and_trailing_style_rows_are_audited(tmp_path, monkeypatch):
    workbook = mod.openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = '워크시트 익스포트'
    sheet.append(mod.COMMON + ['시간', '이용객수'])
    sheet.append(['용인시', '2024', '01', '5001', 'A-B', '평일', '23시~00시', 0])
    sheet.cell(8, 8).number_format = '0'
    workbook.create_sheet('SQL').append(["select a.year from x a join y b on b.year='2023' where a.year='2024'"])
    original = io.BytesIO()
    workbook.save(original)
    altered = io.BytesIO()
    with zipfile.ZipFile(original) as before, zipfile.ZipFile(altered, 'w') as after:
        for item in before.infolist():
            blob = before.read(item)
            if item.filename.startswith('xl/worksheets/sheet'):
                blob = re.sub(rb'<dimension ref="[^"]+"/>', b'<dimension ref="A1"/>', blob)
            after.writestr(item, blob)
    monkeypatch.setattr(mod, 'CASE', tmp_path)
    monkeypatch.setattr(mod, 'RAW', tmp_path)
    cfg = {**CFG, 'policy_names': ['5001'], 'explicit_ab_variants': [], 'batch_rows': 2}
    result = mod.parse_book({'id': 'fixture', 'year': 2024, 'sha256': 'a' * 64}, '', altered, cfg)
    assert result['declared_columns'] == 1
    assert result['rows'] == 1
    assert result['fully_blank_xml_rows'] == 6
    assert result['zero_values'] == 1
    assert result['route_description_years'] == ['2023']
    assert mod.pq.read_table(tmp_path / 'fixture_hourly.parquet')['v0'].to_pylist() == [0]
