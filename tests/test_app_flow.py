"""Flow page renders an existing flow_log.json without running the agent (AppTest, no network)."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "flow_case"
PAGE = ROOT / "app" / "pages" / "1_Flow.py"

sys.path.insert(0, str(ROOT / "app"))
import flow_view as fv  # noqa: E402

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


@pytest.fixture
def cases_root(tmp_path, monkeypatch):
    shutil.copytree(FIXTURE, tmp_path / "flow_case")
    monkeypatch.setenv("PEA_CASES_DIR", str(tmp_path))
    for k in fv.LLM_KEY_ENVS:
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def _text(at) -> str:
    parts = [
        e.value
        for kind in ("markdown", "error", "info", "caption", "success")
        for e in getattr(at, kind)
    ]
    return "\n".join(str(p) for p in parts)


def test_normalize_fills_six_steps():
    log = fv.normalize_flow_log({"steps": [{"step": "collect", "status": "ok"}]})
    assert [s["step"] for s in log["steps"]] == [n for n, _ in fv.STEPS]
    assert [s["status"] for s in log["steps"]] == ["skipped", "ok"] + ["skipped"] * 4


def test_steps_match_core_contract():
    state = pytest.importorskip("core.agent.state")
    assert [n for n, _ in state.STEPS] == [n for n, _ in fv.STEPS]


def test_fixture_matches_schema_version():
    raw = json.loads((FIXTURE / "flow_log.json").read_text(encoding="utf-8"))
    assert raw["schema_version"] == "1" and len(raw["steps"]) == 6


def test_flow_page_renders_existing_log(cases_root):
    at = AppTest.from_file(str(PAGE), default_timeout=60).run()
    assert not at.exception, at.exception
    text = _text(at)
    assert "SYNTHETIC" in text
    assert "식별됨" in text  # verdict label, not raw "identified"
    assert "과잉해석 표현 1건" in text  # guard finding highlighted
    assert "FIXTURE-REPORT-BODY" in text  # report preview
    assert len(at.expander) >= 6
    assert at.sidebar.toggle[0].disabled  # no LLM key -> toggle disabled
    assert at.sidebar.checkbox[0].label == "allow uncommitted plan (demo)"


def test_flow_page_without_log_prompts_run(cases_root):
    (cases_root / "flow_case" / "flow_log.json").unlink()
    at = AppTest.from_file(str(PAGE), default_timeout=60).run()
    assert not at.exception
    assert any("Run flow" in i.value for i in at.info)
