"""강남역 두 구간의 같은 공통 셀에서 시간·운행·승차의 동시 변화를 비교한다."""

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .common import CASE, sha256, utcnow, write_json  # noqa: E402
from .overnight_operations_plots import style  # noqa: E402

OUT = CASE / "results/overnight/segment_operations"


def run():
    style()
    data = pd.read_csv(OUT / "comparisons.csv", dtype={"from_ars": str, "to_ars": str})
    data = data[data.endpoint.eq("arrival")]
    order = ["time", "trips", "boardings", "boardings_per_recorded_trip"]
    fig, axes = plt.subplots(1, 2, figsize=(13, 6), sharey=True)
    for ax, ars, title in zip(axes, ["22011", "22008"], ["남행 22011→22009 · 40셀/14노선", "북행 22008→22010 · 37셀/13노선"], strict=True):
        for offset, comparison, name, color in [(-.24, "summer2024", "2024 여름", "#8a9eac"),
                                                (0., "pre_year_over_year", "2025 사전", "#cc784a"),
                                                (.24, "post2025_from_pre2024", "2025 여름", "#397b91")]:
            part = data[data.from_ars.eq(ars) & data.comparison.eq(comparison)].set_index("metric").reindex(order)
            if not part.quality_pass.all() or part.change_pct.isna().any():
                raise ValueError("강조 구간의 관측 조건 또는 결과 누락")
            positions = np.arange(4) + offset
            ax.bar(positions, part.change_pct, width=.22, color=color, label=name)
            ax.errorbar(positions, part.change_pct,
                        yerr=np.vstack([part.change_pct - part.week_bootstrap_low, part.week_bootstrap_high - part.change_pct]),
                        fmt="none", ecolor="#555", capsize=2, lw=.9)
        ax.set(title=title, xticks=np.arange(4), xticklabels=["기록 시간", "운행횟수", "승차 기록", "승차/운행 비율"], ylim=(-62, 67))
        ax.axhline(0, color="#777", lw=.8)
        ax.legend(loc="upper left" if ars == "22011" else "upper right", fontsize=9)
    axes[0].set_ylabel("같은 2024년 사전 평균 대비 지수 변화 (%)")
    fig.suptitle("남행의 큰 시간 감소는 이 제한 표본의 승차 감소와 함께 나타나지 않음", fontsize=14)
    fig.text(.02, .015, "도착 정류장의 같은 기록 시간 결합. 시간 전용 셀 보존율 남행 88.9%·북행 53.6%; 전체 구간으로 일반화 금지.\n승차/운행은 일별 합계 비율을 별도 기준화한 값. 같은 차량·점유율·정차 원인이나 다중 비교 보정 효과가 아님.", fontsize=9, va="bottom")
    fig.tight_layout(rect=(0, .12, 1, .93))
    output = OUT / "highlighted_operations.png"
    fig.savefig(output, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    write_json(OUT / "plot_audit.json", {"completed_at": utcnow(), "code_sha256": sha256(Path(__file__)),
               "inputs": {"comparisons.csv": sha256(OUT / "comparisons.csv")}, "output": {output.name: sha256(output)}})
