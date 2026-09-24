"""합성 패널 생성기 — 테스트·예제·교육용. 실데이터 아님!

참값(true effect)을 알고 있는 데이터로 추정기가 제대로 복원하는지, 경고가 제대로
뜨는지 검증한다. `pretrend_slope` 를 주면 처치집단에만 사전 추세 차이를 심어
평행추세 위반 상황을 재현할 수 있다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import BaseAdapter, SourceMeta


def simulate_panel(
    n_units: int = 80,
    n_treated: int = 30,
    start: int = 2012,
    end: int = 2019,
    treat_time: int = 2016,
    effect: float = -5.0,
    pretrend_slope: float = 0.0,
    staggered: bool = False,
    base: float = 50.0,
    noise: float = 2.0,
    seed: int = 0,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    years = np.arange(start, end + 1)
    units = np.arange(n_units)
    treated = units < n_treated
    ft = np.where(treated, treat_time, np.nan)
    if staggered:  # 처치집단을 3개 코호트로 분할
        ft = np.where(treated, treat_time + (units % 3) - 1, np.nan)
    alpha = rng.normal(base, 5, n_units)  # 단위 고정효과
    gamma = np.cumsum(rng.normal(0.5, 0.3, len(years)))  # 공통 연도 충격
    rows = []
    for i in units:
        for j, t in enumerate(years):
            d = int(treated[i] and t >= ft[i])
            y = (
                alpha[i]
                + gamma[j]
                + effect * d
                + (pretrend_slope * (t - treat_time) if treated[i] else 0.0)
                + rng.normal(0, noise)
            )
            rows.append((f"R{i:03d}", t, int(treated[i]), ft[i], y))
    return pd.DataFrame(rows, columns=["region_id", "year", "treated", "first_treat", "y"])


class SyntheticAdapter(BaseAdapter):
    meta = SourceMeta(
        name="합성 패널 (simulate_panel)", provider="core.adapters.synthetic", license="synthetic"
    )

    def fetch(self, **kw) -> pd.DataFrame:
        return simulate_panel(**kw)
