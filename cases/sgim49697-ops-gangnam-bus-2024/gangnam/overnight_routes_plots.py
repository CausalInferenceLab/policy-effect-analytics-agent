"""노선군 분리·시간대·날짜 민감도와 승객 가중치 범위의 결과 그림을 저장한다."""

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

from .common import CASE, sha256, write_json  # noqa: E402
from .overnight_observation_plots import BANDS, GROUPS, PERIODS, save  # noqa: E402

OUT = CASE / "results/overnight"


def route_bands():
    d = pd.read_csv(OUT / "bus/route_group_comparisons.csv")
    d = d[d.cohort.eq("common_pre_source_days") & d.policy_group.eq("other_or_unclassified") & d.aggregation.eq("equal_cells")]
    rows = [(g, b) for g in ["central_south", "central_north"] for b in BANDS]
    x = d.set_index(["direction", "band", "comparison"])
    values = np.array([[x.loc[(group, band, period)].change_pct for period in PERIODS] for group, band in rows])
    fig, ax = plt.subplots(figsize=(10, 7))
    ax.imshow(values, aspect="auto", cmap="RdBu_r", vmin=-18, vmax=18)
    for i in range(len(rows)):
        for j in range(3):
            ax.text(j, i, f"{values[i, j]:+.1f}%", ha="center", va="center", fontsize=12,
                    color="white" if abs(values[i, j]) > 11 else "#243e50")
    ax.set(xticks=range(3), xticklabels=PERIODS.values(), yticks=range(len(rows)),
           yticklabels=[f"{GROUPS[g]} · {BANDS[b]}" for g, b in rows])
    fig.suptitle("정책 후보 밖의 고정 노선군: 남행 감소와 북행 증가", fontsize=15)
    save(fig, "route_remaining_bands.png", "2023·2024 사전 관측만으로 셀 고정. 기타·분류 미확정 집단이며 무처치 대조군 아님. 단위 없는 기록 지수의 기술 비교.")


def route_weights():
    d = pd.read_csv(OUT / "bus/route_group_comparisons.csv")
    d = d[d.cohort.eq("common_pre_source_days") & d.policy_group.eq("other_or_unclassified")
          & d.comparison.eq("summer2024") & d.band.eq("evening")]
    methods = {"equal_cells": "셀 평균", "equal_routes": "노선 동일 가중", "equal_segments": "구간 동일 가중", "median_cells": "셀 중앙값"}
    fig, ax = plt.subplots(figsize=(11, 5))
    for offset, group, color in [(-.18, "central_south", "#2d798b"), (.18, "central_north", "#cb744d")]:
        x = d[d.direction.eq(group)].set_index("aggregation").reindex(methods)
        bars = ax.bar(np.arange(4) + offset, x.change_pct, width=.34, label=GROUPS[group], color=color)
        ax.bar_label(bars, fmt="%+.1f%%", padding=4)
    ax.set(xticks=range(4), xticklabels=methods.values(), ylabel="2024 여름 저녁 기록 지수 변화 (%)", ylim=(-13, 17))
    ax.axhline(0, color="#888888", lw=.8)
    ax.legend(ncol=2)
    fig.suptitle("집계법을 바꾸어도 남행·북행의 부호가 유지", fontsize=15)
    save(fig, "route_remaining_weights.png", "정책 후보 밖 집단의 사전 고정 셀. 8개 비교 모두 관측·날짜 기준 통과. 집계법 간 차이를 정책 효과 크기의 범위로 해석하지 않음.")


def timing():
    d = pd.read_csv(OUT / "bus/timing_sensitivity.csv")
    d = d[d.group.eq("central_north") & d.band.eq("evening")]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.7), sharey=True)
    for ax, year in zip(axes, [2023, 2024], strict=True):
        x = d[d.year.eq(year)].sort_values("cut_date")
        dates = pd.to_datetime(x.cut_date)
        ax.plot(dates, x.change_pct.where(x.quality_pass), color="#386b86")
        ax.scatter(dates[~x.quality_pass], x.change_pct[~x.quality_pass], marker="x", color="#888888")
        ax.axvline(pd.Timestamp(f"{year}-06-29"), color="#d27b4c", ls="--", label="6월 29일 기준")
        ax.axhline(0, color="#888888", lw=.7)
        ax.set(title=f"{year}년", xlabel="전후 40일 창의 기준일")
        ax.tick_params(axis="x", rotation=35)
    axes[0].set_ylabel("전후 기록 지수 변화 (%)")
    axes[1].legend()
    fig.suptitle("북행 저녁의 날짜 민감도: 하루가 유일한 변화점인가", fontsize=15)
    save(fig, "route_timing_sensitivity.png", "기준일 전후 각 40일의 평일 비교. 서로 겹치는 창이며 독립 위약 검정·정책 시점 탐지 아님. 2023년 6월 29일은 비교용 날짜.", bottom=.12)


def passenger_coverage():
    d = pd.read_csv(OUT / "passengers/fixed_weight_comparisons.csv")
    d = d[d.band.eq("evening")]
    fig, ax = plt.subplots(figsize=(10, 4.5))
    for offset, subset, name, color in [(-.18, "all_preselected", "전체 사전 고정 셀", "#718da2"),
                                       (.18, "other_or_unclassified", "정책 후보 밖", "#d29155")]:
        x = d[d.subset.eq(subset)].set_index("group").reindex(GROUPS)
        bars = ax.bar(np.arange(3) + offset, 100 * x.weight_cell_fraction, width=.34, label=name, color=color)
        ax.bar_label(bars, fmt="%.1f%%", padding=4)
    ax.axhline(80, color="#945857", ls="--", label="필요 범위 80%")
    ax.set(xticks=range(3), xticklabels=GROUPS.values(), ylabel="사전 승객 가중치를 만들 수 있는 셀 (%)", ylim=(0, 105))
    ax.legend(loc="upper right", ncol=3, fontsize=9)
    fig.suptitle("승객 기록은 통행시간 표본의 일부만 덮는다", fontsize=15)
    save(fig, "passenger_weight_coverage.png", "기준: 사전 날짜 중 비음수 재차인원 기록 80% 이상. 공란·행 부재는 0이 아님. 범위 미달로 전체 통행시간의 승객 가중 결과는 보류.")


def plot():
    for path in [Path("/mnt/c/Windows/Fonts/malgun.ttf"), Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")]:
        if path.exists():
            font_manager.fontManager.addfont(str(path))
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(path)).get_name()
            break
    plt.rcParams.update({"axes.unicode_minus": False, "axes.spines.top": False, "axes.spines.right": False, "font.size": 10})
    for render in [route_bands, route_weights, timing, passenger_coverage]:
        render()
    names = ["route_remaining_bands.png", "route_remaining_weights.png", "route_timing_sensitivity.png", "passenger_weight_coverage.png"]
    write_json(OUT / "route_figures.json", {"code_sha256": sha256(Path(__file__)), "figures": {n: sha256(OUT / n) for n in names},
        "inputs": {n: sha256(OUT / n) for n in ["bus/route_group_comparisons.csv", "bus/timing_sensitivity.csv", "passengers/fixed_weight_comparisons.csv"]}})
