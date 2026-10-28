"""시간대별 지수·집계 민감도·관측 누락·기상 공통 표본을 정적 그림으로 저장한다."""

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

from .common import CASE, sha256, utcnow, write_json  # noqa: E402

OUT = CASE / "results/overnight"
BANDS = {"morning": "아침 07~09시", "midday": "낮 11~14시", "evening": "저녁 17~19시", "late": "야간 20~22시"}
GROUPS = {"central_south": "중앙 남행", "central_north": "중앙 북행", "curb_south": "가로변 후보"}
PERIODS = {"summer2023": "2023 여름", "summer2024": "2024 여름", "autumn2024": "2024 가을"}


def save(fig, name, note, bottom=.08):
    fig.text(.02, .015, note, fontsize=9, color="#4b5563")
    fig.tight_layout(rect=(0, bottom, 1, .94))
    fig.savefig(OUT / name, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def time_bands():
    d = pd.read_csv(OUT / "bus/aggregation_comparisons.csv")
    d = d[d.aggregation.eq("equal_cells") & d.daily_threshold.eq(.8)]
    rows = [(g, b) for g in GROUPS for b in BANDS]
    fig, axes = plt.subplots(1, 2, figsize=(12, 8), sharey=True)
    for ax, cohort, title in zip(axes, ["common_pre_source_days", "summer_survivors_source_days"],
                                 ["양년 사전 관측으로 고정", "사후에도 관측된 표본 (민감도)"], strict=True):
        x = d[d.cohort.eq(cohort)].set_index(["group", "band", "comparison"])
        values = np.full((len(rows), 3), np.nan)
        passed = np.zeros_like(values, dtype=bool)
        for i, (group, band) in enumerate(rows):
            for j, period in enumerate(PERIODS):
                r = x.loc[(group, band, period)]
                values[i, j], passed[i, j] = r.change_pct, r.quality_pass
        ax.imshow(np.ma.masked_invalid(values), aspect="auto", cmap="RdBu_r", vmin=-22, vmax=22)
        for i in range(len(rows)):
            for j in range(3):
                val = values[i, j]
                label = f"{val:+.1f}%" if np.isfinite(val) else "산출 불가"
                ax.text(j, i, label + (" ×" if not passed[i, j] else ""), ha="center", va="center", fontsize=9,
                        color="white" if abs(val) > 15 else "#25374b")
        ax.set(title=title, xticks=range(3), xticklabels=PERIODS.values(), yticks=range(len(rows)))
    axes[0].set_yticklabels([f"{GROUPS[g]} · {BANDS[b]}" for g, b in rows], fontsize=9)
    fig.suptitle("버스 기록 지수의 변화: 방향·시간대·계절", fontsize=16)
    save(fig, "time_bands.png", "×: 20일·관측률·전후 관측률 차이 기준 미달. 기준은 매일 셀 80%. 가로변 ID 이력 일부 미확정. 인과 효과·분 단위 아님.")


def weighting():
    d = pd.read_csv(OUT / "bus/aggregation_comparisons.csv")
    d = d[d.cohort.eq("common_pre_source_days") & d.daily_threshold.eq(.8) & d.comparison.eq("summer2024") & d.group.eq("central_north")]
    names = {"equal_cells": "셀 평균", "equal_routes": "노선 동일 가중", "equal_segments": "구간 동일 가중", "median_cells": "셀 중앙값"}
    fig, ax = plt.subplots(figsize=(11, 5))
    colors = ["#2d6585", "#418c7e", "#cb7e39", "#9374a5"]
    for k, (method, name) in enumerate(names.items()):
        x = d[d.aggregation.eq(method)].set_index("band").reindex(BANDS)
        ax.bar(np.arange(4) + (k - 1.5) * .18, x.change_pct, width=.17, label=name, color=colors[k])
    ax.set(xticks=range(4), xticklabels=BANDS.values(), ylabel="2024 여름 기록 지수 변화 (%)")
    ax.axhline(0, color="#555555", lw=.7)
    ax.legend(ncol=2)
    fig.suptitle("북행의 저녁 증가가 집계 방식에 따라 얼마나 달라지나", fontsize=15)
    save(fig, "north_weighting.png", "같은 사전 셀을 고정. 노선/구간 집계는 단위 내부와 전체 단위의 관측률도 확인. 크기는 6.1~12.3%로 달라지며 인과 추정 아님.")


def missingness():
    d = pd.read_csv(OUT / "bus/missingness_by_route_segment.csv")
    d = d[d.cohort.eq("common_pre_source_days") & d.band.eq("evening") & d.group.eq("central_south")]
    kinds = {"positive": "양수 기록", "zero": "0 기록", "blank": "공란", "row_absent": "셀 행 부재", "source_date_absent": "원본 날짜 부재"}
    colors = ["#397f7a", "#e4b45d", "#b9b9b9", "#c5645e", "#7d8798"]
    groups = {"reverse_evening": "역방향 후보", "curb": "가로변 전환 후보", "dongtan": "동탄 후보", "other_or_unclassified": "기타·분류 미확정"}
    fig, axes = plt.subplots(1, 3, figsize=(13, 5), sharey=True)
    for ax, period, title in zip(axes, ["pre2024", "post2024", "autumn2024"], ["정책 전", "여름 이후", "가을"], strict=True):
        x = d[d.period.eq(period)].groupby("policy_group")[list(kinds) + ["expected_cells"]].sum().reindex(groups).fillna(0)
        left = np.zeros(4)
        for (kind, label), color in zip(kinds.items(), colors, strict=True):
            values = 100 * x[kind] / x.expected_cells
            ax.barh(range(4), values, left=left, color=color, label=label)
            left += values.to_numpy()
        ax.set(title=title, xlim=(0, 100), yticks=range(4), xlabel="고정 셀·달력 날짜 중 비율 (%)")
    axes[0].set_yticklabels(groups.values())
    axes[0].invert_yaxis()
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(.5, .09), ncol=5, frameon=False)
    fig.suptitle("남행 저녁의 관측 누락: 정책 후보 노선과 나머지의 차이", fontsize=15)
    save(fig, "south_missingness.png", "원본 날짜 누락과 셀 내부 0을 구분. 0·행 부재는 무운행 확정이 아님. 후보의 역사적 노선명 연결은 미확정. 분모를 고정한 기록 점검.", bottom=.20)


