import json
import shutil
import subprocess
from pathlib import Path

import pytest

from core.agent import STEPS, FlowState, build_graph, langgraph_available, run_flow
from core.agent.guard import lint, template_narrative
from core.agent.nodes import define_problem
from core.estimators.result import EffectResult

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "cases" / "_example_night_clinic"


@pytest.fixture
def case(tmp_path):
    """예제 케이스 복사본 (저장소 파일을 건드리지 않도록)."""
    dst = tmp_path / "case"
    shutil.copytree(EXAMPLE, dst, ignore=shutil.ignore_patterns("figures", "*.json", "report.md"))
    shutil.copy(EXAMPLE / "data" / "panel.source.json", dst / "data")
    return dst


def test_full_flow_offline_no_llm(case):
    s = run_flow(case, allow_uncommitted=True, engine="python")
    assert [x.step for x in s.steps] == [n for n, _ in STEPS]
    assert s.status == "warn"  # 미커밋 plan + 합성 데이터 경고
    assert s.verdict == "identified" and s.guard["passed"]
    r = s.results[0]
    assert r.ci_low <= -5.0 <= r.ci_high  # 합성 데이터 참효과
    for f in ("report.md", "run_manifest.json", "flow_log.json", "figures/event_study.png"):
        assert (case / f).exists(), f
    log = json.loads((case / "flow_log.json").read_text(encoding="utf-8"))
    assert log["schema_version"] == "1" and log["verdict"] == "identified"
    assert {
        "index",
        "step",
        "title",
        "status",
        "started_at",
        "ended_at",
        "message",
        "artifacts",
    } <= set(log["steps"][0])
    assert len(log["steps"][1]["artifacts"]["data_sha256"]) == 64
    assert "요약" in (case / "report.md").read_text(encoding="utf-8")


def _r(verdict, lo, hi, triggers=()):
    return EffectResult(
        "did_twfe",
        "y",
        (lo + hi) / 2,
        1.0,
        lo,
        hi,
        0.5,
        100,
        30,
        triggers=list(triggers),
        verdict=verdict,
    )


def test_guard_flags_overclaim():
    bad = "정책 때문에 방문율이 줄었고 효과가 입증되었다. This proves the policy works."
    v = lint(bad, "conditional", ci_crosses_zero=False)
    assert {x["phrase"].lower() for x in v} >= {"때문에", "효과가 입증", "proves"}
    assert lint(bad, "identified", ci_crosses_zero=False) == []  # 식별된 경우엔 허용
    null = lint("정책은 효과 없음으로 나타났다.", "conditional", ci_crosses_zero=True)
    assert any("판별 불가" in x["reason"] for x in null)


@pytest.mark.parametrize(
    "r",
    [
        _r("identified", -6, -4),
        _r("conditional", -2, 1, ["ci_crosses_zero"]),
        _r("not_identified", -6, -4, ["pretrend_rejected"]),
    ],
)
def test_template_narrative_always_passes_lint(r):
    assert lint(template_narrative(r), r.verdict, r.ci_low <= 0 <= r.ci_high) == []


def _git(cwd, *a):
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)


def test_gate_blocks_uncommitted_plan(case):
    _git(case, "init", "-q")
    _git(
        case,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.invalid",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "init",
    )
    s = run_flow(case, write_log=False)
    assert [x.status for x in s.steps] == ["blocked"] and s.status == "blocked"

    _git(case, "add", "plan.yaml")
    _git(
        case,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.invalid",
        "commit",
        "-q",
        "-m",
        "plan",
    )
    assert define_problem(FlowState(case_dir=case)).steps[-1].status == "ok"

    (case / "plan.yaml").write_text((case / "plan.yaml").read_text("utf-8") + "\n# edit\n", "utf-8")
    assert define_problem(FlowState(case_dir=case)).steps[-1].status == "blocked"  # 커밋 후 수정


def test_missing_plan_falls_back_to_template(tmp_path):
    s = run_flow(tmp_path / "new_case", question="X 정책이 Y를 줄였는가?", write_log=False)
    assert s.status == "needs_human" and len(s.steps) == 1
    assert (tmp_path / "new_case" / "plan.yaml").exists()


def test_quality_check_fails_fast(case):
    (case / "data" / "panel.csv").write_text("region_id,year\nR1,2015\n", encoding="utf-8")
    s = run_flow(case, allow_uncommitted=True, write_log=False)
    assert s.steps[-1].step == "structure_metrics" and s.status == "failed"
    assert "필수 컬럼" in s.steps[-1].message


@pytest.mark.skipif(not langgraph_available(), reason="langgraph 미설치")
def test_langgraph_path_matches_python(case):
    assert build_graph() is not None
    g = run_flow(case, allow_uncommitted=True, engine="langgraph", write_log=False)
    p = run_flow(case, allow_uncommitted=True, engine="python", write_log=False)
    assert [x.status for x in g.steps] == [x.status for x in p.steps]
    assert g.results[0].estimate == pytest.approx(p.results[0].estimate)
