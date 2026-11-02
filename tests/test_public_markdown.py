"""행안부 AI 친화 보고서 케이스(gyeom-yee-public-markdown): HWPX 지표 계산, 표본 추출, 월 인덱스.
네트워크 없이 메모리에서 만든 작은 HWPX 만 쓴다(pdfplumber 도 필요 없다)."""

from __future__ import annotations

import importlib.util
import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "cases" / "gyeom-yee-public-markdown"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"gypm_{name}", CASE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


fetch = _load("fetch")
NS = 'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"'


def _p(text: str, extra: str = "") -> str:
    return f"<hp:p><hp:run><hp:t>{text}</hp:t>{extra}</hp:run></hp:p>"


def _tbl(*cells: str) -> str:
    tcs = "".join(f"<hp:tc><hp:subList>{c}</hp:subList></hp:tc>" for c in cells)
    return f"<hp:tbl><hp:tr>{tcs}</hp:tr></hp:tbl>"


def _hwpx(body: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/section0.xml", f"<hs:sec {NS} xmlns:hs='urn:x'>{body}</hs:sec>")
    return buf.getvalue()


def test_narrative_units_skip_table_text_and_short_lines():
    body = (
        _p("행정안전부는 오늘 새 지침을 발표했다. 지침은 다음 달부터 적용된다.")
        + _p("□ 주요 내용 개조식 정리 추진")
        + _p("끝")  # 5자 미만은 세지 않는다
        + _p("", _tbl(_p("표 안의 문장은 세지 않는다.")))
    )
    m = fetch.hwpx_metrics(_hwpx(body))
    assert (m["units"], m["narrative"]) == (3, 2)
    assert m["tables"] == 1 and m["has_nested"] == 0
    assert m["cells"] == ["표안의문장은세지않는다."]


def test_nested_table_counts_once_and_keeps_innermost_cells():
    inner = _tbl(_p("가"), _p("나"))
    m = fetch.hwpx_metrics(_hwpx(_p("", _tbl(_p("", inner), _p("다")))))
    assert m["tables"] == 1  # 최상위 표만 센다
    assert m["has_nested"] == 1
    assert sorted(m["cells"]) == ["가", "나", "다"]  # 표를 품은 바깥 셀은 빼고 가장 안쪽 셀만


def test_quoted_sentence_splits_but_both_parts_are_narrative():
    # 닫는 따옴표 뒤에서도 나눈다. 두 조각 모두 서술문이라 비율은 그대로다.
    m = fetch.hwpx_metrics(_hwpx(_p("장관은 “함께 바꾸겠다.” 라고 말했다.")))
    assert (m["units"], m["narrative"]) == (2, 2)


def test_sample_is_deterministic_and_capped():
    ids = [str(i) for i in range(30)]
    a = fetch.sample_ids(ids, "A00031", 27)
    assert a == fetch.sample_ids(list(reversed(ids)), "A00031", 27)
    assert len(a) == fetch.SAMPLE_K
    assert sorted(fetch.sample_ids(ids[:3], "A00031", 27)) == sorted(ids[:3])


class _Resp:
    def __init__(self, text: str):
        self.text = text


def _list_html(ids: list[str], paging: bool) -> str:
    items = "".join(f'<li><a href="/briefing/pressReleaseView.do?newsId={i}&amp;x=1">' for i in ids)
    widget = '<a href="/briefing/pressReleaseView.do?newsId=999">최신 보도자료</a>'
    pages = '<div class="paging"><a onclick="pageLink(1);">1</a></div>' if paging else ""
    return f'<div class="list_type"><ul>{items}</ul></div>{pages}<aside>{widget}</aside>'


def test_list_ignores_side_widget(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "LISTS", tmp_path)
    pages = {"A00031": _list_html(["1", "2"], True), "B00027": _list_html([], False)}
    monkeypatch.setattr(fetch, "_get", lambda url, params: _Resp(pages[params["repCode"]]))
    assert fetch.list_month("A00031", 0) == ["1", "2"]
    assert fetch.list_month("B00027", 0) == []  # 결과가 없는 달에 위젯 글을 세지 않는다


def test_month_index_matches_plan():
    assert fetch.month_of(0) == (2024, 1)
    assert fetch.month_of(27) == (2026, 4)  # plan.yaml treat_time
    assert fetch.month_of(fetch.N_MONTHS - 1) == (2026, 9)
