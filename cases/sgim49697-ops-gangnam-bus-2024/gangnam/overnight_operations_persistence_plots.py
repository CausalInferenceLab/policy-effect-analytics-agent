"""같은 공통 셀에서 관측한 2024·2025년 시간·운행·승차 기록의 수준을 그린다."""

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .common import CASE, sha256, write_json  # noqa: E402
from .overnight_operations_plots import style  # noqa: E402

OUT = CASE / "results/overnight/operations_persistence"


def plot():
    style()
    source = OUT / "comparisons.csv"
    data = pd.read_csv(source)
    selected = data[data.band.eq("evening") & data.endpoint.eq("arrival")]
    if not selected.quality_pass.all():
        raise ValueError("저녁 공통 기록의 보류 결과를 유효한 평균으로 그리지 않습니다")
    metrics = [("time", "기록 시간"), ("trips", "운행횟수 기록"),
               ("boardings", "승차 기록"), ("boardings_per_recorded_trip", "운행 기록당 승차 비율")]
    fig, axes = plt.subplots(2, 2, figsize=(12, 8.4), sharex=True)
    for ax, (metric, title) in zip(axes.flat, metrics, strict=True):
        for group, label, color in [("central_south", "남행 268개 셀", "#397b91"),
                                    ("central_north", "북행 251개 셀", "#cc784a")]:
            rows = selected[selected.group.eq(group) & selected.metric.eq(metric)].set_index("comparison")
            values = [rows.loc["summer2024", "before_mean"], rows.loc["summer2024", "after_mean"],
                      rows.loc["summer2025", "before_mean"], rows.loc["summer2025", "after_mean"]]
            ax.plot(np.arange(4), values, marker="o", color=color, label=label, lw=2)
            for position, value in enumerate(values):
                ax.annotate(f"{value:.1f}", (position, value), xytext=(0, 8 if group == "central_south" else -14),
                            textcoords="offset points", ha="center", fontsize=9, color=color)
        ax.axhline(100, color="#999", ls="--", lw=.8)
        ax.set(title=title, ylabel="고정 2024년 사전 기준 지수", ylim=(85, 125), xticks=np.arange(4),
               xticklabels=["2024 사전", "2024 여름", "2025 사전", "2025 여름"])
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(.5, .94), ncol=2)
    fig.suptitle("시간이 줄어든 남행에서도 승차 기록은 늘었음", fontsize=15)
    fig.text(.02, .015, "정책 후보 밖 고정 공통 셀·저녁 17~19시·도착 정류장 같은 시간 연결. 선은 기간 평균 연결이며 중간 날짜 추정이 아님.\n"
             "비율은 일별 승차 합/운행횟수 합의 별도 사전 기준이며 두 지수의 나눗셈이 아님. 차량별 탑승 인원·혼잡도·인과 효과로 해석하지 않음.",
             fontsize=9, va="bottom")
    fig.tight_layout(rect=(0, .08, 1, .90))
    path = OUT / "common_operations_levels.png"
    fig.savefig(path, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    write_json(OUT / "figures.json", {"code_sha256": sha256(Path(__file__)), "inputs": {source.name: sha256(source)},
                                      "outputs": {path.name: sha256(path)}})
