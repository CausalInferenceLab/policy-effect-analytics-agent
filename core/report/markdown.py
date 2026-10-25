"""EffectResult + Plan → 마크다운 리포트.

원칙: 판정(verdict)과 경고를 추정치보다 먼저 보여준다 (과잉해석 방지, W6).
"""

from __future__ import annotations

from ..estimators.result import EffectResult
from .interpret import statements

VERDICT_KO = {
    "identified": "✅ 효과 근거 있음 (가정 하에서)",
    "conditional": "⚠️ 크기를 판별하지 못함",
    "not_identified": "⛔ 판단 불가",
}


def _p(p: float) -> str:
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def results_table(results: list[EffectResult]) -> str:
    rows = [
        "| 방법 | 결과변수 | 추정치 | 95% CI | p | N | 클러스터 | 판정 |",
        "|---|---|---:|---|---:|---:|---:|---|",
    ]
    for r in results:
        rows.append(
            f"| {r.method} | {r.outcome} | {r.estimate:.3f} | [{r.ci_low:.3f}, {r.ci_high:.3f}] "
            f"| {_p(r.p_value)} | {r.n_obs} | {r.n_clusters or '-'} | {VERDICT_KO[r.verdict]} |"
        )
    return "\n".join(rows)


def said_lines(plan, results: list[EffectResult]) -> list[str]:
    """판정을 넘지 않는 범위에서 '그래도 말할 수 있는 것' (배제 범위 · 검출 한계)."""
    outs = {o.col: o for o in plan.outcomes}
    lines = []
    for r in results:
        o = outs.get(r.outcome)
        st = statements(
            r.verdict,
            o.name if o else r.outcome,
            r.ci_low,
            r.ci_high,
            r.outcome,
            o.unit if o else None,
        )
        lines += [f"- {v}" for v in st.values()]
    if not lines:
        return []
    return [
        "### 그래도 말할 수 있는 것",
        "",
        *lines,
        "",
        "> 배제 범위: 효과가 있었는지는 판별하지 못했지만, 95% 범위 밖의 큰 효과는 이 자료와 맞지 않습니다. "
        "'효과가 없다'는 뜻이 아닙니다. 판단 불가 결과에는 쓰지 않습니다.",
        "",
    ]


def render_report(
    plan,
    results: list[EffectResult],
    figures: dict[str, str],
    checks: dict | None = None,
    narrative: str | None = None,
) -> str:
    worst = max(
        results, key=lambda r: ["identified", "conditional", "not_identified"].index(r.verdict)
    )
    L = [f"# {plan.title}", ""]
    if plan.synthetic_data:
        L += [
            "> **⚠️ 합성(synthetic) 데이터입니다. 아래 수치는 실제 정책 효과가 아니며, "
            "파이프라인 시연용입니다.**",
            "",
        ]
    L += [
        f"**분석 질문**: {plan.question}",
        "",
        f"**종합 판정**: {VERDICT_KO[worst.verdict]}",
        "",
        *([narrative, ""] if narrative else []),
        "## 1. 설계",
        "",
        f"- 분석 단위: {plan.unit.name} (`{plan.unit.id_col}`), 기간 {plan.time.start}–{plan.time.end} ({plan.time.freq})",
        f"- 처치: {plan.treatment.definition}",
        f"- 통제: {plan.control.definition} — {plan.control.rationale}",
        f"- 주 결과변수: {plan.primary_outcome.name} — {plan.primary_outcome.definition}",
        f"- 추정 방법: `{plan.estimator.method}` (cluster: `{plan.estimator.cluster_col or plan.unit.id_col}`)",
        "",
        "## 2. 결과",
        "",
        results_table(results),
        "",
    ]
    L += said_lines(plan, results)
    for name, path in figures.items():
        L += [f"![{name}]({path})", ""]
    L += ["## 3. 가정 점검 및 반박 검정", "", "| 가정 | 점검 방법 | 결과 |", "|---|---|---|"]
    checks = checks or {}
    for a in plan.assumptions:
        L.append(f"| {a.name} | {a.check} | {checks.get(a.name, '수동 검토 필요')} |")
    L += ["", "## 4. 경고 및 보류 조건", ""]
    warns = sorted({w for r in results for w in r.warnings})
    L += [f"- {w}" for w in warns] or [
        "- (자동 경고 없음 — 그래도 가정은 검증된 것이 아니라 '반박되지 않은' 것입니다)"
    ]
    L += ["", "## 5. 데이터 출처", "", "| 이름 | 제공 | 라이선스 | URL |", "|---|---|---|---|"]
    L += [f"| {d.name} | {d.provider} | {d.license} | {d.url or '-'} |" for d in plan.data_sources]
    return "\n".join(L) + "\n"
