"""plan.yaml 하나로 추정 → 반박검정 → 보류판정까지 실행.

케이스의 estimate.py 는 보통 `run_plan(plan, df)` 한 줄이면 충분하다.
시간 컬럼은 정수(연도, 또는 월/분기/일/시간을 0,1,2… 로 인덱싱한 값)여야 한다 → core.schema.timeindex.

시간 자료(freq=hour)일 때
- estimator.event_bin: 상대시점을 묶는 크기 (24=일). placebo_time 의 shift 도 이 단위로 읽는다.
- time.active_hours: 정책이 적용되는 시간대만으로 주 추정을 한다.
- refutations: placebo_window → 적용되지 않는 시간대로 같은 추정을 다시 해, 효과가 없어야 통과.
"""

from __future__ import annotations

import pandas as pd

from .estimators import EffectResult, apply_abstention, did, event_study, its, placebo_time
from .schema.plan import Plan
from .schema.timeindex import hours_numeric, in_window


def _estimate(plan: Plan, df: pd.DataFrame, col: str, common: dict) -> EffectResult:
    e, tr, th = plan.estimator, plan.treatment, plan.thresholds
    if e.method == "its":
        return its(df, col, plan.time.col, tr.treat_time, alpha=e.alpha)
    if e.method == "did":
        return did(df, col, covariates=e.covariates, **common)
    return event_study(
        df,
        col,
        ref_period=e.ref_period,
        window=e.window,
        pretrend_alpha=th.pretrend_alpha,
        bin=e.bin,
        **common,
    )


def split_hours(plan: Plan, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """(정책 적용 시간대, 나머지 시간대). active_hours 가 없으면 (전체, None)."""
    t = plan.time
    if not t.active_hours:
        return df, None
    h = hours_numeric(df[t.hour_col])
    mask = in_window(h, t.active_hours)
    return df[mask], df[~mask & h.notna()]  # 시각이 빈 행은 어느 쪽에도 넣지 않는다


def run_plan(plan: Plan, df: pd.DataFrame) -> list[EffectResult]:
    e, tr, th = plan.estimator, plan.treatment, plan.thresholds
    common = dict(
        unit=plan.unit.id_col,
        time=plan.time.col,
        group_col=tr.group_col,
        treat_time=tr.treat_time,
        first_treat_col=tr.first_treat_col,
        cluster=e.cluster_col,
        alpha=e.alpha,
        min_clusters=th.min_clusters,
    )
    active, inactive = split_hours(plan, df)
    results = []
    for o in plan.outcomes:
        r = _estimate(plan, active, o.col, common)
        if plan.time.active_hours:
            a, b = plan.time.active_hours
            r.assumptions_checked["active_hours"] = f"{a:02d}:00~{b:02d}:00 자료만으로 추정"
        for ref in plan.refutations:
            if ref.kind == "placebo_time" and e.method != "its" and tr.treat_time is not None:
                r.assumptions_checked["placebo_time"] = placebo_time(
                    active,
                    o.col,
                    plan.unit.id_col,
                    plan.time.col,
                    tr.group_col,
                    tr.treat_time,
                    shift=ref.params.get("shift", 2) * e.bin,
                    cluster=e.cluster_col,
                    alpha=th.pretrend_alpha,
                )
            if ref.kind == "placebo_window" and inactive is not None and len(inactive):
                off = _estimate(plan, inactive, o.col, common)
                r.assumptions_checked["placebo_window"] = {
                    "hours": "정책이 적용되지 않는 시간대",
                    "estimate": off.estimate,
                    "ci": [off.ci_low, off.ci_high],
                    "p_value": off.p_value,
                    "passed": bool(off.p_value >= th.pretrend_alpha),
                }
        results.append(apply_abstention(r, plan.abstention, th))
    return results
