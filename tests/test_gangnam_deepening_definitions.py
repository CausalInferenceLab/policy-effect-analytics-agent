"""API 명세의 모호한 필드 대응과 잠금 연도 예시를 거절한다."""

import importlib
import sys
from pathlib import Path

import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
mod = importlib.import_module("gangnam.deepening_definitions")


def page(date):
    return ('<table><tr>' + ''.join(f'<th>{x}</th>' for x in
            ['변수명', '타입', '필수 여부', '변수 크기', '변수 설명', '값 설명', '샘플데이터'])
            + '</tr></table><table><tr>' + ''.join(f'<th>{x}</th>' for x in
            ['변수명', '변수 설명', '값 설명', '샘플데이터'])
            + '</tr><tr><td>trip_time</td><td>운행 시간</td><td></td><td></td></tr></table>'
            + '<table><tr><th>샘플 미리보기</th><td>&quot;{&quot;stdrDe&quot;:&quot;'
            + date + '&quot;,&quot;tripTime&quot;:&quot;0&quot;}&quot;</td></tr></table>')


def test_public_sample_preserves_zero_without_unit_inference():
    _, fields, sample = mod.extract(page('20211217'), 2026)
    assert fields == [['trip_time', '운행 시간', '', '']]
    assert sample['tripTime'] == '0'


def test_locked_sample_and_ambiguous_names_are_rejected():
    with pytest.raises(ValueError, match='locked'):
        mod.extract(page('20260101'), 2026)
    with pytest.raises(ValueError, match='ambiguous'):
        mod.indexed(['trip_time', 'tripTime'])
