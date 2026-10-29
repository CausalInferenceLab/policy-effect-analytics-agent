"""연간 자료 게시물의 첨부 범위와 외부 다운로드 경계를 검증한다."""

import importlib
import sys
from pathlib import Path

import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
mod = importlib.import_module("gangnam.deepening_gyeonggi_data")
CFG = {"years": [2024], "board_title_contains": "노선별 버스 이용객수"}


def row(year, url='/gtdb/common/download2.do?f=public'):
    return (f'<tr><td>{year}</td><td><a href="javascript:fn_goView(\'1956\', \'1695\');">'
            f'{year}년 노선별 버스 이용객수 자료</a></td><td>'
            f'<a href="{url}" title="시간대별.xlsx 파일다운로드">파일</a></td></tr>')


def test_year_selected_from_own_row_not_other_publication_date():
    jobs = mod.parse_catalog(row(2026) + row(2024), CFG)
    assert len(jobs) == 1
    assert jobs[0]['year'] == 2024
    assert jobs[0]['board_no'] == '1956'


def test_external_attachment_rejected():
    with pytest.raises(ValueError, match='endpoint'):
        mod.parse_catalog(row(2024, 'https://example.com/gtdb/common/download2.do?f=x'), CFG)
