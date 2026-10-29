"""강남역 인접 구간의 장기 주간 궤적과 모든 구간의 기술적 수준 분할을 그린다."""

import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from .common import sha256, write_json  # noqa: E402
from .overnight_operations_plots import style  # noqa: E402
from .overnight_timeline import OUT  # noqa: E402


def run():
    style()
    audit = json.loads((OUT / "audit.json").read_text())
    paths = [OUT / name for name in ["weekly.csv", "single_level_changes.csv", "series.csv"]]
    if any(sha256(path) != audit["outputs"][path.name] for path in paths):
        raise ValueError("장기 궤적 그림 입력 해시 변경")
    weekly, fits, meta = [pd.read_csv(path, dtype={"from_ars": str, "to_ars": str}) for path in paths]
    fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=True)
    for axis, ars, title in [(axes[0], "22011", "남행 22011→22009: 지하철2호선강남역→신분당선강남역"),
                             (axes[1], "22008", "북행 22008→22010: 래미안아파트·파이낸셜뉴스→신분당선강남역")]:
        series = meta[meta.scope.eq("segment") & meta.from_ars.eq(ars)].iloc[0].series
        for method, label, color in [("equal_cells", "고정 셀 평균", "#397b91"), ("median_cells", "고정 셀 중앙값", "#cc784a")]:
            frame = weekly[weekly.series.eq(series) & weekly.aggregation.eq(method)].sort_values("week_start")
            axis.plot(pd.to_datetime(frame.week_start), frame["index"], color=color, alpha=.9, lw=1.4, label=label)
        axis.axvline(pd.Timestamp("2024-06-29"), color="#b24242", lw=1.2, ls="--", label="2024-06-29 조정일")
        axis.axhline(100, color="#888", lw=.7)
        axis.set(title=title, ylabel="2024년 사전 셀 기준 지수", ylim=(20, 180))
        axis.legend(loc="upper left", fontsize=9, ncol=3)
        axis.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        axis.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.suptitle("두 강조 구간의 반대 수준 변화는 2024년 7월 이후 여러 달에 걸쳐 유지", fontsize=15)
    fig.text(.02, .015, "평일·공휴일 제외, 주 유효 3일 이상·예정 날짜 80% 이상. 탈락 주는 선을 끊고 보간하지 않음.\n"
             "32개월/2024년 단일 분할은 두 집계 모두 2024-07-01 주 선택. 계절·추세·측정 변경을 분리한 인과 변화일 추정은 아님.", fontsize=9)
    fig.tight_layout(rect=(0, .095, 1, .95))
    fig.savefig(OUT / "highlighted_weekly.png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    frame = fits[fits.scope.eq("segment") & fits.aggregation.eq("equal_cells") & fits.range.eq("full")].copy()
    south = frame[frame.group.eq("central_south")].sort_values("from_ars", ascending=False)
    north = frame[frame.group.eq("central_north")].sort_values("from_ars")
    frame = pd.concat([south, north], ignore_index=True)
    if not frame.quality_pass.eq(True).all():
        raise ValueError("보류한 구간 분할이 그림에 포함됐습니다")
    labels = [("남 " if row.group == "central_south" else "북 ") + row.from_ars + "→" + row.to_ars for row in frame.itertuples()]
    colors = ["#397b91" if group == "central_south" else "#cc784a" for group in frame.group]
    fig, axes = plt.subplots(1, 2, figsize=(13, 7), sharey=True, gridspec_kw={"width_ratios": [1.5, 1]})
    positions = np.arange(len(frame))
    axes[0].scatter(pd.to_datetime(frame.split_week), positions, color=colors, s=45)
    axes[0].axvline(pd.Timestamp("2024-06-29"), color="#b24242", ls="--", lw=1)
    axes[0].xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    axes[0].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    axes[0].set(title="최소 제곱오차 단일 분할 주", yticks=positions, yticklabels=labels,
                xlim=(pd.Timestamp("2023-01-01"), pd.Timestamp("2025-08-31")))
    for i, row in enumerate(frame.itertuples()):
        axes[0].annotate(row.split_week, (pd.Timestamp(row.split_week), i), xytext=(6, 0), textcoords="offset points", va="center", fontsize=8)
    axes[1].barh(positions, frame.geometric_change_pct, color=colors, alpha=.85)
    axes[1].axvline(0, color="#888", lw=.8)
    axes[1].set(title="분할 뒤/앞 주간 기하평균 변화", xlabel="변화 (%)", xlim=(-60, 50))
    for i, value in enumerate(frame.geometric_change_pct):
        axes[1].text(value + (1 if value >= 0 else -1), i, f"{value:+.1f}%", va="center", ha="left" if value >= 0 else "right", fontsize=9)
    axes[0].invert_yaxis()
    fig.suptitle("모든 구간이 같은 시점에 바뀐 것은 아님: 전체 14개 구간을 함께 공개", fontsize=14)
    fig.text(.02, .02, "2023-01~2025-08, 고정 셀 평균, 로그 주간 지수의 두 상수 수준 적합. 양쪽 최소 유효 8주.\n"
             "분할 앞뒤의 서로 다른 긴 기간 요약으로 기존 사전/사후 창 증감률과 다름. 유의성 검정·정책 효과가 아님.", fontsize=9)
    fig.tight_layout(rect=(0, .11, 1, .94))
    fig.savefig(OUT / "segment_splits.png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    write_json(OUT / "figures.json", {"code_sha256": sha256(Path(__file__)), "inputs": {p.name: sha256(p) for p in paths},
                                      "outputs": {name: sha256(OUT / name) for name in ["highlighted_weekly.png", "segment_splits.png"]}})
