"""plan.yaml 하나로 추정 → 반박검정 → 보류판정까지 실행.

케이스의 estimate.py 는 보통 `run_plan(plan, df)` 한 줄이면 충분하다.
시간 컬럼은 정수(연도, 또는 월/분기를 0,1,2… 로 인덱싱한 값)여야 한다.
"""

from __future__ import annotations

import pandas as pd

from .estimators import EffectResult, apply_abstention, did, event_study, its, placebo_time
from .schema.plan import Plan


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
    results = []
    for o in plan.outcomes:
        if e.method == "its":
            r = its(df, o.col, plan.time.col, tr.treat_time, alpha=e.alpha)
        elif e.method == "did":
            r = did(df, o.col, covariates=e.covariates, **common)
        else:
            r = event_study(
                df,
                o.col,
                ref_period=e.ref_period,
                window=e.window,
                pretrend_alpha=th.pretrend_alpha,
                **common,
            )
        for ref in plan.refutations:
            if ref.kind == "placebo_time" and e.method != "its" and tr.treat_time is not None:
                r.assumptions_checked["placebo_time"] = placebo_time(
                    df,
                    o.col,
                    plan.unit.id_col,
                    plan.time.col,
                    tr.group_col,
                    tr.treat_time,
                    shift=ref.params.get("shift", 2),
                    cluster=e.cluster_col,
                    alpha=th.pretrend_alpha,
                )
        results.append(apply_abstention(r, plan.abstention, th))
    return results
