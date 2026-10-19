#!/usr/bin/env python3
"""주 분석: analysis-plan.yaml 을 계획이 정한 순서대로 계산한다(계획 보완 포함).

    python cases/hyun2-land-permit-spillover-2020/fetch.py           # 먼저 자료 받기
    python cases/hyun2-land-permit-spillover-2020/estimate.py pre    # 지정 전 단계
    python cases/hyun2-land-permit-spillover-2020/estimate.py post   # 지정 전후 비교

`pre` reads prices of months before 2020-06 only. Post-period months enter only as deal
counts and "this 동 × month cell has a deal", so the MDE uses the real cell layout. It
writes results/pre-period.json:
  - main · S1 · S2 · S3: MDE (power), event-study lead joint test and placebo onset
    2019-12 (pre_trend.checks), the «원래 흐름 차이 의심» label;
  - supplementary analyses: exposure_step placebo, within_complex placebo, diagnostics,
    past_placebo_years, linear_trends fit and holdout, trend_violation_bound's Δmax;
  - sha256 of every input, which `post` checks before it reads a price.

`post` refuses to run unless results/pre-period.json exists and was computed from the same
inputs. It writes results/post-period.json. That the pre stage came first is shown by the
git history: results/pre-period.json is committed before results/post-period.json.

Inputs: data/deals.csv.gz from fetch.py (not committed). Only numpy and pyyaml are used.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from statistics import NormalDist

import numpy as np
import yaml

HERE = Path(__file__).resolve().parent
PLAN = HERE / "analysis-plan.yaml"
DEALS = HERE / "data" / "deals.csv.gz"
RESULTS = HERE / "results"
PRE_RESULTS = RESULTS / "pre-period.json"
POST_RESULTS = RESULTS / "post-period.json"
FINGERPRINTED = ["analysis-plan.yaml", "fetch.py", "estimate.py", "data/deals.csv.gz"]

DISTRICT = {"강남": "11680", "서초": "11650", "송파": "11710"}
GROUPS = ("designated", "ring1", "ring2", "far")
TREATED = GROUPS[:3]  # far is the omitted group


def months(first: str, last: str) -> list[str]:
    return [
        f"{y}{m:02d}"
        for y in range(int(first[:4]), int(last[:4]) + 1)
        for m in range(1, 13)
        if first <= f"{y}{m:02d}" <= last
    ]


PRE = months("201906", "202005")
DROPPED = "202006"
POST = months("202007", "202103")
WINDOW = months("201906", "202103")
REFERENCE = "202005"  # event-study reference month
PLACEBO_ONSET = "201912"
PRICE_HIDDEN_FROM = "202006"  # the `pre` stage never reads a price from this month on
EXPOSURE_MONTHS = months("201906", "201911")
EXPOSURE_THRESHOLD = 150_000  # 만원 = 15억 (exposure_step)
PAST_YEARS = range(2015, 2020)  # past_placebo_years
TREND_FIT = months("201606", "202005")  # linear_trends
TREND_HOLDOUT_FIT = months("201606", "201905")
CALENDAR = {m: i for i, m in enumerate(months("201406", "202103"))}

SEED = 20261018
RI_DRAWS = 5_000
WILD_DRAWS = 9_999
ALPHA, POWER = 0.05, 0.80
LABEL_P = 0.10  # pre_trend.rule
M_BAR = (0.0, 0.5, 1.0, 2.0)  # trend_violation_bound
WEBB = np.array([-np.sqrt(1.5), -1.0, -np.sqrt(0.5), np.sqrt(0.5), 1.0, np.sqrt(1.5)])
CONTRASTS = {
    "direct": np.array([1.0, 0, 0]),
    "spillover": np.array([0, 1.0, 0]),
    "gradient": np.array([0, 1.0, -1.0]),
}


# ---------------------------------------------------------------- distributions


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the regularised incomplete beta (modified Lentz)."""
    tiny, qab, qap, qam = 1e-300, a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        for aa in (
            m * (b - m) * x / ((qam + m2) * (a + m2)),
            -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2)),
        ):
            d = 1 + aa * d
            d = 1 / (d if abs(d) > tiny else tiny)
            c = 1 + aa / c
            c = c if abs(c) > tiny else tiny
            h *= d * c
        if abs(d * c - 1) < 1e-14:
            break
    return h


def _betainc(a: float, b: float, x: float) -> float:
    if x <= 0 or x >= 1:
        return float(x >= 1)
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    )
    if x < (a + 1) / (a + b + 2):
        return front * _betacf(a, b, x) / a
    return 1 - front * _betacf(b, a, 1 - x) / b


