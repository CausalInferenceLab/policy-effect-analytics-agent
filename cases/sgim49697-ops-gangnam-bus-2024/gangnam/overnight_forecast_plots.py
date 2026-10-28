"""동결 시험의 기준선 비교·경보 부담·상대 저속·분위수 예측을 정적 그림으로 저장한다."""

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

from .common import CASE, sha256, write_json  # noqa: E402

OUT = CASE / "results/overnight/forecast"
COLORS = ["#397b98", "#cc7953"]


def save(fig, name, note, bottom=.10):
    fig.text(.02, .02, note, fontsize=9, color="#4b5563")
    fig.tight_layout(rect=(0, bottom, 1, .94))
    fig.savefig(OUT / name, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def models(metrics, bootstrap):
    d = metrics[metrics["slice"].eq("primary_all_hours") & metrics.label.eq("label_10") & metrics.family.ne("quantile")]
    labels = ["달력·계절 확률", "달력·로지스틱", "달력·CatBoost", "7일 전 속도·로지스틱", "7일 전 속도·CatBoost",
              "최근 도로 가정·로지스틱", "최근 도로 가정·CatBoost", "지연 버스 추가·로지스틱", "지연 버스 추가·CatBoost (선택)", "선택 설정·다른 시드"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 7), sharey=True)
    intervals = bootstrap[bootstrap["slice"].eq("primary_all_hours") & bootstrap.metric.eq("average_precision")].set_index("candidate")
    for ax, horizon, color in zip(axes, [1, 3], COLORS, strict=True):
        x = d[d.horizon.eq(horizon)].reset_index(drop=True)
        for i, row in x.iterrows():
            ci = intervals.loc[row.candidate]
            ax.plot([ci.low, ci.high], [i, i], color=color, alpha=.45, lw=2)
            ax.scatter(row.average_precision, i, marker="D" if row.role == "primary_selected" else "o", color=color, zorder=3)
        ax.axvline(x.prevalence.iloc[0], color="#888888", ls=":", label="실제 저속 비율")
        ax.set(title=f"{horizon}시간 예측", xlabel="Average precision", xlim=(0, .6), yticks=np.arange(len(labels)), yticklabels=labels)
        ax.grid(axis="x", alpha=.2)
    axes[0].invert_yaxis()
    fig.suptitle("절대 저속 41개 관측: 복잡한 모델의 우위가 뚜렷한가", fontsize=15)
    save(fig, "forecast_model_comparison.png", "2025년 5~8월 핵심 3개 링크. 선은 주 단위 1,000회 재표집 95% 기술 구간. 시험 점수로 선택 모델을 교체하지 않음.")


def alerts(metrics):
    confusion = pd.read_csv(OUT / "test_confusion_counts.csv").set_index("candidate")
    selected = metrics[metrics["slice"].eq("primary_all_hours") & metrics.role.eq("primary_selected")]
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    positions = np.arange(2)
    true, false, missed = [], [], []
    for name in selected.candidate:
        x = confusion.loc[name]
        true.append(x.true_alerts)
        false.append(x.false_alerts)
        missed.append(x.missed_events)
    axes[0].bar(positions, true, color="#397b98", label="실제 저속과 맞은 경보")
    axes[0].bar(positions, false, bottom=true, color="#d2a285", label="저속이 아니었던 경보")
    for i, (t, f, m) in enumerate(zip(true, false, missed, strict=True)):
        axes[0].text(i, t + f + 7, f"경보 {t+f}개\n정탐 {t} · 놓침 {m}", ha="center", fontsize=10)
    axes[0].set(xticks=positions, xticklabels=["1시간", "3시간"], ylabel="링크×시간 경보 수", ylim=(0, 420))
    axes[0].legend(loc="upper right", fontsize=9)
    support = pd.read_csv(OUT / "test_event_support.csv", dtype={"link_id": str})
    support = support[support.horizon.eq(1)].set_index("link_id").reindex(["1220025000", "1220021000", "1220016200"])
    bars = axes[1].bar(np.arange(3), support.positive_hours, color=["#88a7b4", "#cc7953", "#b4c2ca"])
    axes[1].bar_label(bars, padding=4, fmt="%.0f개")
    axes[1].set(xticks=np.arange(3), xticklabels=["교보타워→강남역", "강남역→우성아파트", "우성아파트→뱅뱅사거리"], ylabel="10km/h 미만 관측 수", ylim=(0, 45))
    axes[1].tick_params(axis="x", rotation=15)
    fig.suptitle("높은 재현율만으로는 경보의 실용성을 판단할 수 없다", fontsize=15)
    save(fig, "forecast_alert_burden.png", "절대 저속 관측 41개 중 38개가 한 링크에 집중. 시간별 경보를 합친 수이며 운전자 알림 횟수나 독립 사고 건수가 아님.")


