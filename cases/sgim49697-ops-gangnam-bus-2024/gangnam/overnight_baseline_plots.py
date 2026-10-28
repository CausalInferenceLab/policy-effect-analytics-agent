"""상대 저속 기준 모델·경보량 제한·속도 구간의 사후 비교를 그림으로 저장한다."""

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .common import CASE, sha256, write_json  # noqa: E402
from .overnight_operations_plots import style  # noqa: E402

OUT = CASE / "results/overnight/forecast_baselines"


def save(fig, name, note):
    fig.text(.02, .02, note, fontsize=9, va="bottom")
    fig.tight_layout(rect=(0, .12, 1, .93))
    fig.savefig(OUT / name, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot():
    style()
    probability = pd.read_csv(OUT / "probability_metrics.csv")
    quantile = pd.read_csv(OUT / "quantile_metrics.csv")
    primary = probability[probability["slice"].eq("primary_all_hours")]
    order = ["seasonal_q20", "calendar_logistic_q20", "weekly_logistic_q20", "catboost_frozen_q20"]
    labels = ["계절 빈도", "달력 로지스틱", "주간 로지스틱", "기존 CatBoost"]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    for offset, horizon, color in [(-.18, 1, "#397b91"), (.18, 3, "#cc784a")]:
        data = primary[primary.horizon.eq(horizon) & primary.rule.eq("original_rule")].set_index("name").reindex(order)
        bars = ax.bar(np.arange(4) + offset, data.average_precision, width=.34, color=color, label=f"{horizon}시간")
        ax.bar_label(bars, fmt="%.3f", padding=3)
    ax.set(xticks=np.arange(4), xticklabels=labels, ylabel="평균 정밀도(AP, 높을수록 좋음)", ylim=(0, 1))
    ax.legend(loc="upper left")
    fig.suptitle("핵심 3개 링크의 상대 저속: 단순 기준보다 높은 전체 AP", fontsize=15)
    save(fig, "relative_baselines.png", "시험은 2025년 5~8월, 상대 저속 2,075개 / 관측 8,820개. 기존 시험을 본 뒤 추가한 탐색적 비교.\n저녁만 보면 주간 로지스틱 대비 AP 차이의 주 재표집 구간은 두 간격 모두 0을 포함함.")

    fig, axes = plt.subplots(1, 3, figsize=(14, 5.5))
    chosen = primary[primary.name.eq("catboost_frozen_q20")].set_index(["horizon", "rule"])
    keys = [(1, "original_rule"), (1, "budget_rule"), (3, "original_rule"), (3, "budget_rule")]
    chosen = chosen.reindex(pd.MultiIndex.from_tuples(keys))
    for ax, field, title, multiplier, limit in [(axes[0], "precision", "경보 중 맞은 비율 (%)", 100, 110),
                                                (axes[1], "recall", "상대 저속을 찾은 비율 (%)", 100, 110),
                                                (axes[2], "alerts_per_day", "달력 하루당 링크·시간 경보", 1, 23)]:
        bars = ax.bar(np.arange(4), chosen[field] * multiplier, color=["#397b91", "#cc784a"] * 2)
        ax.bar_label(bars, fmt="%.1f", padding=3)
        ax.set(title=title, xticks=np.arange(4), xticklabels=["1h 기존", "1h 제한", "3h 기존", "3h 제한"], ylim=(0, limit))
    fig.suptitle("경보량을 줄이면 정밀도는 높아지지만 대부분의 상대 저속을 놓침", fontsize=15)
    save(fig, "alert_budget.png", "4월 평균 하루 2개 이하로 고른 고정 임계값을 시험에 적용. 시험 평균은 2.76·3.14개로 증가.\n하루마다 2개를 강제로 잘라낸 운영 정책이 아니며, 상대 저속을 실제 장애·민원과 동일시하지 않음.")

    q = quantile[quantile["slice"].eq("primary_all_hours")]
    key_order = [("calendar_empirical", "raw"), ("weekly_empirical", "raw"),
                 ("weekly_empirical", "calibration_expanded"), ("catboost_frozen_quantile", "raw")]
    fig, axes = plt.subplots(1, 3, figsize=(15, 5.7))
    for ax, field, title in [(axes[0], "coverage", "관측 포함률"), (axes[1], "width", "평균 구간 폭 (km/h)"),
                             (axes[2], "interval_score_alpha_0.2", "구간 점수 (낮을수록 좋음)")]:
        for offset, horizon, color in [(-.18, 1, "#397b91"), (.18, 3, "#cc784a")]:
            data = q[q.horizon.eq(horizon)].set_index(["name", "variant"]).reindex(pd.MultiIndex.from_tuples(key_order))
            bars = ax.bar(np.arange(4) + offset, data[field], width=.34, color=color, label=f"{horizon}시간")
            ax.bar_label(bars, fmt="%.2f", padding=3, fontsize=9)
        ax.set(title=title, xticks=np.arange(4), xticklabels=["달력\n경험분포", "주간\n원본", "주간\n보정", "기존\nCatBoost"])
        ax.set_ylim(0, max(.95 if field == "coverage" else 0, float(q[field].max()) * 1.18))
    axes[0].axhline(.8, color="#555", ls="--", lw=1, label="목표 80%")
    axes[0].legend(loc="lower left", fontsize=9)
    fig.suptitle("속도 범위는 포함률·폭·누락 벌점을 함께 비교", fontsize=15)
    save(fig, "quantile_baselines.png", "주간 보정은 3월 점수로 양 끝을 각각 1.003km/h 확장. 달력·CatBoost는 축소 금지 규칙에 따라 확장 0.\n전체 포함률 약 82%여도 기존 CatBoost의 저녁 포함률은 79.0%·76.7%; 시계열에 분포무관 보장을 주장하지 않음.")
    names = ["relative_baselines.png", "alert_budget.png", "quantile_baselines.png"]
    write_json(OUT / "figures.json", {"code_sha256": sha256(Path(__file__)),
                                      "inputs": {name: sha256(OUT / name) for name in ["probability_metrics.csv", "quantile_metrics.csv"]},
                                      "outputs": {name: sha256(OUT / name) for name in names}})