def t_quantile(p: float, df: float) -> float:
    """Student t quantile by bisection on the CDF (p > 0.5)."""

    def cdf(t):
        return 1 - 0.5 * _betainc(df / 2, 0.5, df / (df + t * t))

    lo, hi = 0.0, 50.0
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if cdf(mid) < p else (lo, mid)
    return (lo + hi) / 2


def holm(pvalues: dict[str, float]) -> dict[str, float]:
    order = sorted(pvalues, key=pvalues.get)
    adjusted, running = {}, 0.0
    for i, name in enumerate(order):
        running = max(running, min(1.0, (len(order) - i) * pvalues[name]))
        adjusted[name] = running
    return adjusted


# ---------------------------------------------------------------- units and deals


def plan() -> dict:
    return yaml.safe_load(PLAN.read_text(encoding="utf-8"))


def plan_units() -> tuple[dict[tuple[str, str], str], set[tuple[str, str]]]:
    units_plan = plan()["units"]
    lists = {
        "designated": units_plan["designated"],
        "ring1": units_plan["ring1_adjacent"],
        "ring2": units_plan["ring2_next"],
        "far": units_plan["far_comparison"],
    }
    units = {}
    for group, names in lists.items():
        for name in names:
            gu, dong = name.split()
            units[(DISTRICT[gu], dong)] = group
    excluded = {(DISTRICT[n.split()[0]], n.split()[1]) for n in units_plan["ring2_without_deals"]}
    return units, excluded


@dataclass
class Deal:
    unit: tuple[str, str]
    month: str
    price: float | None  # 만원/m²; None where the stage may not read it
    amount: int | None  # 만원; None where the stage may not read it
    build_year: int | None
    complex: tuple[str, str, str, str]
    area: float
    floor: int | None
    cancelled: bool


