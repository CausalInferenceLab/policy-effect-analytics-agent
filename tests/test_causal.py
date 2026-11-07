"""PyWhy(DoWhy)·CausalML 연계와 가설·데이터 점검.

feasibility·draft·unit_changes 는 추가 설치 없이, DoWhy·CausalML 단계는 설치돼 있을 때만 돈다(CI 의 causal 작업).
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from core.causal.draft import draft
from core.causal.feasibility import space_level, time_level, topic_feasibility
from core.causal.pywhy import check_case, unit_changes
from core.discovery.catalog import load_topics
from core.discovery.ontology import load_datasets, load_issues
from core.schema.plan import Plan, load_plan

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "cases" / "_example_night_clinic"


def test_unit_levels():
    assert (
        space_level("시군구(법정동)") == 3
        and space_level("지점(역)") == 4
        and space_level("확인필요") is None
    )
    assert time_level("월") == 2 and time_level("실시간") == 5 and time_level("수시") is None


def test_feasibility_for_every_topic_has_six_checks_and_graph():
    ds, iss = load_datasets(), load_issues()
    for t in load_topics():
        f = topic_feasibility(t, ds, iss)
        assert [c["key"] for c in f["checks"]] == [
            "when",
            "who",
            "what",
            "confounders",
            "space",
            "time",
        ]
        assert f["verdict"] in {"go", "warn", "stop"} and f["label"]
        assert ["정책", "결과"] in f["graph"]["edges"]
        assert f["hypothesis"]["sentence"]


def test_draft_is_schema_valid_and_uses_official_date():
    r = draft("서울 토허제 전역 확대 뒤 집값이 잡혔나", "gildong-ltp")
    assert r["matched"] and r["issue"] == "seoul-ltp-1015-2025"
    plan = Plan.model_validate(yaml.safe_load(r["plan_yaml"]))
    assert plan.treatment.treat_time == "2025-10"  # issues.yaml 의 공식 시행일 2025-10-20
    assert r["todo"] > 0  # 사람이 채울 칸은 남긴다
    assert draft("반려동물 등록제 효과")["matched"] is False


def test_unit_changes_equals_two_by_two_did():
    plan = load_plan(EX / "plan.yaml")
    df = pd.read_csv(EX / "data" / "panel.csv")
    f = unit_changes(plan, df)
    y = plan.primary_outcome.col
    post = df[plan.time.col] >= plan.treatment.treat_time
    m = df.groupby([plan.treatment.group_col, post])[y].mean()
    did = (m[1, True] - m[1, False]) - (m[0, True] - m[0, False])
    est = f.loc[f["T"] == 1, "dy"].mean() - f.loc[f["T"] == 0, "dy"].mean()
    assert np.isclose(est, did, atol=1e-9)
    assert set(f.columns) >= {"T", "dy", "y_pre"} and f["T"].sum() == 30


def test_check_case_without_data_says_so(tmp_path):
    case = tmp_path / "c"
    case.mkdir()
    (case / "plan.yaml").write_text(
        (EX / "plan.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    assert check_case(case)["status"] == "no_data"


def test_dowhy_and_causalml_recover_the_synthetic_effect():
    pytest.importorskip("dowhy")
    pytest.importorskip("causalml")
    r = check_case(EX)
    assert r["status"] == "ok" and r["same_direction_as_baseline"] is True
    dw, ml = r["dowhy"], r["causalml"]
    assert dw["status"] == "ok" and abs(dw["estimate"] - (-5.0)) < 0.6  # 합성 데이터의 참효과 -5.0
    assert {x["status"] for x in dw["refutations"]} == {"pass"}
    assert "y_pre" in dw["identification"]["adjust_for"]
    assert ml["status"] == "ok" and abs(ml["ate"] - (-5.0)) < 0.6 and len(ml["by_baseline"]) == 3


def test_causalml_skips_with_few_treated_units():
    from core.causal.pywhy import causalml_hte

    f = pd.DataFrame({"T": [1] * 4 + [0] * 21, "dy": np.arange(25.0), "y_pre": np.arange(25.0)})
    assert causalml_hte(f, [])["status"] == "skipped"


def test_committed_second_opinion_renders_on_answer_page():
    import sys
    from html import escape

    sys.path.insert(0, str(ROOT / "site"))
    import answers as ans

    a = {x["case"]: x for x in ans.load_answers()}["t3-land-permit-2025"]
    assert a["pywhy"] and a["pywhy"]["dowhy"]["status"] == "ok"
    html = ans.pywhy_block(escape, a)
    assert "DoWhy" in html and "CausalML" in html and "가짜 처치" in html


def test_news_rss_count_parses_items():
    import importlib.util

    spec = importlib.util.spec_from_file_location("rt", ROOT / "scripts" / "refresh_trends.py")
    rt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rt)
    xml = "<rss><channel><item><title>a</title></item><item><title>b</title></item></channel></rss>"
    assert rt.count_rss_items(xml) == 2 and rt.count_rss_items("not xml") == 0
    t = load_topics()[0]
    assert "when:7d" in rt.news_query(t) and rt.news_link(t).startswith(
        "https://news.google.com/search?"
    )


ISSUE_BODY = """### 담당자 GitHub ID

gildong

### 주제 · 이슈

housing-regulation / seoul-ltp-gangnam-2025

### 하려는 것 (한두 문장)

강남3구 재지정 뒤
가격 급등이 멈췄나
"""


def test_issue_agent_comment_and_plan():
    from core.causal.issue_agent import MARK, comment, parse_form, plan_for_issue

    form = parse_form(ISSUE_BODY)
    assert form["담당자 GitHub ID"] == "gildong"
    r = plan_for_issue("[작업] x", ISSUE_BODY)
    assert r["case"] == "gildong-housing-regulation" and r["issue"] == "seoul-ltp-gangnam-2025"
    plan = Plan.model_validate(yaml.safe_load(r["plan_yaml"]))
    assert (
        plan.question.strip() == "강남3구 재지정 뒤 가격 급등이 멈췄나"
    )  # 힌트는 plan 에 들어가지 않는다
    assert plan.treatment.treat_time == "2025-03"
    c = comment("[작업] x", ISSUE_BODY)
    assert c.startswith(MARK) and "plan-approved" in c and "```yaml" in c


def test_issue_agent_rejects_unsafe_owner_and_multiline_injection():
    from core.causal.issue_agent import plan_for_issue

    bad = plan_for_issue(
        "[작업] x", "### 담당자 GitHub ID\n\n$(rm -rf /)\n\n### 하려는 것 (한두 문장)\n\n토허제\n"
    )
    assert bad["case"] is None
    inj = plan_for_issue(
        "[작업] x",
        "### 담당자 GitHub ID\n\ngildong\n\n### 하려는 것 (한두 문장)\n\n토허제 효과\nsynthetic_data: true\ncase_id: evil\n",
    )
    d = yaml.safe_load(inj["plan_yaml"])
    assert d["case_id"] == "gildong-housing-regulation" and d["synthetic_data"] is False


def test_plan_agent_workflow_keeps_issue_text_out_of_shell():
    wf = (ROOT / ".github" / "workflows" / "plan-agent.yml").read_text(encoding="utf-8")
    assert "plan-approved" in wf and "ISSUE_BODY: ${{ github.event.issue.body }}" in wf
    run_lines = [
        ln
        for ln in wf.splitlines()
        if "github.event.issue.body" in ln or "github.event.issue.title" in ln
    ]
    assert all(ln.strip().startswith(("ISSUE_BODY:", "ISSUE_TITLE:")) for ln in run_lines)
