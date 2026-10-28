"""같은 CatBoost 설정의 정보 집합별 상대 저속 성능과 짝 차이를 시각화한다."""

import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .common import CASE, sha256, write_json  # noqa: E402
from .overnight_operations_plots import style  # noqa: E402

OUT = CASE / "results/overnight/relative_ablation"


def plot():
    style()
    audit = json.loads((OUT / "evaluation_audit.json").read_text())
    for name, expected in audit["outputs"].items():
        if sha256(OUT / name) != expected:
            raise ValueError("정보 집합 비교 결과 해시 불일치")
    metrics = pd.read_csv(OUT / "metrics.csv")
    paired = pd.read_csv(OUT / "paired_comparisons.csv")
    names = ["calendar_only", "weekly_delayed", "recent_road_assumption", "frozen_delayed_bus_ablation"]
    labels = ["달력", "주간 도로", "최근 도로", "+ 지연 버스"]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.8))
    for ax, scope, title in zip(axes, ["primary_all_hours", "primary_evening_17_19"], ["전체 시간", "저녁 17~19시"], strict=True):
        for offset, horizon, color in [(-.18, 1, "#397b91"), (.18, 3, "#cc784a")]:
            part = metrics[metrics["slice"].eq(scope) & metrics.horizon.eq(horizon) & metrics.rule.eq("original_rule")]
            part = part.set_index("name").reindex(names)
            bars = ax.bar(np.arange(4) + offset, part.average_precision, width=.34, color=color, label=f"{horizon}시간")
            ax.bar_label(bars, fmt="%.3f", padding=3, fontsize=9)
        ax.set(title=title, xticks=np.arange(4), xticklabels=labels, ylim=(0, 1.07), ylabel="AP (높을수록 좋음)")
    axes[0].legend(loc="lower left")
    fig.suptitle("주간 도로 정보의 이득은 남지만 버스 정보의 추가 이득은 확인되지 않음", fontsize=15)
    fig.text(.02, .025, "동일 깊이·시드·학습 표본·개발 기간의 탐색 비교. 시험은 이미 관측한 2025년 5~8월 핵심 3개 링크.\n달력·주간 정보는 목표 시각 기준으로 같아 두 예측 간격의 결과도 동일함; 독립 반복 실험이 아님.", fontsize=10)
    fig.tight_layout(rect=(0, .13, 1, .93))
    fig.savefig(OUT / "information_sets.png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    pairs = [("weekly_delayed", "calendar_only"), ("recent_road_assumption", "weekly_delayed"),
             ("frozen_delayed_bus_ablation", "recent_road_assumption")]
    pair_labels = ["주간 - 달력", "최근 - 주간", "버스 추가 - 최근"]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.8), sharex=True)
    for ax, scope, title in zip(axes, ["primary_all_hours", "primary_evening_17_19"], ["전체 시간", "저녁 17~19시"], strict=True):
        for offset, horizon, color in [(-.12, 1, "#397b91"), (.12, 3, "#cc784a")]:
            part = paired[paired["slice"].eq(scope) & paired.horizon.eq(horizon)
                          & paired.rule.eq("original_rule") & paired.metric.eq("average_precision")]
            part = part.set_index(["left", "right"]).reindex(pd.MultiIndex.from_tuples(pairs))
            y = np.arange(3) + offset
            ax.hlines(y, part.low, part.high, color=color, lw=3)
            ax.scatter(part.difference, y, color=color, label=f"{horizon}시간", zorder=3)
        ax.axvline(0, color="#888", lw=1)
        ax.set(title=title, yticks=np.arange(3), yticklabels=pair_labels, xlabel="AP 차이와 주 공동 재표집 95% 구간", ylim=(-.6, 2.6))
        ax.invert_yaxis()
    axes[0].legend(loc="lower right")
    fig.suptitle("최근 도로 정보의 이득은 1시간에서 뚜렷하고 3시간에서는 불확실", fontsize=15)
    fig.text(.02, .025, "18개 달력 주를 두 모델에 함께 1,000회 재표집. 양수는 앞 정보 집합의 AP가 높음을 뜻함.\n여러 범위의 탐색이며 확증 검정·새 독립 시험이 아님. 실제 도로 정보 제공 지연도 미확인.", fontsize=10)
    fig.tight_layout(rect=(0, .13, 1, .93))
    fig.savefig(OUT / "information_differences.png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    write_json(OUT / "figures.json", {"code_sha256": sha256(Path(__file__)), "inputs": audit["outputs"],
                                     "outputs": {name: sha256(OUT / name) for name in ["information_sets.png", "information_differences.png"]}})
