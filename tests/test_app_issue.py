"""이슈 → 데이터 → 효과 페이지가 예시 입력으로 끝까지 렌더링되는지 (네트워크·실행 없이)."""

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

PAGE = Path(__file__).resolve().parents[1] / "app" / "pages" / "0_Issue_to_Effect.py"


def test_issue_page_renders_for_example():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["issue"] = "토허제 강남3구 용산 확대하고 집값 잡혔나"
    at.run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "토지거래허가구역" in text
    assert any("효과 분석 실행" in b.label for b in at.button)


def test_issue_page_no_match():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["issue"] = "오늘 점심 뭐 먹지"
    at.run()
    assert not at.exception and at.warning
