"""처치 단위가 적을 때(4/25) 추론이 명목 수준을 지키는지 — CRV1 은 여기서 크게 과대기각한다."""

import numpy as np
import pandas as pd

from core.estimators import did, event_study


def _panel(seed, effect=-0.4, n=25, k=4, months=20, treat=14):
    rng = np.random.default_rng(seed)
    shock = np.cumsum(rng.normal(0, 0.05, months))
    rows = []
    for i in range(n):
        a = rng.normal(5, 0.5)
        for t in range(months):
            d = i < k and t >= treat
            rows.append(
                (f"G{i:02d}", t, int(i < k), a + shock[t] + effect * d + rng.normal(0, 0.08))
            )
    return pd.DataFrame(rows, columns=["g", "t", "treated", "y"])


KW = dict(unit="g", time="t", group_col="treated", treat_time=14, cluster="g")


def test_few_treated_uses_randomization_inference():
    r = event_study(_panel(1), "y", ref_period=-1, window=(-6, 5), **KW)
    assert "few_treated_clusters" in r.triggers
    assert "randomization" in r.assumptions_checked["inference"]
    assert r.ci_low <= -0.4 <= r.ci_high
    assert r.assumptions_checked["parallel_pretrends"]["passed"]


def test_did_ri_covers_truth_and_placebo_null():
    r = did(_panel(2), "y", **KW)
    assert r.ci_low <= -0.4 <= r.ci_high and r.p_value < 0.05
    null = did(_panel(3, effect=0.0), "y", **KW)
    assert null.ci_low <= 0 <= null.ci_high
