"""속도 구간 보정의 포함률·폭·구간 점수와 저녁 링크별 미포함을 함께 시각화한다."""

import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .common import CASE, sha256, write_json  # noqa: E402
from .overnight_operations_plots import style  # noqa: E402

OUT = CASE / "results/overnight/interval_calibration"


def plot():
    style()
    audit = json.loads((OUT / "evaluation_audit.json").read_text())
    path = OUT / "metrics.csv"
    if sha256(path) != audit["outputs"][path.name]:
        raise ValueError("구간 보정 그림 입력 해시 불일치")
    data = pd.read_csv(path)
    names = ["raw", "static_global", "static_link_band", "rolling_global_d2", "rolling_link_band_d2",
             "rolling_global_d24", "rolling_link_band_d24", "rolling_global_d168", "rolling_link_band_d168"]
    labels = ["원본", "3월 전체", "3월 링크·시간", "28일 전체 / 2h", "28일 링크·시간 / 2h",
              "28일 전체 / 24h", "28일 링크·시간 / 24h", "28일 전체 / 168h", "28일 링크·시간 / 168h"]
    selected = data[data["slice"].eq("primary_evening_17_19")]
    fig, axes = plt.subplots(1, 3, figsize=(15, 7), sharey=True)
    for ax, metric, scale, title in [(axes[0], "coverage", 100, "저녁 관측 포함률 (%)"),
                                    (axes[1], "width", 1, "평균 구간 폭 (km/h)"),
                                    (axes[2], "interval_score_alpha_0.2", 1, "구간 점수 (낮을수록 좋음)")]:
        for shift, horizon, color in [(-.12, 1, "#397b91"), (.12, 3, "#cc784a")]:
            part = selected[selected.horizon.eq(horizon)].set_index("variant").reindex(names)
            ax.scatter(part[metric] * scale, np.arange(len(names)) + shift, color=color, label=f"{horizon}시간", s=45)
        ax.set(title=title, yticks=np.arange(len(names)), yticklabels=labels)
        ax.grid(axis="y", alpha=.15)
    axes[0].axvline(80, color="#888", ls="--", lw=1)
    axes[0].invert_yaxis()
    axes[2].legend(loc="lower center")
    fig.suptitle("링크·시간별 보정은 저녁 포함률을 높이지만 구간 폭도 커짐", fontsize=15)
    fig.text(.02, .02, "2025년 5~8월의 이미 관측한 시험을 순차 재생. 28일 방식의 h는 오차 공개 지연 가정이며 예측 간격과 다름.\n2·24·168시간 모두 실제 제공 지연의 확인이 아님. 원래 모델의 최근 도로 입력 가정은 유지됨. 점은 시험 평균.", fontsize=10)
    fig.tight_layout(rect=(0, .13, 1, .94))
    fig.savefig(OUT / "evening_calibration_tradeoffs.png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    variants = ["raw", "static_link_band", "rolling_link_band_d2"]
    links = ["1220025000", "1220021000", "1220016200"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.8), sharey=True)
    for ax, horizon in zip(axes, [1, 3], strict=True):
        matrix = np.array([[data[(data.horizon == horizon) & data.variant.eq(variant)
                                & data["slice"].eq("evening_link_" + link)].iloc[0].coverage * 100
                            for link in links] for variant in variants])
        ax.imshow(matrix, cmap="RdYlGn", vmin=70, vmax=86, aspect="auto")
        for row in range(3):
            for column in range(3):
                ax.text(column, row, f"{matrix[row, column]:.1f}%", ha="center", va="center", fontsize=13)
        ax.set(title=f"{horizon}시간 예측", xticks=np.arange(3), xticklabels=["교보→강남", "강남→우성", "우성→뱅뱅"],
               yticks=np.arange(3), yticklabels=["원본", "3월 링크·시간", "28일 링크·시간 / 2h"])
    fig.suptitle("전체 저녁 포함률이 80%를 넘어도 개별 링크에서는 부족할 수 있음", fontsize=14)
    fig.text(.02, .02, "각 칸은 저녁 369개 링크·시간 관측의 포함률. 색 범위 70~86%, 목표 80%.\n구간 폭·누락 벌점은 첫 그림과 함께 판단. 여러 집단의 탐색이며 조건부 포함률 보장 또는 독립 시험이 아님.", fontsize=10)
    fig.tight_layout(rect=(0, .14, 1, .93))
    fig.savefig(OUT / "evening_link_coverage.png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    write_json(OUT / "figures.json", {"code_sha256": sha256(Path(__file__)), "inputs": {path.name: sha256(path)},
                                     "outputs": {name: sha256(OUT / name) for name in ["evening_calibration_tradeoffs.png", "evening_link_coverage.png"]}})
