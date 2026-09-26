"""이중차분(DiD) 계열 추정기 — pyfixest 기반.

- did():          TWFE DiD  y ~ D | unit + time  (2x2 및 동시 도입 다기간 모두 커버)
- event_study():  상대시점 더미 기반 동적효과 + 사전추세 결합 Wald 검정
- placebo_time(): 사전 구간만 잘라 가짜 도입시점으로 재추정 (반박 검정)

주의: 도입 시점이 단위마다 다른 '시차 도입(staggered)'에서 TWFE 는 이미 처치된
단위를 통제군으로 쓰면서 편향될 수 있다 (Goodman-Bacon 2021). 이 경우 경고를 띄우며,
Callaway & Sant'Anna(2021) 등 이질효과-강건 추정을 권장한다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyfixest as pf
from scipy import stats

from .diagnostics import check_clusters, check_staggered
from .result import EffectResult


def _first_treat(df, unit, time, group_col, first_treat_col, treat_time) -> pd.Series:
    """단위별 최초 처치 시점 (미처치 = NaN)."""
    if first_treat_col:
        return df[first_treat_col].astype(float)
    return np.where(df[group_col] == 1, float(treat_time), np.nan)


def _fit(df, fml, cluster):
    vcov = {"CRV1": cluster} if cluster else "hetero"
    return pf.feols(fml, data=df, vcov=vcov)


def did(
    df: pd.DataFrame,
    y: str,
    unit: str,
    time: str,
    group_col: str,
    treat_time=None,
    first_treat_col: str | None = None,
    cluster: str | None = None,
    covariates: list[str] = (),
    alpha: float = 0.05,
    min_clusters: int = 20,
) -> EffectResult:
    """TWFE DiD. cluster 기본값은 unit (정책이 단위 수준에서 배정되므로)."""
    cluster = cluster or unit
    d = df.copy()
    d["_ft"] = _first_treat(d, unit, time, group_col, first_treat_col, treat_time)
    d["_D"] = ((d[time] >= d["_ft"]) & d["_ft"].notna()).astype(int)
    rhs = " + ".join(["_D", *covariates])
    fit = _fit(d, f"{y} ~ {rhs} | {unit} + {time}", cluster)
    ci = fit.confint(alpha=alpha).loc["_D"]
    n_cl = d[cluster].nunique()
    res = EffectResult(
        method="did_twfe",
        outcome=y,
        estimate=float(fit.coef()["_D"]),
        se=float(fit.se()["_D"]),
        ci_low=float(ci.iloc[0]),
        ci_high=float(ci.iloc[1]),
        p_value=float(fit.pvalue()["_D"]),
        n_obs=int(fit._N),
        n_clusters=int(n_cl),
    )
    check_clusters(res, n_cl, min_clusters)
    check_staggered(res, d.groupby(unit)["_ft"].first())
    return res


def event_study(
    df: pd.DataFrame,
    y: str,
    unit: str,
    time: str,
    group_col: str,
    treat_time=None,
    first_treat_col: str | None = None,
    cluster: str | None = None,
    ref_period: int = -1,
    window: tuple[int, int] = (-4, 4),
    pretrend_alpha: float = 0.10,
    alpha: float = 0.05,
    min_clusters: int = 20,
) -> EffectResult:
    """상대시점 더미 TWFE. 창 밖 상대시점은 양끝으로 binning.

    반환 EffectResult.estimate = 사후 계수들의 평균(단순평균),
    extra['coefs'] = 상대시점별 계수표, assumptions_checked['parallel_pretrends'] = 결합검정.
    """
    cluster = cluster or unit
    lo, hi = window
    d = df.copy()
    d["_ft"] = _first_treat(d, unit, time, group_col, first_treat_col, treat_time)
    rel = (d[time] - d["_ft"]).clip(lo, hi)
    names = {}
    for k in range(lo, hi + 1):
        if k == ref_period:
            continue
        nm = f"ev_m{-k}" if k < 0 else f"ev_p{k}"
        d[nm] = ((rel == k) & d["_ft"].notna()).astype(int)
        names[nm] = k
    names = {n: k for n, k in names.items() if d[n].any()}  # 관측 없는 상대시점 제거
    fit = _fit(d, f"{y} ~ {' + '.join(names)} | {unit} + {time}", cluster)
    coef, se, ci = fit.coef(), fit.se(), fit.confint(alpha=alpha)
    tab = pd.DataFrame(
        {
            "rel_time": list(names.values()),
            "coef": coef[list(names)].values,
            "se": se[list(names)].values,
            "ci_low": ci.loc[list(names)].iloc[:, 0].values,
            "ci_high": ci.loc[list(names)].iloc[:, 1].values,
        }
    )
    tab = pd.concat(
        [
            tab,
            pd.DataFrame(
                [{"rel_time": ref_period, "coef": 0.0, "se": 0.0, "ci_low": 0.0, "ci_high": 0.0}]
            ),
        ]
    ).sort_values("rel_time")

    # 사전추세 결합 Wald 검정 (H0: 모든 사전 계수 = 0). 가장 먼 bin 은 포함.
    pre = [n for n, k in names.items() if k < 0]
    post = [n for n, k in names.items() if k >= 0]
    idx = [list(coef.index).index(n) for n in pre]
    V = fit._vcov[np.ix_(idx, idx)]
    b = coef[pre].values
    wald = float(b @ np.linalg.pinv(V) @ b)
    p_pre = float(stats.chi2.sf(wald, df=len(pre)))

    # 사후 평균효과와 그 SE (선형결합)
    pidx = [list(coef.index).index(n) for n in post]
    w = np.full(len(post), 1 / len(post))
    est = float(w @ coef[post].values)
    se_avg = float(np.sqrt(w @ fit._vcov[np.ix_(pidx, pidx)] @ w))
    z = stats.norm.ppf(1 - alpha / 2)
    n_cl = d[cluster].nunique()
    res = EffectResult(
        method="event_study",
        outcome=y,
        estimate=est,
        se=se_avg,
        ci_low=est - z * se_avg,
        ci_high=est + z * se_avg,
        p_value=float(2 * stats.norm.sf(abs(est / se_avg))),
        n_obs=int(fit._N),
        n_clusters=int(n_cl),
        extra={"coefs": tab},
    )
    res.assumptions_checked["parallel_pretrends"] = {
        "test": "joint Wald (chi2)",
        "stat": wald,
        "df": len(pre),
        "p_value": p_pre,
        "passed": p_pre >= pretrend_alpha,
    }
    if p_pre < pretrend_alpha:
        res.warn(
            f"사전추세 결합검정 p={p_pre:.3f} < {pretrend_alpha}: 평행추세 가정이 의심됩니다. "
            "효과를 인과적으로 해석하지 마세요.",
            "pretrend_rejected",
        )
    n_pre = int(
        d.loc[d["_ft"].notna(), time]
        .lt(d.loc[d["_ft"].notna(), "_ft"])
        .groupby(d.loc[d["_ft"].notna(), unit])
        .sum()
        .min()
    )
    res.assumptions_checked["pre_periods"] = n_pre
    check_clusters(res, n_cl, min_clusters)
    check_staggered(res, d.groupby(unit)["_ft"].first())
    return res


def placebo_time(
    df: pd.DataFrame,
    y: str,
    unit: str,
    time: str,
    group_col: str,
    treat_time,
    shift: int = 2,
    cluster: str | None = None,
    alpha: float = 0.10,
) -> dict:
    """실제 도입 이전 구간만 사용해 도입시점을 shift 만큼 앞당긴 가짜 DiD.
    유의하면(p<alpha) 사전 구간에 이미 차이가 벌어지고 있었다는 신호."""
    pre = df[df[time] < treat_time]
    fake = treat_time - shift
    r = did(pre, y, unit, time, group_col, treat_time=fake, cluster=cluster)
    return {
        "fake_treat_time": fake,
        "estimate": r.estimate,
        "p_value": r.p_value,
        "passed": r.p_value >= alpha,
    }