def relative_warning(metrics):
    d = metrics[metrics.label.eq("label_q20") & metrics["slice"].isin(["primary_all_hours", "primary_evening_17_19"])]
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    for ax, scope, title in zip(axes, ["primary_all_hours", "primary_evening_17_19"], ["모든 시간", "저녁 17~19시"], strict=True):
        for offset, horizon, color in [(-.18, 1, COLORS[0]), (.18, 3, COLORS[1])]:
            row = d[d["slice"].eq(scope) & d.horizon.eq(horizon)].iloc[0]
            values = 100 * row[["precision", "recall", "false_positive_rate"]].astype(float).to_numpy()
            bars = ax.bar(np.arange(3) + offset, values, width=.34, color=color, label=f"{horizon}시간")
            ax.bar_label(bars, fmt="%.1f", padding=3, fontsize=9)
        ax.set(title=title, xticks=np.arange(3), xticklabels=["정밀도", "재현율", "거짓 양성률"], ylim=(0, 108), ylabel="%")
        ax.legend()
    fig.suptitle("평소보다 느린 상태: 별도 상대 저속 목표의 시험 결과", fontsize=15)
    save(fig, "forecast_relative_warning.png", "학습기 링크별 하위 20% 속도를 기준으로 한 별도 목표. 시속 10km 경보의 대체 성적이 아니며 저녁 오탐률도 함께 확인.")


def quantile_coverage(metrics):
    d = metrics[metrics.family.eq("quantile")]
    periods = ["primary_all_hours", "primary_evening_17_19", *[f"month_2025-{m:02}" for m in range(5, 9)]]
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    for horizon, color in zip([1, 3], COLORS, strict=True):
        x = d[d.horizon.eq(horizon)].set_index("slice").reindex(periods)
        axes[0].plot(np.arange(6), 100 * x.coverage, marker="o", color=color, label=f"{horizon}시간")
        axes[1].plot(np.arange(6), x.width, marker="o", color=color, label=f"{horizon}시간")
    axes[0].axhline(80, color="#888888", ls="--", label="명목 80%")
    axes[0].set(ylabel="실제 값 포함률 (%)", ylim=(70, 90))
    axes[1].set(ylabel="예측 구간의 평균 폭 (km/h)", ylim=(0, 6))
    for ax in axes:
        ax.set(xticks=np.arange(6), xticklabels=["전체", "저녁", "5월", "6월", "7월", "8월"])
        ax.legend()
        ax.grid(axis="y", alpha=.2)
    fig.suptitle("속도 범위 예측: 전체 포함률과 저녁 성능을 함께 점검", fontsize=15)
    save(fig, "forecast_quantile_coverage.png", "고정한 10·50·90% 분위수 모델. 전체 핵심 구간의 80% 구간 포함률은 약 82%; 저녁 3시간 예측은 약 77%.")


def plot():
    for path in [Path("/mnt/c/Windows/Fonts/malgun.ttf"), Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")]:
        if path.exists():
            font_manager.fontManager.addfont(str(path))
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(path)).get_name()
            break
    plt.rcParams.update({"axes.unicode_minus": False, "axes.spines.top": False, "axes.spines.right": False, "font.size": 10})
    metrics = pd.read_csv(OUT / "test_metrics.csv")
    bootstrap = pd.read_csv(OUT / "test_week_bootstrap.csv")
    models(metrics, bootstrap)
    for render in [alerts, relative_warning, quantile_coverage]:
        render(metrics)
    figures = ["forecast_model_comparison.png", "forecast_alert_burden.png", "forecast_relative_warning.png", "forecast_quantile_coverage.png"]
    inputs = ["test_metrics.csv", "test_week_bootstrap.csv", "test_confusion_counts.csv", "test_event_support.csv"]
    write_json(OUT / "figures.json", {"code_sha256": sha256(Path(__file__)), "inputs": {n: sha256(OUT / n) for n in inputs},
        "figures": {n: sha256(OUT / n) for n in figures}})
