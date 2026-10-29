"""폐선 노선을 제외한 비교와 기록 부재의 경계를 별도 그림으로 저장한다."""

import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .common import sha256, write_json  # noqa: E402
from .deepening_cohort import OUT  # noqa: E402
from .overnight_operations_plots import style  # noqa: E402


def run():
    style()
    audit = json.loads((OUT / "audit.json").read_text())
    inputs = {}
    for name in ["comparisons.csv", "retired_route_daily.csv"]:
        actual = sha256(OUT / name)
        if actual != audit["outputs"][name]:
            raise ValueError("구성 비교 그림의 입력 해시 변경")
        inputs[name] = actual
    data = pd.read_csv(OUT / "comparisons.csv")
    labels = {"summer2024": "2024 사전 → 2024 여름", "pre_year_over_year": "2024 사전 → 2025 사전",
              "post2025_from_pre2024": "2024 사전 → 2025 여름", "summer2025": "2025 사전 → 2025 여름",
              "post_year_over_year": "2024 여름 → 2025 여름"}
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.6), sharey=True, sharex=True)
    for ax, segment, title, color in zip(axes, ["south", "north"], ["남행 22011→22009", "북행 22008→22010"],
                                          ["#287c9c", "#b56535"], strict=True):
        for cohort, offset, selected_color, marker, label in [
            ("original_14_reproduction", -.13, "#9aa3ad", "o", "원래 14개 선택"),
            ("retained_13_same_accepted_dates", .13, color, "s", "542번 제외 13개 · 같은 날짜")]:
            rows = data[data.segment.eq(segment) & data.cohort.eq(cohort)].set_index("comparison").reindex(labels)
            if not rows.quality_pass.all():
                raise ValueError("그림에 사용할 구성 비교의 품질 조건 미달")
            y = np.arange(len(labels)) + offset
            ax.hlines(y, rows.week_bootstrap_low, rows.week_bootstrap_high, color=selected_color, lw=2)
            ax.scatter(rows.change_pct, y, color=selected_color, marker=marker, s=30, label=label, zorder=3)
        ax.axvline(0, color="#999", lw=.8)
        ax.axhline(2.5, color="#ccc", lw=.8, ls="--")
        ax.set(title=title, xlabel="앞 기간 대비 기록 시간 지수 변화 (%)", xlim=(-68, 68),
               yticks=np.arange(len(labels)), yticklabels=list(labels.values()))
        ax.grid(axis="x", alpha=.15)
    axes[0].invert_yaxis()
    axes[0].legend(loc="lower left", fontsize=8)
    fig.suptitle("폐선 이력을 반영한 13개 노선에서도 방향별 변화가 유지됨", fontsize=15)
    fig.text(.02, .025, "원래 사전 기준값·양방향 07~22시 공동 관측 규칙 유지, 17~19시 비교. 13개 관측률 규칙을 다시 적용해도 유효 날짜가 같았다.\n"
             "선은 개별 주 재표집 구간. 시간 단위·정차 경계 미확인으로 실제 분 절감이나 인과 효과가 아니다.", fontsize=9)
    fig.tight_layout(rect=(0, .14, 1, .92))
    fig.savefig(OUT / "retained_cohort_changes.png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    daily = pd.read_csv(OUT / "retired_route_daily.csv")
    daily = daily[daily.date.between("2024-08-15", "2024-09-02")]
    totals = daily.groupby("date").sum(numeric_only=True)
    days = totals.index.tolist()
    palette = [("positive", "양수 기록", "#397b91"), ("zero", "숫자 0", "#7792c3"),
               ("negative", "음수", "#b56535"), ("blank", "행 내부 공란", "#d3ac52"),
               ("row_absent", "해당 행 미수록", "#d4d8dd"), ("source_date_absent", "원본 날짜 부재", "#626b76")]
    fig, axes = plt.subplots(3, 1, figsize=(11.5, 6.8), sharex=True, sharey=True)
    for ax, metric, label in zip(axes, ["time", "departure_trips", "arrival_trips"],
                                  ["시간 기록", "출발 정류장 횟수", "도착 정류장 횟수"], strict=True):
        bottom = np.zeros(len(days))
        for state, state_label, color in palette:
            values = totals[metric + "_" + state].to_numpy()
            ax.bar(np.arange(len(days)), values, bottom=bottom, color=color, label=state_label, width=.85)
            bottom += values
        if not np.array_equal(bottom, totals.expected_hours.to_numpy()):
            raise ValueError("폐선 기록 그림의 상태 합계 불일치")
        ax.axvline(days.index("2024-08-24") - .5, color="#973d3d", ls="--", lw=1.3)
        ax.set(ylabel=label, ylim=(0, 32), yticks=[0, 16, 32])
    axes[0].legend(ncol=6, bbox_to_anchor=(.5, 1.45), loc="upper center", fontsize=8)
    positions = np.arange(0, len(days), 2)
    axes[-1].set(xticks=positions, xticklabels=[days[i][5:] for i in positions], xlabel="2024년 기록 날짜")
    fig.suptitle("542번의 시간·횟수 기록과 공식 폐선일(8월 24일)", fontsize=15)
    fig.text(.02, .02, "세로축은 두 강조 구간 × 16시간의 기록 셀 수이며 운행 대수·횟수의 합이 아니다. 점선은 공식 폐선일의 경계.\n"
             "8월 23일의 시간 미수록·횟수 공란 원인은 미확인이다. 마지막 양수 기록일을 실제 운행 종료일로 바꾸지 않는다.", fontsize=9)
    fig.tight_layout(rect=(0, .11, 1, .91))
    fig.savefig(OUT / "retirement_record_states.png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    write_json(OUT / "figures.json", {"code_sha256": sha256(Path(__file__)), "inputs": inputs,
        "outputs": {name: sha256(OUT / name) for name in ["retained_cohort_changes.png", "retirement_record_states.png"]}})
