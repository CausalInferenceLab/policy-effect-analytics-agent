"""배제 범위 문장이 판정을 넘지 않는지 — 판단 불가에는 쓰지 않고, 너무 넓은 범위는 말하지 않는다."""

from types import SimpleNamespace as NS

from core.report import interpret
from core.report.markdown import said_lines


def test_bounds_log_and_level():
    assert interpret.bounds(-0.301, 0.181, "log_population") == ("-26.0%", "+19.8%")
    assert interpret.bounds(-1.3, 1.2, "log_sales") is None  # 로그 1.0 보다 넓으면 말하지 않음
    assert interpret.bounds(-35.4, 38.4, "net_migration_rate", "‰") == ("-35.4 ‰", "+38.4 ‰")
    assert interpret.bounds(None, 1.0, "y") is None
    assert interpret.bounds(float("nan"), 1.0, "y") is None


def test_statements_follow_verdict():
    s = interpret.statements("conditional", "인구", -0.301, 0.181, "log_population")
    assert "+19.8%보다 큰 증가" in s["rule_out"] and "-26.0%보다 큰 감소" in s["rule_out"]
    assert interpret.statements("not_identified", "인구", -0.3, 0.18, "log_population") == {}
    assert interpret.statements("identified", "인구", -0.3, -0.1, "log_population") == {}


def test_mde_for_planning():
    # 폭 0.392 → 표준오차 0.1 → 2.8배 ≈ 0.28 (로그) ≈ 32.3%
    assert interpret.mde(-0.196, 0.196, "log_y") == "32.3%"
    assert interpret.mde(-2.0, 2.0, "rate") == "2.86"


def test_report_has_said_section_only_when_conditional():
    plan = NS(outcomes=[NS(col="log_population", name="주민등록인구(로그)", unit=None)])
    cond = NS(verdict="conditional", outcome="log_population", ci_low=-0.301, ci_high=0.181)
    lines = said_lines(plan, [cond])
    assert lines[0] == "### 그래도 말할 수 있는 것" and "+19.8%" in "\n".join(lines)
    stop = NS(verdict="not_identified", outcome="log_population", ci_low=-0.3, ci_high=0.18)
    assert said_lines(plan, [stop]) == []


def test_korean_log_unit_is_log():
    assert interpret.is_log("super_idx", "지수(2020=100, 로그)")
    assert interpret.bounds(-0.195, 0.052, "super_idx", "지수(2020=100, 로그)") == (
        "-17.7%",
        "+5.3%",
    )
