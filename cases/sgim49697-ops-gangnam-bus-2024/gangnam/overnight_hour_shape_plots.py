"""같은 노선·날짜 공동 표본의 16시간 변화율과 관측 조건을 표시한다."""

import json
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .common import sha256, write_json  # noqa: E402
from .overnight_hour_shape import OUT  # noqa: E402
from .overnight_operations_plots import style  # noqa: E402


def run():
    style()
    path = OUT / "comparisons.csv"
    audit = json.loads((OUT / "audit.json").read_text())
    if sha256(path) != audit["outputs"][path.name]:
        raise ValueError("시간 모양 그림 입력 변경")
    data = pd.read_csv(path)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.8), sharey=True)
    for axis, key, title in zip(axes, ["south", "north"], ["남행 22011→22009", "북행 22008→22010"], strict=True):
        part = data[data.segment.eq(key)]
        count = int(part.selected_routes.iloc[0])
        for comparison, label, color, offset in [("summer2024", "2024 여름", "#7d98a6", -.08),
                                                  ("post2025_from_pre2024", "2025 여름", "#1d627c", .08)]:
            rows = part[part.comparison.eq(comparison)].sort_values("hour")
            valid = rows.quality_pass.eq(True)
            values = rows.change_pct.where(valid)
            axis.plot(rows.hour + offset, values, marker="o", ms=3, lw=1.5, label=label, color=color)
            axis.fill_between(rows.hour + offset, rows.week_bootstrap_low.where(valid),
                              rows.week_bootstrap_high.where(valid), color=color, alpha=.15)
            for row in rows[~valid].itertuples():
                axis.text(row.hour, 0, "보류", rotation=90, fontsize=7, va="bottom")
        axis.axhline(0, color="#888", lw=.8)
        axis.axvspan(16.5, 19.5, alpha=.07, color="#b36227")
        axis.set(title=f"{title} · 고정 {count}개 노선", xticks=list(range(7, 23)), xlabel="시간 열 (7~22시)")
        axis.tick_params(axis="x", labelsize=8)
        axis.legend(fontsize=9, loc="lower left")
    axes[0].set_ylabel("2024년 사전 대비 기록 운행시간 지수 변화 (%)")
    fig.suptitle("같은 노선의 16시간을 함께 관측해 비교한 변화", fontsize=15)
    fig.text(.02, .025, "한 시간이라도 양수 기록이 없으면 그 노선·날짜의 16시간을 모두 제외. 노선 선택과 기준값은 사전 기간만 사용.\n"
             "음영은 시간별 주 재표집 변동 구간이며 공동 신뢰구간·인과 효과가 아님. 주황 배경은 17~19시.", fontsize=9)
    fig.tight_layout(rect=(0, .12, 1, .94))
    figure = OUT / "hourly_changes.png"
    fig.savefig(figure, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    write_json(OUT / "figures.json", {"code_sha256": sha256(Path(__file__)), "inputs": {path.name: sha256(path)},
                                      "outputs": {figure.name: sha256(figure)}})
