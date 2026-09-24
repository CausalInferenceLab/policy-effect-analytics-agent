"""자동 경고 레이어 + 보류(abstention) 판정.

추정치는 항상 '조건부 주장'이다. 여기서는 기계적으로 잡을 수 있는 위험 신호를
EffectResult.warnings / triggers 에 기록하고, plan.yaml 의 abstention 규칙에 따라
verdict(identified / conditional / not_identified)를 정한다.
"""

from __future__ import annotations

import pandas as pd

from .result import EffectResult

_ORDER = {"identified": 0, "conditional": 1, "not_identified": 2}


def check_clusters(res: EffectResult, n_clusters: int, min_clusters: int = 20) -> None:
    if n_clusters < min_clusters:
        res.warn(
            f"클러스터 수 {n_clusters}개 < {min_clusters}: 군집-강건 표준오차가 과소추정될 수 "
            "있습니다. wild cluster bootstrap(pyfixest `wildboottest`) 또는 randomization "
            "inference 를 병행하세요.",
            "few_clusters",
        )


def check_staggered(res: EffectResult, first_treat_by_unit: pd.Series) -> None:
    timings = first_treat_by_unit.dropna().unique()
    res.assumptions_checked["n_adoption_cohorts"] = int(len(timings))
    if len(timings) > 1:
        res.warn(
            f"도입 시점이 {len(timings)}개(시차 도입)입니다. TWFE 는 이질적 효과 하에서 편향될 수 "
            "있습니다(Goodman-Bacon 2021). Callaway & Sant'Anna(2021) 또는 pyfixest `did2s`/"
            "`lpdid` 등을 사용하세요.",
            "staggered_adoption",
        )


def apply_abstention(res: EffectResult, rules, thresholds=None) -> EffectResult:
    """plan.abstention 규칙을 적용해 verdict 를 결정 (가장 보수적인 판정이 이긴다).

    rules: list[AbstentionRule] (또는 동일 필드를 가진 dict)
    """
    min_pre = getattr(thresholds, "min_pre_periods", 3)
    pre = res.assumptions_checked.get("pre_periods")
    if pre is not None and pre < min_pre:
        res.warn(f"사전 기간 {pre}기 < {min_pre}: 추세 비교 근거가 부족합니다.", "short_pre_period")
    if res.ci_low <= 0 <= res.ci_high:
        res.warn(
            "신뢰구간이 0을 포함합니다. '효과 없음'이 아니라 '효과 크기를 판별할 수 없음'으로 "
            "해석하세요.",
            "ci_crosses_zero",
        )
    placebo = res.assumptions_checked.get("placebo_time")
    if placebo and not placebo["passed"]:
        res.warn(
            f"가짜 도입시점 검정이 유의(p={placebo['p_value']:.3f}): 도입 전부터 차이가 "
            "벌어졌을 가능성.",
            "placebo_significant",
        )

    verdict = "identified"
    for r in rules:
        r = r if isinstance(r, dict) else r.model_dump()
        if r["when"] in res.triggers and _ORDER[r["verdict"]] > _ORDER[verdict]:
            verdict = r["verdict"]
    res.verdict = verdict
    return res