def load_deals(post_prices: bool) -> list[Deal]:
    deals = []
    with gzip.open(DEALS, "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            month = f"{row['dealYear']}{int(row['dealMonth']):02d}"
            see = post_prices or month < PRICE_HIDDEN_FROM
            area = float(row["excluUseAr"])
            amount = int(row["dealAmount"].replace(",", "")) if see else None
            unit = (row["sggCd"], row["umdNm"].strip())
            floor = row["floor"].strip()
            deals.append(
                Deal(
                    unit,
                    month,
                    amount / area if see else None,
                    amount,
                    int(row["buildYear"]) if row["buildYear"].strip() else None,
                    (*unit, row["aptNm"].strip(), row["jibun"].strip()),
                    area,
                    int(float(floor)) if floor else None,
                    bool(row["cdealType"].strip()),
                )
            )
    return deals


def window_units(deals: list[Deal]) -> set[tuple[str, str]]:
    """법정동 with at least one deal report in the 22-month window (units.rule)."""
    return {d.unit for d in deals if d.month in WINDOW}


def specifications(deals: list[Deal]) -> dict:
    units, excluded = plan_units()
    present = window_units(deals)
    missing = sorted(u for u in units if u not in present)
    if missing:
        raise SystemExit(f"plan units without a deal in the window: {missing}")
    if excluded & present:
        raise SystemExit(f"ring2_without_deals now have deals: {sorted(excluded & present)}")
    # S2: keep every main unit and add the rest of Seoul as far (amendment correction).
    s2 = {**units, **{u: "far" for u in present if u not in units and u not in excluded}}
    s3 = {u: g for u, g in units.items() if u != ("11680", "율현동")}
    return {
        "main": (units, lambda d: True),
        "S1": (units, lambda d: d.build_year is None or d.build_year > 1990),
        "S2": (s2, lambda d: True),
        "S3": (s3, lambda d: True),
    }


# ---------------------------------------------------------------- designs


@dataclass
class Design:
    """Observations (cells or deals) with two absorbed FE, optional controls, 동 clusters."""

    units: list[tuple[str, str]]
    group: np.ndarray  # group index per 동
    obs_unit: np.ndarray  # 동 index per observation (also the cluster)
    obs_month: np.ndarray  # month string per observation
    fe_a: np.ndarray  # first absorbed FE per observation (동 for cells, complex for deals)
    y: np.ndarray  # nan where the price is not read
    controls: np.ndarray | None = None
    names: dict = field(default_factory=dict)


def cell_design(
    deals: list[Deal], assignment: dict, window: list[str], keep=lambda d: True
) -> Design:
    """동 × month cells: log of the median price per m² (outcome.construction)."""
    prices: dict[tuple, list] = {}
    for d in deals:
        if (
            d.unit in assignment
            and d.month in window
            and d.month != DROPPED
            and not d.cancelled
            and keep(d)
        ):
            prices.setdefault((d.unit, d.month), []).append(d.price)
    units = sorted({u for u, _ in prices})
    index = {u: i for i, u in enumerate(units)}
    keys = sorted(prices, key=lambda k: (index[k[0]], k[1]))
    y = np.array([np.nan if None in prices[k] else np.log(np.median(prices[k])) for k in keys])
    obs_unit = np.array([index[u] for u, _ in keys], dtype=int)
    return Design(
        units,
        np.array([GROUPS.index(assignment[u]) for u in units]),
        obs_unit,
        np.array([m for _, m in keys]),
        obs_unit.copy(),
        y,
    )


def deal_design(deals: list[Deal], assignment: dict, window: list[str]) -> Design:
    """within_complex: deal-level log price per m² with complex FE, log area and floor."""
    rows = [
        d
        for d in deals
        if d.unit in assignment
        and d.month in window
        and d.month != DROPPED
        and not d.cancelled
        and d.floor is not None
    ]
    units = sorted({d.unit for d in rows})
    index = {u: i for i, u in enumerate(units)}
    complexes = {c: i for i, c in enumerate(sorted({d.complex for d in rows}))}
    y = np.array([np.nan if d.price is None else np.log(d.price) for d in rows])
    controls = np.column_stack([np.log([d.area for d in rows]), [d.floor for d in rows]])
    return Design(
        units,
        np.array([GROUPS.index(assignment[u]) for u in units]),
        np.array([index[d.unit] for d in rows]),
        np.array([d.month for d in rows]),
        np.array([complexes[d.complex] for d in rows]),
        y,
        controls,
        {
            "complexes": len(complexes),
            "deals": len(rows),
            "dropped_empty_floor": sum(
                1
                for d in deals
                if d.unit in assignment
                and d.month in window
                and d.month != DROPPED
                and not d.cancelled
                and d.floor is None
            ),
        },
    )


def restrict(design: Design, keep_months: list[str]) -> Design:
    mask = np.isin(design.obs_month, keep_months)
    used = np.unique(design.obs_unit[mask])
    remap = -np.ones(len(design.units), dtype=int)
    remap[used] = np.arange(len(used))
    a_used = np.unique(design.fe_a[mask])
    a_remap = -np.ones(design.fe_a.max() + 1, dtype=int)
    a_remap[a_used] = np.arange(len(a_used))
    return Design(
        [design.units[i] for i in used],
        design.group[used],
        remap[design.obs_unit[mask]],
        design.obs_month[mask],
        a_remap[design.fe_a[mask]],
        design.y[mask],
        None if design.controls is None else design.controls[mask],
        dict(design.names),
    )


def with_controls(design: Design, controls: np.ndarray) -> Design:
    return Design(
        design.units,
        design.group,
        design.obs_unit,
        design.obs_month,
        design.fe_a,
        design.y,
        controls,
        dict(design.names),
    )


def describe(design: Design) -> dict:
    return {
        "units_per_group": {g: int(np.sum(design.group == i)) for i, g in enumerate(GROUPS)},
        "observations": int(len(design.y)),
        **design.names,
    }


# ---------------------------------------------------------------- projection


class Residualiser:
    """M z: residual of z on two absorbed FE (Frisch–Waugh–Lovell) and then on controls."""

    def __init__(self, design: Design):
        month_codes = {m: i for i, m in enumerate(sorted(set(design.obs_month)))}
        a = np.eye(design.fe_a.max() + 1)[design.fe_a]
        b = np.eye(len(month_codes))[[month_codes[m] for m in design.obs_month]]
        # Orthonormal basis of the FE columns from an SVD. pinv of the singular full-dummy Gram
        # was exact on these panels but lost ~0.005 on an unbalanced simulated panel
        # (pretrend_study.py), so the projection no longer goes through that Gram.
        u, s, _ = np.linalg.svd(np.hstack([a, b]), full_matrices=False)
        keep = s > s.max() * max(a.shape[0], a.shape[1] + b.shape[1]) * np.finfo(float).eps
        self.q = u[:, keep]
        self.rank = int(keep.sum())
        self.c = None
        if design.controls is not None:
            c = self._fe(design.controls)
            keep = np.linalg.norm(c, axis=0) > 1e-9  # a control absorbed by the FE drops out
            self.c = c[:, keep]
            self.c_pinv = np.linalg.pinv(self.c)
            self.rank += int(np.linalg.matrix_rank(self.c))

    def _fe(self, z: np.ndarray) -> np.ndarray:
        return z - self.q @ (self.q.T @ z)

    def __call__(self, z: np.ndarray) -> np.ndarray:
        r = self._fe(z)
        return r if self.c is None else r - self.c @ (self.c_pinv @ r)

    def rows(self, z: np.ndarray) -> np.ndarray:
        """Residualise each row of z (B × n)."""
        return self(z.T).T


def onehot3(group: np.ndarray) -> np.ndarray:
    return (group[:, None] == np.arange(3)[None, :]).astype(float)


def ols(mx: np.ndarray, my: np.ndarray):
    # pinv, not inv: in the Seoul-wide S2 panel a shuffled group of small 동 can have no cell
    # in some month, leaving a column empty; its coefficient is then 0.
    bread = np.linalg.pinv(mx.T @ mx)
    return bread @ mx.T @ my, bread


def shuffled_groups(group: np.ndarray, draws: int) -> np.ndarray:
    rng = np.random.default_rng(SEED)
    return np.array([rng.permutation(group) for _ in range(draws)])


def ri_p(observed: float, draws: np.ndarray) -> float:
    """Two-sided randomisation p counting the observed assignment: (1 + #{|b*| ≥ |b|}) / (1 + R)."""
    return float((1 + np.sum(np.abs(draws) >= abs(observed) - 1e-12)) / (1 + len(draws)))


def cr1(
    design: Design, resid_fn: Residualiser, mx: np.ndarray, bread: np.ndarray, resid: np.ndarray
) -> np.ndarray:
    g = len(design.units)
    n, k = mx.shape
    scores = np.zeros((g, k))
    np.add.at(scores, design.obs_unit, mx * resid[:, None])
    dof = g / (g - 1) * (n - 1) / (n - k - resid_fn.rank)
    return dof * bread @ scores.T @ scores @ bread


def did(design: Design, post_months: list[str], wild: bool = True) -> dict:
    """β_D, β_1, β_1 − β_2 with RI p (primary), CR1 CI (amendment) and wild cluster p.

    RI uses one residualised indicator per 동 (A[:, u] = M·1[obs in u, post]); a shuffled
    group's regressor is the sum of its 동's columns, so each draw costs a 3 × 3 solve.
    """
    m = Residualiser(design)
    my = m(design.y)
    post = np.isin(design.obs_month, post_months).astype(float)
    basis = m(np.eye(len(design.units))[design.obs_unit] * post[:, None])
    gram, cross = basis.T @ basis, basis.T @ my

    def beta_for(group):
        h = onehot3(group)
        return np.linalg.pinv(h.T @ gram @ h) @ (h.T @ cross)

    mx = basis @ onehot3(design.group)
    beta, bread = ols(mx, my)
    vcov = cr1(design, m, mx, bread, my - mx @ beta)
    draws = np.array([beta_for(g) for g in shuffled_groups(design.group, RI_DRAWS)])
    tq = t_quantile(1 - ALPHA / 2, len(design.units) - 1)
    out = {}
    for name, r in CONTRASTS.items():
        est, se = float(r @ beta), float(np.sqrt(r @ vcov @ r))
        out[name] = {
            "estimate": est,
            "ri_p": ri_p(est, draws @ r),
            "se_cr1": se,
            "ci95": [est - tq * se, est + tq * se],
        }
    if wild:
        wild_p = wild_cluster_p(design, m, mx, my, beta, bread)
        for name in CONTRASTS:
            out[name]["wild_p"] = wild_p[name]
    out["design"] = describe(design)
    return out


def wild_cluster_p(design, m, mx, my, beta, bread) -> dict:
    """Restricted wild cluster bootstrap-t (Webb weights, 동 clusters, CR1), per contrast."""
    rng = np.random.default_rng(SEED)
    clusters = design.obs_unit
    g = len(design.units)
    n, k = mx.shape
    dof = g / (g - 1) * (n - 1) / (n - k - m.rank)
    onehot = np.eye(g)[clusters]
    weights = WEBB[rng.integers(0, 6, size=(WILD_DRAWS, g))]

    def cr1_var(resid: np.ndarray) -> np.ndarray:  # resid: B × n
        scores = np.stack([(resid * mx[:, j]) @ onehot for j in range(k)], axis=2)
        meat = np.einsum("bgk,bgl->bkl", scores, scores)
        return dof * np.einsum("kl,blm,mn->bkn", bread, meat, bread)

    out = {}
    for name, r in CONTRASTS.items():
        basis = np.linalg.svd(r[None, :])[2][1:].T  # null space of r: imposes r·β = 0
        gamma = np.linalg.lstsq(mx @ basis, my, rcond=None)[0]
        fit_r = mx @ basis @ gamma
        resid_r = my - fit_r
        t_obs = (r @ beta) / np.sqrt(r @ cr1_var((my - mx @ beta)[None, :])[0] @ r)
        y_star = fit_r[None, :] + m.rows(weights[:, clusters] * resid_r[None, :])
        b_star = y_star @ (bread @ mx.T).T
        var_star = cr1_var(y_star - b_star @ mx.T)
        t_star = (b_star @ r) / np.sqrt(np.einsum("k,bkl,l->b", r, var_star, r))
        out[name] = float(np.mean(np.abs(t_star) >= abs(t_obs)))
    return out


def event_basis(design: Design, m: Residualiser, event_months: list[str]) -> np.ndarray:
    """Residualised 1[obs in 동 u, month = e] for every 동 u and event month e (U·E columns)."""
    unit_d = np.eye(len(design.units))[design.obs_unit]
    cols = [unit_d * (design.obs_month == e)[:, None] for e in event_months]
    return m(np.concatenate(cols, axis=1))  # column index = e·U + u


def event_regressors(basis: np.ndarray, group: np.ndarray, n_events: int) -> np.ndarray:
    """Columns ordered group-major: (designated, e1..eE), (ring1, ...), (ring2, ...)."""
    h = onehot3(group)
    blocks = basis.reshape(basis.shape[0], n_events, -1) @ h  # n × E × 3
    return blocks.transpose(0, 2, 1).reshape(basis.shape[0], -1)


def contrast_rows(n_events: int) -> dict[str, np.ndarray]:
    eye = np.eye(3 * n_events)
    return {
        "direct": eye[:n_events],
        "spillover": eye[n_events : 2 * n_events],
        "gradient": eye[n_events : 2 * n_events] - eye[2 * n_events :],
    }


# ---------------------------------------------------------------- pre-period checks


def lead_joint_test(pre: Design) -> dict:
    """Event-study leads 2019-06 .. 2020-04 on pre-period cells, reference 2020-05.

    Statistic per contrast: the leads' quadratic form under the homoskedastic OLS
    covariance; p from randomisation of the group labels (same draws as the primary).
    Every shuffle is computed from Gram matrices of one per-동 basis.
    """
    leads = [mo for mo in PRE if mo != REFERENCE]
    nl = len(leads)
    m = Residualiser(pre)
    my = m(pre.y)
    basis = event_basis(pre, m, leads)
    gram, cross, yy = basis.T @ basis, basis.T @ my, my @ my
    u = len(pre.units)
    dof = len(my) - m.rank - 3 * nl
    picks = contrast_rows(nl)

    gram4, cross2 = gram.reshape(nl, u, nl, u), cross.reshape(nl, u)

    def stats(group):
        h = onehot3(group)
        # basis column e·U + u → regressor (g, e): sum the Gram over the 동 of each group
        xx = np.einsum("eufv,ug,vh->gehf", gram4, h, h, optimize=True).reshape(3 * nl, 3 * nl)
        xy = (cross2 @ h).T.reshape(-1)
        bread = np.linalg.pinv(xx)
        beta = bread @ xy
        sigma2 = (yy - beta @ xy) / dof
        return {
            name: (
                float((r @ beta) @ np.linalg.pinv(sigma2 * r @ bread @ r.T) @ (r @ beta)),
                r @ beta,
            )
            for name, r in picks.items()
        }

    observed = stats(pre.group)
    draws = [stats(g) for g in shuffled_groups(pre.group, RI_DRAWS)]
    result = {}
    for name in picks:
        null = np.array([d[name][0] for d in draws])
        lead_values = list(map(float, observed[name][1]))
        path = lead_values + [0.0]  # reference month is 0
        result[name] = {
            "statistic": observed[name][0],
            "ri_p": float((1 + np.sum(null >= observed[name][0] - 1e-12)) / (1 + len(null))),
            "leads": dict(zip(leads, lead_values, strict=True)),
            "delta_max": float(np.max(np.abs(np.diff(path)))),  # trend_violation_bound
        }
    return result


def mde(layout: Design, pre: Design) -> dict:
    """MDE at 80% power, α = 0.05 (two-sided), from pre-period residual variance only.

    σ² and the lag-1 within-동 autocorrelation ρ come from the residuals of the two-way FE
    model fitted to pre-period cells. The standard error of each contrast is then the OLS
    sampling SE on the real 21-month cell layout under those errors: iid (σ²) and AR(1)
    (σ², ρ). The reported MDE is the larger of the two. Approximate: it assumes 동 are
    independent and share one error variance (plan review).
    """
    m_pre = Residualiser(pre)
    resid = m_pre(pre.y)
    sigma2 = float(resid @ resid / (len(resid) - m_pre.rank))
    by_cell = {
        (u, CALENDAR[mo]): e for u, mo, e in zip(pre.obs_unit, pre.obs_month, resid, strict=True)
    }
    pairs = np.array(
        [(e, by_cell[(u, t + 1)]) for (u, t), e in by_cell.items() if (u, t + 1) in by_cell]
    )
    rho = float(
        np.sum(pairs[:, 0] * pairs[:, 1])
        / np.sqrt(np.sum(pairs[:, 0] ** 2) * np.sum(pairs[:, 1] ** 2))
    )
    m = Residualiser(layout)
    post = np.isin(layout.obs_month, POST).astype(float)
    mx = m(onehot3(layout.group)[layout.obs_unit] * post[:, None])
    bread = np.linalg.pinv(mx.T @ mx)
    t = np.array([CALENDAR[mo] for mo in layout.obs_month])
    meat = np.zeros((3, 3))
    for u in range(len(layout.units)):  # AR(1) errors are independent across 동
        rows = layout.obs_unit == u
        block = sigma2 * rho ** np.abs(t[rows][:, None] - t[rows][None, :])
        meat += mx[rows].T @ block @ mx[rows]
    var_iid, var_ar = sigma2 * bread, bread @ meat @ bread
    z = NormalDist().inv_cdf(1 - ALPHA / 2) + NormalDist().inv_cdf(POWER)
    out = {
        "sigma2_pre": sigma2,
        "rho_pre": rho,
        "multiplier": z,
        "pre_cells": len(pre.y),
        "layout_cells": len(layout.y),
    }
    for name, r in CONTRASTS.items():
        se_iid, se_ar = float(np.sqrt(r @ var_iid @ r)), float(np.sqrt(r @ var_ar @ r))
        value = z * max(se_iid, se_ar)
        out[name] = {
            "se_iid": se_iid,
            "se_ar1": se_ar,
            "mde_log": value,
            "mde_pct": float(100 * (np.exp(value) - 1)),
        }
    return out


def exposure(deals: list[Deal]) -> dict[tuple[str, str], float]:
    """exposure_step: share of non-cancelled 2019-06..2019-11 deals above 15억, per 동."""
    counts: dict[tuple, list[int]] = {}
    for d in deals:
        if d.month in EXPOSURE_MONTHS and not d.cancelled:
            n = counts.setdefault(d.unit, [0, 0])
            n[0] += 1
            n[1] += d.amount > EXPOSURE_THRESHOLD
    return {u: k / n for u, (n, k) in counts.items()}


def exposure_controls(design: Design, share: dict, with_post: bool) -> np.ndarray:
    e = np.array([share.get(u, 0.0) for u in design.units])[design.obs_unit]
    cols = [e * (design.obs_month >= PLACEBO_ONSET)]
    if with_post:
        cols.append(e * np.isin(design.obs_month, POST))
    return np.column_stack(cols)


def diagnostics(deals: list[Deal], assignment: dict) -> dict:
    """diagnostics: counts only, per group × month of the window (2020-06 included)."""
    out = {g: {} for g in GROUPS}
    per_cell: dict[tuple, int] = {}
    for d in deals:
        if d.unit in assignment and d.month in WINDOW:
            row = out[assignment[d.unit]].setdefault(d.month, {"deals": 0, "cancelled": 0})
            row["cancelled" if d.cancelled else "deals"] += 1
            if not d.cancelled:
                per_cell[(d.unit, d.month)] = per_cell.get((d.unit, d.month), 0) + 1
    for g in GROUPS:
        members = [u for u, gg in assignment.items() if gg == g]
        for mo in WINDOW:
            row = out[g].setdefault(mo, {"deals": 0, "cancelled": 0})
            counts = [per_cell.get((u, mo), 0) for u in members]
            row["cells_0"] = sum(c == 0 for c in counts)
            row["cells_1_4"] = sum(1 <= c <= 4 for c in counts)
        out[g] = dict(sorted(out[g].items()))
    return out


def past_placebos(deals: list[Deal], assignment: dict) -> dict:
    """past_placebo_years: fake onset June Y, window (Y−1)-06..(Y+1)-03, June Y dropped."""
    out = {}
    for year in PAST_YEARS:
        pre_m = months(f"{year - 1}06", f"{year}05")
        post_m = months(f"{year}07", f"{year + 1}03")
        design = cell_design(deals, assignment, pre_m + post_m)
        result = did(design, post_m, wild=False)
        out[str(year)] = {
            c: {k: result[c][k] for k in ("estimate", "ri_p", "ci95")} for c in CONTRASTS
        }
        out[str(year)]["design"] = result["design"]
    return out


def trend_fit(design: Design) -> np.ndarray:
    """linear_trends: group-specific linear trends (designated, ring1, ring2 relative to far)."""
    m = Residualiser(design)
    t = np.array([CALENDAR[mo] for mo in design.obs_month], dtype=float)
    x = onehot3(design.group)[design.obs_unit] * t[:, None]
    return ols(m(x), m(design.y))[0]


def detrend(design: Design, gamma: np.ndarray) -> Design:
    t = np.array([CALENDAR[mo] for mo in design.obs_month], dtype=float)
    shift = (onehot3(design.group)[design.obs_unit] * t[:, None]) @ gamma
    return Design(
        design.units,
        design.group,
        design.obs_unit,
        design.obs_month,
        design.fe_a,
        design.y - shift,
        design.controls,
        dict(design.names),
    )


def fingerprint() -> dict[str, str]:
    """sha256 of every input. analysis-plan.yaml is hashed without `disclosures`, which only
    ever grows by an appended line recording what a run printed, so recording the pre run
    does not invalidate the pre run."""
    out = {}
    for name in FINGERPRINTED:
        data = (HERE / name).read_bytes()
        if name == "analysis-plan.yaml":
            content = {k: v for k, v in yaml.safe_load(data).items() if k != "disclosures"}
            data = json.dumps(content, ensure_ascii=False, sort_keys=True).encode("utf-8")
        out[name] = hashlib.sha256(data).hexdigest()
    return out


def run_pre() -> dict:
    deals = load_deals(post_prices=False)
    specs = specifications(deals)
    results: dict = {"specifications": {}}
    for name, (assignment, keep) in specs.items():
        layout = cell_design(deals, assignment, WINDOW, keep)
        pre = restrict(layout, PRE)
        # A 동 with deals only after 2020-05 has no pre cell. It stays in the MDE layout (its
        # unit FE absorbs it; it only moves post month FE) but cannot enter the pre checks.
        post_only = [" ".join(u) for u in layout.units if u not in set(pre.units)]
        placebo = did(pre, [mo for mo in PRE if mo >= PLACEBO_ONSET])
        leads = lead_joint_test(pre)
        labels = {
            c: bool(leads[c]["ri_p"] < LABEL_P or placebo[c]["ri_p"] < LABEL_P) for c in CONTRASTS
        }
        results["specifications"][name] = {
            "design": {
                **describe(layout),
                "pre_checks": describe(pre),
                "post_only_units": post_only,
            },
            "mde": mde(layout, pre),
            "lead_joint_test": leads,
            "placebo_2019_12": placebo,
            "label_원래_흐름_차이_의심": labels,
        }
        print(f"{name}: {describe(layout)}  labels {labels}", flush=True)

    units = specs["main"][0]
    share = exposure(deals)
    pre_cells = cell_design(deals, units, PRE)
    placebo_post = [mo for mo in PRE if mo >= PLACEBO_ONSET]
    results["exposure_share_15eok"] = {" ".join(u): share.get(u) for u in sorted(units)}
    results["exposure_step_placebo_2019_12"] = did(
        with_controls(pre_cells, exposure_controls(pre_cells, share, False)),
        placebo_post,
        wild=False,
    )
    results["within_complex_placebo_2019_12"] = did(
        deal_design(deals, units, PRE), placebo_post, wild=False
    )
    results["diagnostics"] = diagnostics(deals, units)
    results["past_placebo_years"] = past_placebos(deals, units)
    gamma_hold = trend_fit(cell_design(deals, units, TREND_HOLDOUT_FIT))
    holdout = detrend(cell_design(deals, units, TREND_HOLDOUT_FIT + PRE), gamma_hold)
    results["linear_trends"] = {
        "gamma_per_month": dict(
            zip(TREATED, map(float, trend_fit(cell_design(deals, units, TREND_FIT))), strict=True)
        ),
        "holdout_gamma_per_month": dict(zip(TREATED, map(float, gamma_hold), strict=True)),
        "holdout_2019_06_to_2020_05": did(holdout, PRE, wild=False),
    }
    print("supplementary pre-period analyses done", flush=True)
    return results


# ---------------------------------------------------------------- post-period contrast


def require_pre() -> dict:
    """The post stage reads prices only after the pre stage ran on the same inputs."""
    if not PRE_RESULTS.exists():
        raise SystemExit("run `estimate.py pre` first: results/pre-period.json is missing")
    recorded = json.loads(PRE_RESULTS.read_text(encoding="utf-8"))
    now = fingerprint()
    changed = [k for k, v in recorded["inputs_sha256"].items() if now.get(k) != v]
    if changed:
        raise SystemExit(f"inputs changed since results/pre-period.json: {changed}; rerun pre")
    return recorded


def event_study(design: Design, event_months: list[str]) -> tuple[np.ndarray, np.ndarray]:
    m = Residualiser(design)
    mx = event_regressors(event_basis(design, m, event_months), design.group, len(event_months))
    my = m(design.y)
    beta, bread = ols(mx, my)
    return beta, cr1(design, m, mx, bread, my - mx @ beta)


def trend_bound(design: Design, deltas: dict[str, float]) -> dict:
    """trend_violation_bound: θ = mean post event-study coefficient; |bias| ≤ M̄·Δmax·mean k."""
    events = [mo for mo in PRE + POST if mo != REFERENCE]
    beta, vcov = event_study(design, events)
    rows = contrast_rows(len(events))
    post_idx = [i for i, mo in enumerate(events) if mo in POST]
    mean_k = float(np.mean([CALENDAR[mo] - CALENDAR[REFERENCE] for mo in POST]))
    tq = t_quantile(1 - ALPHA / 2, len(design.units) - 1)
    n_ev = len(events)
    out = {
        "event_study": {
            g: dict(zip(events, map(float, beta[i * n_ev : (i + 1) * n_ev]), strict=True))
            for i, g in enumerate(TREATED)
        },
        "mean_k": mean_k,
    }
    for name, r in rows.items():
        w = r[post_idx].mean(axis=0)
        theta, se = float(w @ beta), float(np.sqrt(w @ vcov @ w))
        slack = deltas[name] * mean_k
        out[name] = {
            "theta": theta,
            "se_cr1": se,
            "delta_max": deltas[name],
            "intervals": {
                str(mb): [theta - tq * se - mb * slack, theta + tq * se + mb * slack]
                for mb in M_BAR
            },
            "breakdown_m_bar": float(max(0.0, abs(theta) - tq * se) / slack) if slack else None,
        }
    return out


def classify(main: dict, mde_values: dict) -> dict:
    """analysis-plan.yaml amendment supersedes_conclusion_rule."""
    holm_p = holm({c: main[c]["ri_p"] for c in CONTRASTS})
    verdicts = {}
    for c in CONTRASTS:
        est, (lo, hi), bound = main[c]["estimate"], main[c]["ci95"], mde_values[c]["mde_log"]
        if holm_p[c] < ALPHA:
            verdicts[c] = "양(+)의 차이" if est > 0 else "음(−)의 차이"
        elif -bound < lo and hi < bound:
            verdicts[c] = "MDE 이상 효과 배제"
        else:
            verdicts[c] = "판별 불가"
    b = (
        main["spillover"]["estimate"] > 0
        and holm_p["spillover"] < ALPHA
        and main["gradient"]["estimate"] >= 0
    )  # β_1 ≥ β_2
    a = (
        main["direct"]["estimate"] < 0
        and holm_p["direct"] < ALPHA
        and verdicts["spillover"] == "MDE 이상 효과 배제"
    )
    lo, hi = main["gradient"]["ci95"]
    return {
        "holm_ri_p": holm_p,
        "verdicts": verdicts,
        "B_supported": bool(b),
        "A_supported": bool(a),
        "gradient_확인": bool(lo > 0 or hi < 0),
    }


def run_post() -> dict:
    recorded = require_pre()
    pre_specs = recorded["results"]["specifications"]
    deals = load_deals(post_prices=True)
    specs = specifications(deals)
    results: dict = {"specifications": {}}
    for name, (assignment, keep) in specs.items():
        results["specifications"][name] = did(cell_design(deals, assignment, WINDOW, keep), POST)
        print(f"{name}: done", flush=True)
    units = specs["main"][0]
    main_cells = cell_design(deals, units, WINDOW)
    share = {
        tuple(k.split()): v or 0.0 for k, v in recorded["results"]["exposure_share_15eok"].items()
    }
    results["conclusion"] = classify(results["specifications"]["main"], pre_specs["main"]["mde"])
    results["exposure_step"] = did(
        with_controls(main_cells, exposure_controls(main_cells, share, False)), POST, wild=False
    )
    results["exposure_step_and_post"] = did(
        with_controls(main_cells, exposure_controls(main_cells, share, True)), POST, wild=False
    )
    results["within_complex"] = did(deal_design(deals, units, WINDOW), POST, wild=False)
    gamma = np.array([recorded["results"]["linear_trends"]["gamma_per_month"][g] for g in TREATED])
    results["linear_trends"] = did(detrend(main_cells, gamma), POST, wild=False)
    results["trend_violation_bound"] = trend_bound(
        main_cells, {c: pre_specs["main"]["lead_joint_test"][c]["delta_max"] for c in CONTRASTS}
    )
    actual = {c: results["specifications"]["main"][c]["estimate"] for c in CONTRASTS}
    past = recorded["results"]["past_placebo_years"]
    results["past_placebo_years_benchmark"] = {
        c: {
            "years_with_abs_ge_actual": sum(
                abs(past[y][c]["estimate"]) >= abs(actual[c]) for y in past
            ),
            "years": len(past),
        }
        for c in CONTRASTS
    }
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["pre", "post"])
    stage = parser.parse_args().stage
    results = run_pre() if stage == "pre" else run_post()
    RESULTS.mkdir(exist_ok=True)
    path = PRE_RESULTS if stage == "pre" else POST_RESULTS
    payload = {
        "seed": SEED,
        "ri_draws": RI_DRAWS,
        "wild_draws": WILD_DRAWS,
        "inputs_sha256": fingerprint(),
        "results": results,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(HERE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
