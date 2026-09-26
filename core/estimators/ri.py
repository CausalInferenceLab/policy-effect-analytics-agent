"""처치 단위가 적을 때의 무작위화 추론(randomization inference, placebo-in-space).

처치 클러스터가 몇 개뿐이면(예: 서울 25개 구 중 4개) 군집-강건 표준오차는 크게 과소추정되고,
사전추세 Wald 검정은 귀무가설이 참이어도 절반 이상 기각한다(MacKinnon & Webb 2017).
대신 "처치를 받은 단위 집합"을 무작위로 바꿔 가며 같은 이벤트 스터디를 반복해 분포를 만든다.

- 균형 패널 + 동시 도입일 때만 사용한다(양방향 고정효과를 평균 빼기로 정확히 제거 가능).
- 가짜 처치 단위는 실제 처치 단위를 뺀 대조군에서만 뽑는다(placebo-in-space, Abadie et al. 2010).
- 통계량: 사전 = 사전 계수 제곱합, 사후 = 사후 계수 평균.
- 신뢰구간: 사후 평균효과에 대한 검정 역산(test inversion).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _twoway_demean(a: np.ndarray, u: np.ndarray, t: np.ndarray) -> np.ndarray:
    """균형 패널에서 unit·time 고정효과 제거 (a: n x k)."""
    df = pd.DataFrame(a)
    return (
        a
        - df.groupby(u).transform("mean").to_numpy()
        - df.groupby(t).transform("mean").to_numpy()
        + a.mean(axis=0)
    )


def _dummies(rel: np.ndarray, treated_row: np.ndarray, ks: list[int]) -> np.ndarray:
    return np.column_stack([(treated_row & (rel == k)).astype(float) for k in ks])


def event_study_ri(
    df: pd.DataFrame,
    y: str,
    unit: str,
    time: str,
    treated_units: set,
    treat_time: int,
    ks: list[int],
    lo: int,
    hi: int,
    alpha: float = 0.05,
    n_perm: int = 999,
    seed: int = 0,
) -> dict:
    u = df[unit].to_numpy()
    t = df[time].to_numpy()
    rel = np.clip(t - treat_time, lo, hi)
    pool = np.array([x for x in np.unique(u) if x not in treated_units])
    k_tr = len(treated_units)
    pre = np.array([k < 0 for k in ks])
    post = ~pre
    w = post / post.sum()
    yd = _twoway_demean(df[[y]].to_numpy(float), u, t)[:, 0]
    # 실제 처치 단위의 사후 지시변수 — H0(효과=δ)에서 y(0) = y − δ·D_obs 로 보정할 때 쓴다
    d_obs = _twoway_demean(
        (np.isin(u, list(treated_units)) & (t >= treat_time)).astype(float)[:, None], u, t
    )[:, 0]

    def coefs(tr_set) -> tuple[np.ndarray, np.ndarray]:
        tr_row = np.isin(u, list(tr_set))
        Xd = _twoway_demean(_dummies(rel, tr_row, ks), u, t)
        a = w @ np.linalg.pinv(Xd)  # 사후 평균효과 = a · y (선형 범함수)
        beta = np.linalg.lstsq(Xd, yd, rcond=None)[0]
        return beta, np.array([a @ yd, a @ d_obs])

    b_obs, (m_obs, c_obs) = coefs(treated_units)
    s_pre_obs = float(np.sum(b_obs[pre] ** 2))
    rng = np.random.default_rng(seed)
    s_pre, m, c = np.empty(n_perm), np.empty(n_perm), np.empty(n_perm)
    for i in range(n_perm):
        b, (m[i], c[i]) = coefs(set(rng.choice(pool, k_tr, replace=False)))
        s_pre[i] = np.sum(b[pre] ** 2)

    p_pre = float((1 + np.sum(s_pre >= s_pre_obs)) / (n_perm + 1))
    p_post = float((1 + np.sum(np.abs(m) >= abs(m_obs))) / (n_perm + 1))
    # 검정 역산: H0 효과=δ 에서 관측·순열 통계량을 δ 만큼 보정해 p(δ) > alpha 인 δ 의 범위
    spread = max(np.std(m), abs(m_obs), 1e-9)
    grid = np.linspace(m_obs - 6 * spread, m_obs + 6 * spread, 481)
    obs = np.abs(m_obs - grid * c_obs)
    perm = np.abs(m[:, None] - grid[None, :] * c[:, None])
    p_grid = (1 + (perm >= obs[None, :]).sum(axis=0)) / (n_perm + 1)
    keep = grid[p_grid > alpha]
    ci = (float(keep.min()), float(keep.max())) if keep.size else (float("nan"), float("nan"))
    return {
        "method": f"randomization inference (처치 단위 {k_tr}개를 무작위 재배정, {n_perm}회)",
        "estimate": float(m_obs),
        "p_post": p_post,
        "p_pretrend": p_pre,
        "ci": ci,
    }


def did_ri(
    df: pd.DataFrame,
    y: str,
    unit: str,
    time: str,
    treated_units: set,
    treat_time: int,
    alpha: float = 0.05,
    n_perm: int = 999,
    seed: int = 0,
) -> dict:
    """2x2/동시 도입 TWFE DiD 계수에 대한 무작위화 추론 (p값, 검정 역산 신뢰구간)."""
    u = df[unit].to_numpy()
    t = df[time].to_numpy()
    pool = np.array([x for x in np.unique(u) if x not in treated_units])
    yd = _twoway_demean(df[[y]].to_numpy(float), u, t)[:, 0]

    def dd(tr_set) -> np.ndarray:
        return _twoway_demean(
            (np.isin(u, list(tr_set)) & (t >= treat_time)).astype(float)[:, None], u, t
        )[:, 0]

    d_obs = dd(treated_units)
    b_obs = float(d_obs @ yd / (d_obs @ d_obs))
    rng = np.random.default_rng(seed)
    m, c = np.empty(n_perm), np.empty(n_perm)
    for i in range(n_perm):
        dp = dd(set(rng.choice(pool, len(treated_units), replace=False)))
        m[i], c[i] = dp @ yd / (dp @ dp), dp @ d_obs / (dp @ dp)
    p = float((1 + np.sum(np.abs(m) >= abs(b_obs))) / (n_perm + 1))
    spread = max(np.std(m), abs(b_obs), 1e-9)
    grid = np.linspace(b_obs - 6 * spread, b_obs + 6 * spread, 481)
    obs = np.abs(b_obs - grid)
    p_grid = (1 + (np.abs(m[:, None] - grid[None, :] * c[:, None]) >= obs[None, :]).sum(0)) / (
        n_perm + 1
    )
    keep = grid[p_grid > alpha]
    ci = (float(keep.min()), float(keep.max())) if keep.size else (float("nan"), float("nan"))
    return {"estimate": b_obs, "p": p, "ci": ci}
