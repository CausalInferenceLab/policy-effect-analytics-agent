"""고정 중앙 정류장의 2025년 승하차 변화를 일별 평일과 월별 저녁으로 구분해 그린다."""

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .common import sha256, write_json  # noqa: E402
from .overnight_card_persistence import OUT  # noqa: E402
from .overnight_operations_plots import style  # noqa: E402


def plot():
    style()
    daily_path, hourly_path = OUT / "daily_comparisons.csv", OUT / "monthly_year_changes.csv"
    daily, hourly = pd.read_csv(daily_path), pd.read_csv(hourly_path)
    daily = daily[daily.scope.eq("direction") & daily.comparison.eq("pre_year_over_year")]
    hourly = hourly[hourly.band.eq("evening") & hourly.flow.eq("boardings")]
    if not daily.quality_pass.all() or not hourly.quality_pass.all():
        raise ValueError("보류한 카드 변화를 유효한 결과로 그리지 않습니다")
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for group, label, color, offset in [("central_south", "남행 8개 정류장", "#397b91", -.12),
                                       ("central_north", "북행 8개 정류장", "#cc784a", .12)]:
        selected = daily[daily.group.eq(group)].set_index("flow").reindex(["boardings", "alightings"])
        axes[0].errorbar(np.arange(2) + offset, selected.change_pct,
                        yerr=[selected.change_pct - selected.week_bootstrap_low, selected.week_bootstrap_high - selected.change_pct],
                        fmt="o", capsize=4, color=color, label=label)
        for i, row in enumerate(selected.itertuples()):
            axes[0].text(i + offset, row.week_bootstrap_high + .5, f"{row.change_pct:+.2f}%", ha="center", color=color, fontsize=9)
        selected = hourly[hourly.group.eq(group)].sort_values("after_month")
        axes[1].plot(np.arange(4), selected.change_pct, marker="o", color=color, lw=2, label=label)
        for i, value in enumerate(selected.change_pct):
            axes[1].text(i, value + .45, f"{value:+.2f}%", ha="center", color=color, fontsize=9)
    axes[0].set(title="같은 사전 창의 평일 하루 전체", xticks=[0, 1], xticklabels=["승차 기록", "하차 기록"], xlim=(-.5, 1.5))
    axes[1].set(title="같은 월의 달력 하루 저녁 승차", xticks=np.arange(4), xticklabels=["5월", "6월", "7월", "8월"])
    for ax in axes:
        ax.set(ylabel="2024년 같은 기간 대비 2025년 변화 (%)", ylim=(-5, 12))
        ax.axhline(0, color="#888", lw=.8)
        ax.legend(loc="upper left", fontsize=9)
    fig.suptitle("정류장 전체 서울 면허 카드에서도 남행 기록은 늘었으나 증가 폭은 표본마다 다름", fontsize=14)
    fig.text(.02, .015, "왼쪽: 5/20~6/28 평일·공휴일 제외, 8개 정류장 모두 관측, 주 재표집 구간. 오른쪽: 주말 포함 월별 17~19시.\n"
             "일별·월별 총계 256개 조합 정확 일치. 같은 카드 집계 체계이며 독립 측정·고유 사람 수·경기 광역버스 전체가 아님.", fontsize=9, va="bottom")
    fig.tight_layout(rect=(0, .11, 1, .92))
    path = OUT / "card_persistence.png"
    fig.savefig(path, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    write_json(OUT / "figures.json", {"code_sha256": sha256(Path(__file__)),
                                      "inputs": {p.name: sha256(p) for p in [daily_path, hourly_path]},
                                      "outputs": {path.name: sha256(path)}})
