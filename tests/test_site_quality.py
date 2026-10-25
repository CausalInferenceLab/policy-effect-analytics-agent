"""'이 결과를 얼마나 믿을 수 있나'·배제 범위·다음 할 일·법령 갱신 경고가 기록대로 나오는지."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "site"))

import answers  # noqa: E402
import quality  # noqa: E402


def _answer(**kw):
    a = {
        "case": "x",
        "verdict": "conditional",
        "results": [
            {
                "name": "판매액(로그)",
                "said": {
                    "rule_out": "판매액(로그): +19.8%보다 큰 증가나 -26.0%보다 큰 감소는 맞지 않음"
                },
                "primary": True,
            },
        ],
        "manifest": {},
    }
    return a | kw


def test_rule_out_only_for_conditional():
    s = answers.rule_out(_answer())
    assert s.startswith("그래도 말할 수 있는 것") and "+19.8%보다 큰 증가" in s
    assert answers.rule_out(_answer(verdict="not_identified")) == ""
    assert answers.rule_out(_answer(results=[{"name": "y", "said": {}}])) == ""


def test_bounds_text_hides_wide_log_ranges():
    assert answers.bounds_text(-0.301, 0.181, "log_population", None) == ("-26.0%", "+19.8%")
    assert answers.bounds_text(-1.3, 1.2, "log_sales", None) is None
    assert answers.bounds_text(-35.4, 38.4, "net_migration_rate", "‰") == ("-35.4 ‰", "+38.4 ‰")


def test_prereg_reads_git_history():
    for case in (ROOT / "cases").glob("*/flow_log.json"):
        r = quality.prereg(case.parent)
        if r is None:  # 얕은 clone 이면 기록을 확인하지 못한다
            continue
        assert r["level"] in {"go", "warn"} and r["plan_at"] <= r["result_at"], case


def test_checks_and_next_steps():
    a = _answer(prereg=None, reproduced_by=["someone"], has_one_line=True)
    heads = [h for _, h, _ in quality.checks(a)]
    assert any("교차 재현 · 확인됨" in h for h in heads)
    assert any("작성자 해석 · 있음" in h for h in heads)
    p = {"stages": [True, True, True, True]}
    todo = quality.next_steps(p, _answer(has_one_line=False, prereg={"level": "warn"}), True)
    assert any("한 문장" in t for t in todo) and any("교차 재현" in t for t in todo)
    assert quality.next_steps({"stages": [True, False, False, False]}, None, False) == [
        "catalog/projects.yaml 에 한 줄 추가",
        "fetch.py 로 data/panel.csv 만들기",
    ]


def test_legal_stale_banner():
    spec = importlib.util.spec_from_file_location("site_build_q", ROOT / "site" / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert "28일째" in mod.legal_stale("2026-09-27", today="2026-10-25")
    assert mod.legal_stale("2026-10-20", today="2026-10-25") == ""
    assert mod.legal_stale("", today="2026-10-25") == ""
