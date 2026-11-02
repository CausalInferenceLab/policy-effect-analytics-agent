"""공통 실행기 결과를 보완하는 추정을 같은 plan.yaml 설정으로 돌린다 → extra_checks.json

- complete_case: 지표마다 33개월 모두 값이 있는 기관만 남겨 다시 추정한다. core 의 무작위화 추론
  (core/estimators/ri.py)이 결과변수 결측을 걸러내지 않아, 결측 칸이 있으면 통계량이 모두 NaN 이 되고
  p 가 최솟값 1/(배정 수+1)에 붙으며 신뢰구간이 nan 으로 나온다. 균형 패널로 맞추면 그 문제가 없다.
- placebo_outcome: 월별 보도자료 건수(releases, 로그). 문서 형식 지침이 건수까지 바꿀 이유는 없다.
- drop_unit_msit: 과학기술정보통신부를 뺀 패널(data/panel_no_msit.csv)로 complete_case 를 다시 한다.

실행: make flow 뒤에  python cases/gyeom-yee-public-markdown/extra_checks.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from core.pipeline import run_plan  # noqa: E402
from core.schema.plan import Outcome, load_plan  # noqa: E402


def _row(r, n_units: int) -> dict:
    a = r.assumptions_checked
    coefs = r.extra["coefs"]
    return {
        "outcome": r.outcome,
        "n_units": n_units,
        "estimate": r.estimate,
        "ci": [r.ci_low, r.ci_high],
        "p_value": r.p_value,
        "pretrend_p": a["parallel_pretrends"]["p_value"],
        "placebo_time": {k: a["placebo_time"].get(k) for k in ("estimate", "p_value", "passed")},
        "post_coefs": {
            int(k): float(c)
            for k, c in zip(coefs["rel_time"], coefs["coef"], strict=True)
            if k >= 0
        },
        "verdict": r.verdict,
        "triggers": r.triggers,
    }


def complete_case(plan, df: pd.DataFrame) -> list[dict]:
    """지표마다 결측 없는 기관만으로 균형 패널을 만들어 추정한다."""
    rows = []
    for o in plan.outcomes:
        full = df.groupby("org_id")[o.col].transform(lambda s: s.notna().all())
        sub = df[full]
        (r,) = run_plan(plan.model_copy(update={"outcomes": [o]}), sub)
        rows.append(_row(r, sub["org_id"].nunique()))
    return rows


def main() -> None:
    plan = load_plan(HERE / "plan.yaml")
    df = pd.read_csv(HERE / "data" / "panel.csv")
    df["log_releases"] = np.log1p(df["releases"])
    placebo = plan.model_copy(
        update={
            "outcomes": [
                Outcome(
                    name="월별 보도자료 건수(로그)",
                    col="log_releases",
                    definition="log(1+releases)",
                )
            ]
        }
    )
    no_msit = pd.read_csv(HERE / "data" / "panel_no_msit.csv")
    out = {
        "complete_case": complete_case(plan, df),
        "placebo_outcome": complete_case(placebo, df),
        "drop_unit_msit": complete_case(plan, no_msit),
        "md_attach_share_max": float(df["md_attach_share"].max()),
    }
    (HERE / "extra_checks.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=float), encoding="utf-8"
    )
    for k, rows in out.items():
        if not isinstance(rows, list):
            print(k, rows)
            continue
        for r in rows:
            print(
                f"{k:16} {r['outcome']:20} n={r['n_units']:2} est={r['estimate']:+.4f} "
                f"ci=[{r['ci'][0]:+.4f}, {r['ci'][1]:+.4f}] p={r['p_value']:.3f} "
                f"pre_p={r['pretrend_p']:.3f} placebo_p={r['placebo_time']['p_value']:.3f} "
                f"{r['verdict']} {r['triggers']}"
            )


if __name__ == "__main__":
    main()
