"""② 수집: 서울 25개 자치구 × 월(2024-01 ~ 2025-09) 패널 → data/panel.csv

- plan.yaml 의 첫 번째 data_source 가 molit 이고 DATA_GO_KR_API_KEY 가 있으면 실데이터를 받는다.
- 그렇지 않으면 **시뮬레이션** 패널을 만든다(실데이터 아님, 파이프라인 시연용).
- 2025-03(month_idx 14)은 지정 효력일(3.24)이 월 중간이라 전환월로 보고 뺀다.
"""

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from core.adapters.base import SourceMeta  # noqa: E402
from core.adapters.molit import SEOUL_GU, MolitAptTradeAdapter, to_gu_month_panel  # noqa: E402
from core.adapters.synthetic import SyntheticAdapter  # noqa: E402

START, END = "2024-01", "2025-09"
TREATED = {"11650", "11680", "11710", "11170"}  # 서초·강남·송파·용산
TRANSITION = 14  # 2025-03


def simulate(seed: int = 7, effect: float = -0.40) -> pd.DataFrame:
    """자치구 고정효과 + 공통 월 충격 + 처치 후 거래량 효과(임의값). 가격 효과는 0."""
    rng = np.random.default_rng(seed)
    months = pd.period_range(START, END, freq="M")
    shock = np.cumsum(rng.normal(0.02, 0.05, len(months)))
    rows = []
    for code in SEOUL_GU:
        a_t, a_p = rng.normal(5.0, 0.5), rng.normal(16.3, 0.3)
        for i, m in enumerate(months):
            d = code in TREATED and i >= 15
            rows.append(
                {
                    "gu_code": code,
                    "ym": m.strftime("%Y%m"),
                    "month_idx": i,
                    "log_trades": a_t + shock[i] + effect * d + rng.normal(0, 0.08),
                    "log_price_m2": a_p + 0.3 * shock[i] + rng.normal(0, 0.02),
                }
            )
    return pd.DataFrame(rows)


def main():
    plan = yaml.safe_load((HERE / "plan.yaml").read_text(encoding="utf-8"))
    real = plan["data_sources"][0].get("adapter") == "molit" and os.getenv("DATA_GO_KR_API_KEY")
    if real:
        ad = MolitAptTradeAdapter()
        panel = to_gu_month_panel(ad.fetch(START, END), START)
        panel["log_trades"] = np.log1p(panel["trades"])
        panel["log_price_m2"] = np.log(panel["price_m2_median"])
        meta, query = ad.meta, {"start": START, "end": END}
    else:
        panel = simulate()
        meta = SourceMeta(
            "시뮬레이션 자치구×월 패널 (실데이터 아님)", "core.adapters.synthetic", "synthetic"
        )
        query = {"seed": 7, "note": "API 키 없음 → 시뮬레이션"}
    panel["gu_name"] = panel["gu_code"].map(SEOUL_GU)
    panel["treated"] = panel["gu_code"].isin(TREATED).astype(int)
    panel = panel[panel["month_idx"] != TRANSITION].sort_values(["gu_code", "month_idx"])
    ad = SyntheticAdapter()
    ad.meta = meta
    out = ad.save(panel.reset_index(drop=True), HERE / "data" / "panel.csv", query)
    print(
        f"{'실데이터' if real else '시뮬레이션'} 패널 저장: {out.relative_to(HERE)} ({len(panel)}행)"
    )


if __name__ == "__main__":
    main()
