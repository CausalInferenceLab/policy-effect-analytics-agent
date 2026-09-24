"""단절 시계열(Interrupted Time Series) — 단일 지역/전국 단위 정책용.

모형 (segmented regression):
    y_t = b0 + b1*t + b2*post_t + b3*(t - T0)*post_t [+ 계절 더미] + e_t
    b2 = 도입 직후 수준 변화(level change, 주 추정치), b3 = 기울기 변화(slope change)
표준오차: Newey-West HAC (자기상관 대응).
한계: 통제집단이 없으므로 같은 시점의 다른 사건(동시 정책, 경기변동)과 구분 불가.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.stattools import durbin_watson

from .result import EffectResult


def its(
    df: pd.DataFrame,
    y: str,
    time: str,
    treat_time,
    seasonal_period: int | None = None,
    maxlags: int | None = None,
    alpha: float = 0.05,
    min_pre: int = 8,
) -> EffectResult:
    d = df.sort_values(time).reset_index(drop=True)
    t = np.arange(len(d), dtype=float)
    post = (d[time] >= treat_time).astype(float).values
    t0 = t[post.argmax()] if post.any() else np.nan
    X = pd.DataFrame({"const": 1.0, "trend": t, "level": post, "slope": (t - t0) * post})
    if seasonal_period:
        season = pd.get_dummies(
            t.astype(int) % seasonal_period, prefix="s", drop_first=True, dtype=float
        )
        X = pd.concat([X, season], axis=1)
    maxlags = maxlags if maxlags is not None else max(1, int(len(d) ** 0.25))
    fit = sm.OLS(d[y].astype(float).values, X).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})
    ci = fit.conf_int(alpha=alpha).loc["level"]
    res = EffectResult(
        method="its",
        outcome=y,
        estimate=float(fit.params["level"]),
        se=float(fit.bse["level"]),
        ci_low=float(ci[0]),
        ci_high=float(ci[1]),
        p_value=float(fit.pvalues["level"]),
        n_obs=int(fit.nobs),
        n_clusters=None,
        extra={
            "slope_change": float(fit.params["slope"]),
            "slope_change_p": float(fit.pvalues["slope"]),
            "fitted": fit.fittedvalues.values,
            "counterfactual": (
                fit.fittedvalues
                - fit.params["level"] * X["level"]
                - fit.params["slope"] * X["slope"]
            ).values,
        },
    )
    n_pre = int((1 - post).sum())
    res.assumptions_checked["pre_periods"] = n_pre
    dw = float(durbin_watson(fit.resid))
    res.assumptions_checked["durbin_watson"] = dw
    if n_pre < min_pre:
        res.warn(
            f"사전 관측치 {n_pre}개 < {min_pre}: 사전 추세 추정이 불안정합니다.", "short_pre_period"
        )
    if dw < 1.0 or dw > 3.0:
        res.warn(
            f"Durbin-Watson={dw:.2f}: 강한 자기상관. maxlags 를 늘리거나 ARIMA 오차를 고려하세요."
        )
    res.warn(
        "ITS 는 통제집단이 없어 동시기 다른 사건과 효과를 구분할 수 없습니다. "
        "가능하면 비교 지역을 추가해 DiD 로 확장하세요."
    )
    return res
