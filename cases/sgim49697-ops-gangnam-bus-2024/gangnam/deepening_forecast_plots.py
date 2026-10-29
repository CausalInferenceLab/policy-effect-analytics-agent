"""고정 경보의 시점별 구성과 월별 속도 파일 가용성을 그림으로 보여준다."""

import json

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .common import CASE, sha256, write_json  # noqa: E402
from .overnight_operations_plots import style  # noqa: E402


def read_verified(directory, name):
    path = CASE / "results/deepening" / directory
    audit = json.loads((path / "audit.json").read_text())
    if sha256(path / name) != audit["outputs"][name]:
        raise ValueError("예측 후속 그림 입력 변경")
    return pd.read_csv(path / name)


def run():
    style()
    metrics = read_verified("episodes", "metrics.csv")
    chosen = metrics[metrics.rule.eq("budget_rule") & metrics.minimum_observed_hours.eq(1)]
    fig, axes = plt.subplots(2, 2, figsize=(12.2, 8.8), sharey=True)
    classes = {"advance": ("시작 전", "#287c9c"), "at_onset": ("시작 시점", "#d6a338"),
               "ongoing": ("진행 중", "#8671aa"), "positive_unknown_onset": ("시작 미상", "#a6a6a6"),
               "false_point_alert": ("대상 시간 저속 아님", "#d88272")}
    for row, (task, name, title) in enumerate([
        ("relative_probability", "recent_road_assumption", "링크별 고정 하위 20% · 최근 속도 모형"),
        ("conditional_margin", "scaled_median_gap", "요일·시간 기준 저속 · 표준화 중앙값 차이")]):
        for col, (period, label) in enumerate([("summer", "5~8월"), ("autumn", "9~12월")]):
            ax = axes[row, col]
            data = chosen[chosen.period.eq(period) & chosen.task.eq(task) & chosen.name.eq(name)]
            data = data.set_index(["horizon", "cooldown_hours"]).reindex([(1, 0), (1, 3), (3, 0), (3, 3)])
            if len(data) != 4 or data.alerts.isna().any():
                raise ValueError("경보 구성 그림 표본 오류")
            bottom = np.zeros(4)
            for kind, (display, color) in classes.items():
                heights = (data["alerts_" + kind] / data.calendar_days).to_numpy()
                ax.bar(np.arange(4), heights, bottom=bottom, width=.64, color=color, label=display)
                bottom += heights
            for i, value in enumerate(bottom):
                ax.text(i, value + .07, f"{value:.2f}", ha="center", fontsize=10)
            ax.set(title=f"{label} | {title}", xticks=np.arange(4),
                xticklabels=["H1\n매번", "H1\n3시간 간격", "H3\n매번", "H3\n3시간 간격"], ylim=(0, 5.4))
            ax.grid(axis="y", alpha=.15)
            if col == 0:
                ax.set_ylabel("하루 알림 수 · 핵심 3개 링크 합계")
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(.5, .945), ncol=5, frameon=False)
    fig.suptitle("높은 정밀도가 저속 구간의 시작을 잘 알린다는 뜻은 아님", fontsize=15, y=.985)
    fig.text(.02, .015, "기존 budget_rule 임계값 고정. H1은 대상 시간 시작 시점 발행, H3는 그보다 2시간 앞선 발행.\n"
             "기술적 저속 구간이며 실제 사고가 아니다. 5~8월 결측 36개 링크·시간은 복원하지 않았고 기간별 재알림 상태는 빈 값에서 시작한다.", fontsize=9)
    fig.tight_layout(rect=(0, .085, 1, .90))
    episode_path = CASE / "results/deepening/episodes/alarm_timing.png"
    fig.savefig(episode_path, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    available = read_verified("availability", "feature_availability.csv")
    keys = [("origin", 2), ("target", 168), ("target", 336), ("target", 504), ("target", 672), ("target", 1344)]
    rows, labels = [], []
    for scenario, label in [("catalog_current_version_proxy", "현재 목록 등록·수정일 대용"),
                            ("conservative_guide_and_current_version", "안내 11일·현재 버전 중 늦은 시각")]:
        for period, period_label in [("summer", "5~8월"), ("autumn", "9~12월")]:
            data = available[available.scenario.eq(scenario) & available.period.eq(period) & available.horizon.eq(1)]
            data = data.set_index(["anchor", "lag_hours"]).reindex(keys)
            rows.append(data.fraction_available.to_numpy() * 100)
            labels.append(period_label + " | " + label)
    values = np.array(rows)
    if not np.isfinite(values).all():
        raise ValueError("가용 시점 그림 누락")
    fig, ax = plt.subplots(figsize=(12.2, 4.6))
    im = ax.imshow(values, vmin=0, vmax=100, cmap="YlGnBu", aspect="auto")
    for row in range(4):
        for col in range(6):
            ax.text(col, row, f"{values[row, col]:.1f}%", ha="center", va="center", color="white" if values[row, col] > 55 else "#222")
    ax.set(xticks=np.arange(6), xticklabels=["2시간 전", "7일 전", "14일 전", "21일 전", "28일 전", "56일 전"],
        yticks=np.arange(4), yticklabels=labels, xlabel="속도 입력값의 시간 지연 · H1 기준")
    fig.colorbar(im, ax=ax, pad=.02, label="발행 시점에 월별 파일이 공개됐다고 보는 비율 (%)")
    fig.suptitle("월별 파일로는 최근 속도 입력을 공급할 수 없음", fontsize=15)
    fig.text(.02, .015, "속도값을 읽지 않고 파일 36개의 현재 메타데이터와 시간 격자만 비교. 현재 목록 날짜는 과거 배포 이력의 증명이 아니다.\n"
             "안내는 익월 10일이나 시각이 없어 11일 00시를 보수적으로 가정. 56일 지연의 가용성이 예측 성능을 뜻하지는 않는다.", fontsize=9)
    fig.tight_layout(rect=(0, .13, 1, .93))
    availability_path = CASE / "results/deepening/availability/archive_availability.png"
    fig.savefig(availability_path, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    for directory, file, source in [("episodes", episode_path, "metrics.csv"),
                                    ("availability", availability_path, "feature_availability.csv")]:
        write_json(CASE / "results/deepening" / directory / "figures.json", dict(code_sha256=sha256(__file__),
            inputs={source: sha256(file.parent / source)}, outputs={file.name: sha256(file)}))