def weather_support():
    d = pd.read_csv(OUT / "weather/comparisons.csv")
    d = d[d.cohort.eq("common_pre_source_days") & d.group.eq("central_north") & d.band.eq("evening")
          & d.comparison.eq("summer2024") & d.scheme.eq("rain_temperature")].sort_values(["station", "alignment_offset"])
    labels = [f"{ {108: '서울', 400: '강남', 401: '서초'}[r.station]} · {r.alignment_offset:+d}시간" for r in d.itertuples()]
    fig, axes = plt.subplots(1, 2, figsize=(12, 6), sharey=True)
    y = np.arange(len(d))
    for i, r in enumerate(d.itertuples()):
        axes[0].plot(r.change_pct, i, "o" if r.usable_comparison else "x",
                     color="#287f62" if r.usable_comparison else "#b77845", markersize=8)
    axes[0].set(xlabel="기상 공통 층 표준화 후 기록 지수 변화 (%)", xlim=(0, 12), yticks=y, yticklabels=labels)
    axes[0].invert_yaxis()
    axes[1].barh(y - .16, d.before_retained_of_bus * 100, height=.3, label="정책 전", color="#647f9c")
    axes[1].barh(y + .16, d.after_retained_of_bus * 100, height=.3, label="정책 이후", color="#ce8b4e")
    axes[1].axvline(80, color="#6d4b50", ls="--")
    axes[1].set(xlabel="버스 유효 날짜 중 공통 층에 남은 비율 (%)", xlim=(0, 105))
    axes[1].legend()
    fig.suptitle("지역 기상 자료가 늘어도 비교 가능성은 시간 정렬에 민감", fontsize=15)
    save(fig, "weather_alignment_support.png", "●: 20일·보존율 80%·버스 품질 통과, ×: 미달. 시간 정렬 0에서 서초만 통과. 기상청 공개 참조 자료이며 공식 역사적 QC 미확보.")


def plot():
    for path in [Path("/mnt/c/Windows/Fonts/malgun.ttf"), Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")]:
        if path.exists():
            font_manager.fontManager.addfont(str(path))
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(path)).get_name()
            break
    plt.rcParams.update({"axes.unicode_minus": False, "axes.spines.top": False, "axes.spines.right": False, "font.size": 10})
    for render in [time_bands, weighting, missingness, weather_support]:
        render()
    inputs = ["bus/aggregation_comparisons.csv", "bus/missingness_by_route_segment.csv", "weather/comparisons.csv"]
    write_json(OUT / "observation_figures.json", {"generated_at": utcnow(), "code_sha256": sha256(Path(__file__)),
        "inputs": {p: sha256(OUT / p) for p in inputs}, "figures": {p.name: sha256(p) for p in OUT.glob("*.png")}})
