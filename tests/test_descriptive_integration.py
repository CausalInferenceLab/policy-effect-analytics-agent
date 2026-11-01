"""관측 통계(descriptive_only) 결과가 판정 집계·필터·README 표에서 '판단 불가'와 섞이지 않는지."""

import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "site"))

import answers  # noqa: E402
import board  # noqa: E402

DESC = {"execution_kind": "descriptive_only", "verdict": "not_identified"}


def test_kpis_count_descriptive_separately():
    html = board.kpis(escape, [DESC, {"verdict": "not_identified"}], 10, 3)
    assert "관측 통계" in html
    # 판단 불가 타일에는 진짜 not_identified 하나만
    stop = html.split("판단 불가")[0].rsplit('<span class="v">', 1)[1]
    assert stop.startswith("1<")


def test_kpis_hide_descriptive_tile_when_none():
    assert "관측 통계" not in board.kpis(escape, [{"verdict": "identified"}], 10, 3)


def test_card_filters_descriptive_as_its_own_group():
    a = {
        **DESC,
        "topic": None,
        "synthetic": False,
        "mentor": False,
        "owner": "someone",
        "finished": "",
        "page": "answers/x.html",
        "title": "t",
        "outcomes": [],
        "results": [],
        "has_one_line": False,
    }
    html = answers.card(escape, a, {})
    assert 'data-verdict="descriptive"' in html and "v-info" in html
    assert answers.DESCRIPTIVE_LABEL in html
