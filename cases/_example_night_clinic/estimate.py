"""plan.yaml → 추정 → 그림 → report.md

실행: python cases/_example_night_clinic/estimate.py   (먼저 fetch.py)
"""

import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from core.estimators import apply_abstention, did  # noqa: E402
from core.pipeline import run_plan  # noqa: E402
from core.report import event_study_plot, raw_trends, render_report  # noqa: E402
from core.schema.plan import load_plan  # noqa: E402


def main():
    plan = load_plan(HERE / "plan.yaml")
    df = pd.read_csv(HERE / "data" / "panel.csv")
    y = plan.primary_outcome.col

    results = run_plan(plan, df)  # event study (+ placebo, abstention)
    es = results[0]
    # 보조: 단일 계수 DiD 도 함께 보고
    kw = dict(
        unit=plan.unit.id_col,
        time=plan.time.col,
        group_col=plan.treatment.group_col,
        treat_time=plan.treatment.treat_time,
        cluster=plan.estimator.cluster_col,
    )
    results.append(apply_abstention(did(df, y, **kw), plan.abstention, plan.thresholds))

    fig_dir = HERE / "figures"
    fig_dir.mkdir(exist_ok=True)
    raw_trends(
        df,
        y,
        plan.time.col,
        plan.treatment.group_col,
        plan.treatment.treat_time,
        fig_dir / "raw_trends.png",
        ylabel="Night ED visits per 1,000 children (SYNTHETIC)",
    )
    event_study_plot(es.extra["coefs"], fig_dir / "event_study.png")

    pt = es.assumptions_checked["parallel_pretrends"]
    pl = es.assumptions_checked.get("placebo_time", {})
    checks = {
        "평행추세": f"사전계수 결합 Wald p={pt['p_value']:.3f} → {'통과' if pt['passed'] else '기각'}",
        "도입시점 외생성": (
            f"가짜 도입({pl['fake_treat_time']}) 추정 {pl['estimate']:.3f}, "
            f"p={pl['p_value']:.3f} → {'통과' if pl['passed'] else '실패'}"
        )
        if pl
        else "미실시",
    }
    md = render_report(
        plan,
        results,
        {"Raw trends": "figures/raw_trends.png", "Event study": "figures/event_study.png"},
        checks,
    )
    (HERE / "report.md").write_text(md, encoding="utf-8")
    (HERE / "results.json").write_text(
        json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2, default=float),
        "utf-8",
    )
    for r in results:
        print(r.summary_ko())


if __name__ == "__main__":
    main()
