"""무작위화 추론: 가능한 가짜 배정이 적으면 전부 계산하고, p값이 1/(배정 수+1) 아래로 내려가지 않는다."""

import math

import numpy as np
import pandas as pd

from core.estimators.ri import did_ri, event_study_ri, placebo_sets


def _panel(n_units: int, effect: float = 1.0, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for u in range(n_units):
        for t in range(10):
            y = 0.1 * u + 0.05 * t + rng.normal(0, 0.05) + (effect if u == 0 and t >= 5 else 0)
            rows.append({"u": u, "t": t, "y": y})
    return pd.DataFrame(rows)


def test_exact_enumeration_when_few_controls():
    sets, exact = placebo_sets(np.arange(5), 1, 999, np.random.default_rng(0))
    assert exact and len(sets) == 5 and len({frozenset(s) for s in sets}) == 5
    sets, exact = placebo_sets(np.arange(30), 3, 999, np.random.default_rng(0))
    assert not exact and len(sets) == 999


def test_p_value_floor_with_one_treated_and_five_controls():
    df = _panel(6, effect=5.0)  # 아주 큰 효과여도
    r = did_ri(df, "y", "u", "t", {0}, 5)
    assert r["exact"] and r["n_assignments"] == 5
    assert math.isclose(r["p"], 1 / 6)  # 예전 구현은 999번 중복 추첨으로 0.001 이 나왔다
    assert r["ci"] == (-math.inf, math.inf)  # 5% 에서 어떤 크기도 배제할 수 없음
    es = event_study_ri(df, "y", "u", "t", {0}, 5, [-3, -2, 0, 1, 2], -3, 2)
    assert math.isclose(es["p_post"], 1 / 6) and es["p_pretrend"] >= 1 / 6
    assert es["ci"] == (-math.inf, math.inf)


def test_enough_controls_gives_finite_interval():
    df = _panel(25, effect=1.0)
    r = did_ri(df, "y", "u", "t", {0}, 5)
    assert r["exact"] and r["n_assignments"] == 24 and math.isclose(r["p"], 1 / 25)
    lo, hi = r["ci"]
    assert math.isfinite(lo) and math.isfinite(hi) and lo > 0
