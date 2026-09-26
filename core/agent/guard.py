"""⑤ 과잉해석 가드: 판정에 맞는 서술 템플릿 + 인과 단정 표현 린터.

규칙
  1) 판정(verdict)이 identified 가 아니면 인과·확정 표현(CAUSAL) 금지
  2) 신뢰구간이 0을 포함하면 '효과 없음' 류 금지 → '판별 불가'로 써야 함
린터는 단순 문자열/정규식 매칭이다. 부정문("입증되지 않았다")도 잡히는데, 의도된 보수성이다.
"""

from __future__ import annotations

import re

from ..estimators.result import EffectResult

CAUSAL = [
    "효과가 입증",
    "입증",
    "증명",
    "때문에",
    "덕분에",
    "로 인해",
    "인과적으로 확인",
    "확실히",
    "명백히",
    r"\bcaus(e|es|ed|ing)\b",
    r"\bproves?\b",
    r"\bproven\b",
    r"\bdue to\b",
    r"\bbecause of\b",
    r"\bdemonstrates?\b",
    r"\bdefinitely\b",
]
NULL_EFFECT = [
    "효과 없음",
    "효과가 없",
    "효과는 없",
    r"\bno effect\b",
    r"\bhad no (significant )?effect\b",
]

TRIGGER_KO = {
    "pretrend_rejected": "사전추세 차이(평행추세 가정 기각)",
    "few_clusters": "클러스터 수 부족(표준오차 과소추정 위험)",
    "few_treated_clusters": "처치 단위 수 부족(무작위화 추론 사용)",
    "staggered_adoption": "시차 도입에서 TWFE 편향 위험",
    "placebo_significant": "가짜 도입시점 검정 유의",
    "ci_crosses_zero": "신뢰구간이 0을 포함",
    "short_pre_period": "사전 기간 부족",
}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?。])\s+|\n+", text) if s.strip()]


def lint(text: str, verdict: str, ci_crosses_zero: bool) -> list[dict]:
    """금지 표현 목록을 반환. 빈 리스트면 통과."""
    rules = []
    if verdict != "identified":
        rules += [(p, f"판정이 '{verdict}' 인데 인과·확정 표현 사용") for p in CAUSAL]
    if ci_crosses_zero:
        rules += [
            (p, "신뢰구간이 0을 포함 → '효과 없음'이 아니라 '판별 불가'로 서술")
            for p in NULL_EFFECT
        ]
    out = []
    for sent in _sentences(text):
        for pat, reason in rules:
            m = re.search(pat, sent, flags=re.IGNORECASE)
            if m:
                out.append({"phrase": m.group(0), "sentence": sent, "reason": reason})
    return out


def template_narrative(r: EffectResult, unit: str | None = None, name: str | None = None) -> str:
    """판정별 결정론적 서술 (LLM 미사용 시 기본값). 린터를 항상 통과하도록 작성."""
    u = f" {unit}" if unit else ""
    ci = f"95% CI {r.ci_low:.2f} ~ {r.ci_high:.2f}"
    why = ", ".join(TRIGGER_KO.get(t, t) for t in r.triggers) or "없음"
    if r.verdict == "identified":
        return (
            f"**요약**: 정책 도입 후 처치집단의 {name or r.outcome}은(는) 통제집단 대비 평균 "
            f"{r.estimate:+.2f}{u} 변화한 것으로 추정됩니다 ({ci}). 이 해석은 plan.yaml 의 식별 가정이 "
            "성립할 때에만 유효하며, 자동 점검에서 가정이 반박되지 않았다는 뜻이지 검증되었다는 뜻은 아닙니다."
        )
    if r.verdict == "conditional":
        zero = (
            " 신뢰구간이 0을 포함하므로 효과의 방향과 크기는 판별 불가입니다."
            if ("ci_crosses_zero" in r.triggers)
            else ""
        )
        return (
            f"**요약(조건부)**: 추정치는 {r.estimate:+.2f}{u} ({ci}) 이지만 다음 위험 신호가 있어 "
            f"조건부로만 보고합니다: {why}.{zero} 결론 전에 보완 분석이 필요합니다."
        )
    return (
        f"**요약(식별 불가)**: 다음 사유로 이 설계에서는 정책 효과를 추정치로 보고하지 않습니다: {why}. "
        f"표의 수치({r.estimate:+.2f}{u})는 진단용이며 정책 효과로 해석하면 안 됩니다."
    )
