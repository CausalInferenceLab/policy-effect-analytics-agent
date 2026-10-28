"""차이 점수·날씨별 성능·구간 동시 변동 범위를 저장된 집계표에서 그린다."""

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .common import CASE, sha256, utcnow, write_json  # noqa: E402
from .overnight_operations_plots import style  # noqa: E402

BASE = CASE / "results/overnight"


def save(fig, path, note):
    fig.text(.02, .015, note, fontsize=9, va="bottom")
    fig.tight_layout(rect=(0, .12, 1, .93))
    fig.savefig(path, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def margin():
    folder = BASE / "conditional_margin"
    paths = [folder / "metrics.csv", BASE / "conditional_low/metrics.csv"]
    data = pd.concat([pd.read_csv(p) for p in paths], ignore_index=True)
    names = ["recent_road_assumption", "median_gap", "scaled_median_gap"]
    labels = ["최근 도로 이진 분류", "중앙값 차이", "폭으로 나눈 차이"]
    fig, axes = plt.subplots(1, 3, figsize=(14, 5))
    for horizon, offset, color in [(1, -.16, "#397b91"), (3, .16, "#cc784a")]:
        selected = data[data.horizon.eq(horizon) & data.slice.eq("primary_all_hours")
                        & data.rule.eq("budget_rule")].set_index("name").reindex(names)
        for ax, metric, title in zip(axes, ["average_precision", "precision", "recall"],
                                     ["전체 AP", "4월 예산 규칙의 정밀도", "4월 예산 규칙의 재현율"], strict=True):
            bars = ax.bar(np.arange(3) + offset, selected[metric], width=.3, color=color, label=f"{horizon}시간")
            ax.bar_label(bars, fmt="%.3f", padding=3, fontsize=8)
            ax.set(title=title, xticks=np.arange(3), xticklabels=labels, ylim=(0, .9))
            ax.tick_params(axis="x", labelrotation=18)
    axes[0].axhline(selected.prevalence.iloc[0], color="#777", ls="--", lw=.8)
    axes[0].legend(fontsize=9)
    fig.suptitle("기존 속도 예측을 활용하면 조건부 저속 구분력은 높아지지만 탐지율은 제한됨", fontsize=14)
    path = folder / "margin_comparison.png"
    save(fig, path, "같은 2,569개 양성·8,820개 관측. 차이 점수는 기존 회귀 모델 재학습 없이 3월 보정·4월 규칙을 고정.\n4월 평균 하루 2개 규칙은 미래 상한이 아님: 폭 정규화 방식의 시험 경보는 하루 4.26·4.33개. 사후 탐색 비교.")
    return paths, path


def weather():
    folder = BASE / "weather_performance"
    source = folder / "metrics.csv"
    data = pd.read_csv(source)
    data = data[data.station.eq(401) & data.grouping.eq("rain_group") & data.model.eq("catboost_frozen_quantile")]
    fig, axes = plt.subplots(1, 2, figsize=(11, 5), sharey=True)
    for ax, scope, title in zip(axes, ["all_hours", "evening_17_19"], ["전체 시각", "저녁 17~19시"], strict=True):
        for horizon, offset, color in [(1, -.10, "#397b91"), (3, .10, "#cc784a")]:
            part = data[data.horizon.eq(horizon) & data.slice.eq(scope)].set_index("weather_group").reindex(["dry", "wet"])
            ax.plot(np.arange(2) + offset, part.coverage * 100, color=color, lw=1.3, label=f"{horizon}시간")
            for i, row in enumerate(part.itertuples()):
                ax.scatter(i + offset, row.coverage * 100, s=65, edgecolor=color,
                           facecolor=color if row.comparison_quality_pass else "white", zorder=3)
                ax.annotate(f"{row.coverage * 100:.1f}%", (i + offset, row.coverage * 100),
                            xytext=(-22 if horizon == 1 else 22, 9 if horizon == 1 else -16),
                            textcoords="offset points", ha="center", fontsize=9)
        counts = part.rows.tolist()
        ax.set(title=title, xticks=[0, 1], xticklabels=[f"강수 0\n{counts[0]:,}개 관측", f"강수 양수\n{counts[1]:,}개 관측"], ylim=(60, 89))
        ax.axhline(80, color="#777", ls="--", lw=.9)
    axes[0].set_ylabel("원래 80% 예측구간의 실제 포함률 (%)")
    axes[0].legend(loc="lower left")
    fig.suptitle("서초 AWS 401에서 비가 기록된 시간의 예측구간 포함률이 낮음", fontsize=14)
    path = folder / "rain_coverage.png"
    save(fig, path, "실제 관측 날씨에 따른 사후 분류이며 예보 입력·비의 인과 효과가 아님. 결측 강수는 건조에 합치지 않음.\n빈 점: 저녁 강수 양수는 96행으로 사전 하한 100행 미달, 짝 비교 구간 계산 보류. 선은 분류별 점을 잇는 표시.")
    return [source], path


def segments():
    folder = BASE / "segment_uncertainty"
    source = folder / "comparisons.csv"
    data = pd.read_csv(source, dtype={"from_ars": str, "to_ars": str})
    order = data.drop_duplicates("segment").sort_values(["group", "from_order"], ascending=[False, True])
    fig, axes = plt.subplots(1, 2, figsize=(13, 8), sharey=True)
    for ax, comparison, title in zip(axes, ["summer2024", "pre_year_over_year"],
                                     ["2024 사전 → 2024 여름", "2024 사전 → 2025 사전"], strict=True):
        part = data[data.comparison.eq(comparison)].set_index("segment").reindex(order.segment)
        for i, row in enumerate(part.itertuples()):
            color = "#397b91" if row.group == "central_south" else "#cc784a"
            ax.plot([row.simultaneous_low_pct, row.simultaneous_high_pct], [i, i], color=color, lw=1.5)
            ax.plot([row.week_bootstrap_low, row.week_bootstrap_high], [i, i], color="#b1b1b1", lw=5, alpha=.65)
            ax.scatter(row.change_pct, i, color=color, s=24, zorder=3)
        ax.axvline(0, color="#777", ls="--", lw=.8)
        ax.set(title=title, xlabel="원래 고정 셀의 기록 시간 지수 변화 (%)", xlim=(-65, 55))
    axes[0].set_yticks(np.arange(len(order)), [f"{'남행' if r.group == 'central_south' else '북행'} {r.from_ars} → {r.to_ars}" for r in order.itertuples()])
    axes[0].invert_yaxis()
    fig.suptitle("70개 비교의 공동 변동을 고려해도 강남역 두 구간의 반대 변화가 남음", fontsize=14)
    path = folder / "joint_ranges.png"
    save(fig, path, "회색 굵은 선: 원래 개별 주 재표집 범위. 색 선: 14구간×5비교를 함께 고려한 탐색적 범위 중 2개 비교 표시.\n기간별 6개 주·5,000회 공통 재표집. 정식 유의성 검정·정책 인과 효과·보장된 95% 동시 신뢰구간이 아님.")
    return [source], path


def run():
    style()
    for plot in [margin, weather, segments]:
        inputs, output = plot()
        write_json(output.parent / "plot_audit.json", {"completed_at": utcnow(), "code_sha256": sha256(Path(__file__)),
                   "inputs": {str(p.relative_to(CASE)): sha256(p) for p in inputs}, "output": {output.name: sha256(output)}})
