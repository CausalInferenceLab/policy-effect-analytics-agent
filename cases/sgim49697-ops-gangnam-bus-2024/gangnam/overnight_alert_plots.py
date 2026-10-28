"""순차 경보의 발행량·정밀도·재현율과 시간대별 예산 소진을 그림으로 정리한다."""

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .common import CASE, sha256, utcnow, write_json  # noqa: E402
from .overnight_operations_plots import style  # noqa: E402

OUT = CASE / "results/overnight/alert_replay"
ORDER = ["original", "cap2", "cooldown3", "cooldown3_cap2", "confirm2_cooldown3_cap2"]
LABELS = ["원래", "하루 2개", "3시간 대기", "대기+2개", "연속 확인+대기+2개"]


def save(fig, name, note):
    fig.text(.02, .015, note, fontsize=9, va="bottom")
    fig.tight_layout(rect=(0, .1, 1, .94))
    fig.savefig(OUT / name, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def run():
    style()
    data = pd.read_csv(OUT / "metrics.csv")
    data = data[data.slice.eq("all_hours")]
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    for row, label, title in [(0, "label_10", "절대 10km/h 미만"), (1, "label_q20", "링크 전체 학습 하위 20%")]:
        for horizon, offset, color in [(1, -.16, "#397b91"), (3, .16, "#cc784a")]:
            part = data[data.label.eq(label) & data.horizon.eq(horizon)].set_index("policy").reindex(ORDER)
            for ax, metric, suffix in zip(axes[row], ["alerts", "precision_known", "recall"],
                                           ["발행 수", "정밀도", "양성 시각 재현율"], strict=True):
                bars = ax.bar(np.arange(5) + offset, part[metric], width=.3, color=color, label=f"{horizon}시간")
                ax.bar_label(bars, fmt="%.0f" if metric == "alerts" else "%.2f", fontsize=8, padding=3)
                ax.set(title=title + " · " + suffix, xticks=np.arange(5), xticklabels=LABELS)
                ax.tick_params(axis="x", labelrotation=22, labelsize=9)
                ax.set_ylim(0, part[metric].max() * 1.35 if metric == "alerts" else 1.)
    axes[0, 0].set_ylim(0, 440)
    axes[1, 0].set_ylim(0, 3050)
    axes[0, 0].legend(fontsize=9)
    fig.suptitle("하루 경보 수를 실제로 제한하면 놓치는 저속이 크게 늘어남", fontsize=15)
    save(fig, "alert_tradeoffs.png", "원점 날짜별 핵심 3개 링크 합계 상한. 미래 점수로 하루 상위 2개를 고르지 않음. 정밀도는 실제값이 있는 발행만 계산.\n발행 수는 실제값 미관측 시각도 포함하며 원래 평가의 알려진 정답 경보 수와 구별. 같은 모델·임계값을 유지한 사후 모의.")

    hourly = pd.read_csv(OUT / "hourly.csv")
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for ax, label, title in zip(axes, ["label_10", "label_q20"], ["절대 10km/h 미만", "링크 전체 학습 하위 20%"], strict=True):
        selected = hourly[hourly.label.eq(label) & hourly.horizon.eq(1)]
        for policy, name, color in [("original", "원래 경보", "#8a9eac"), ("cap2", "하루 2개 경보", "#cc784a")]:
            part = selected[selected.policy.eq(policy)].sort_values("target_hour")
            ax.plot(part.target_hour, part.alerts, marker="o", color=color, lw=1.5, ms=3, label=name)
        ax.plot(part.target_hour, part.positives, color="#397b91", ls="--", lw=1.5, label="실제 양성 시각")
        ax.axvspan(16.5, 19.5, color="#ddd", alpha=.4)
        ax.set(title=title, xlabel="목표 시각의 시 (1시간 설정은 원점과 같음)", xticks=list(range(0, 24, 3)), ylabel="시험 전체의 링크·시간 수")
    axes[0].legend(fontsize=9)
    fig.suptitle("날짜 초반에 예산을 쓰면 퇴근 시간 경보가 남지 않을 수 있음", fontsize=15)
    save(fig, "alert_hours.png", "상대 저속의 1시간·하루 2개 규칙은 10시 이후 발행 0개. 서비스 목적에 맞는 시간대·비용을 별도로 정해야 함.\n이 결과를 보고 시간대별 예약 정책을 추가 선택하지 않음. 연속 양성 묶음은 외부 사고 정답이 아님.")
    names = ["alert_tradeoffs.png", "alert_hours.png"]
    write_json(OUT / "plot_audit.json", {"completed_at": utcnow(), "code_sha256": sha256(Path(__file__)),
        "inputs": {name: sha256(OUT / name) for name in ["metrics.csv", "hourly.csv"]},
        "outputs": {name: sha256(OUT / name) for name in names}})
