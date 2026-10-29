"""월별 공개 파일 모형의 구간 점수와 같은 시드의 입력 추가 차이를 그린다."""

import json

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .common import sha256, write_json  # noqa: E402
from .deepening_archive_data import OUT  # noqa: E402
from .overnight_operations_plots import style  # noqa: E402


def run():
    style()
    audit_path = OUT / "evaluation_audit.json"
    audit = json.loads(audit_path.read_text())
    validation = json.loads((OUT / "result_validation.json").read_text())
    if validation["evaluation_audit_sha256"] != sha256(audit_path) or validation["mismatches"]:
        raise ValueError("독립 대조를 통과한 월별 예측 결과가 필요합니다")
    for name in ["metrics.csv", "paired_comparisons.csv"]:
        if sha256(OUT / name) != audit["outputs"][name]:
            raise ValueError("월별 예측 그림 입력 변경")
    metrics = pd.read_csv(OUT / "metrics.csv")
    pairs = pd.read_csv(OUT / "paired_comparisons.csv")
    keys = [("calendar_only", 17), ("calendar_only", 42), ("published_archive", 17), ("published_archive", 42),
            ("published_three_month_profile", 0), ("reference_recent_assumption", 0)]
    labels = ["달력\n시드17", "달력\n시드42", "공개 과거 월\n시드17", "공개 과거 월\n시드42", "최근 3개월\n경험 분위수", "최근 속도\n접근 가정"]
    colors = ["#92999c", "#b7bec1", "#267c9c", "#75b3c7", "#cfac56", "#a591b5"]
    fig, axes = plt.subplots(2, 2, figsize=(12.8, 8.9), sharey=True)
    selected = metrics[metrics.scope.eq("primary_all_hours")]
    ymax = selected["interval_score_alpha_0.2"].max() * 1.23
    for row, horizon in enumerate([1, 3]):
        for col, (period, title) in enumerate([("summer", "5월 11일~8월"), ("autumn", "9~12월")]):
            frame = selected[selected.period.eq(period) & selected.horizon.eq(horizon)].set_index(["name", "seed"]).reindex(keys)
            values = frame["interval_score_alpha_0.2"].to_numpy()
            if not np.isfinite(values).all():
                raise ValueError("구간 점수 그림의 고정 모형 누락")
            ax = axes[row, col]
            ax.bar(np.arange(6), values, color=colors, width=.7)
            for i, value in enumerate(values):
                ax.text(i, value + ymax * .02, f"{value:.2f}", ha="center", fontsize=10)
            ax.set(title=f"{title} | H{horizon}", xticks=np.arange(6), xticklabels=labels, ylim=(0, ymax))
            ax.tick_params(axis="x", labelsize=9)
            ax.grid(axis="y", alpha=.16)
            if col == 0:
                ax.set_ylabel("80% 구간 점수 · 낮을수록 좋음")
    fig.suptitle("공개 시점에 얻을 수 있는 월별 자료만으로 다시 예측", fontsize=16, y=.985)
    fig.text(.02, .02, "핵심 남행 3개 일반도로 링크, 이미 본 2025년의 후속 비교. 버스 시간 예측이 아님. 새 구간 보정·시험 결과에 따른 시드 선택 없음.\n"
        "최근 속도 접근 가정은 별도 자료 공급·이전 학습 조건의 참고치. H1은 대상 시간 시작 발행, H3는 시작 2시간 전 발행.", fontsize=9)
    fig.tight_layout(rect=(0, .085, 1, .95))
    first = OUT / "archive_interval_scores.png"
    fig.savefig(first, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    entries, names, shades = [], [], []
    for period, period_title in [("summer", "5~8월"), ("autumn", "9~12월")]:
        for scope, scope_title in [("primary_all_hours", "전체"), ("primary_evening_17_19", "17~19시")]:
            for horizon in [1, 3]:
                for seed in [17, 42]:
                    entries.append((period, scope, horizon, seed))
                    names.append(f"{period_title} · {scope_title} · H{horizon} · 시드{seed}")
                    shades.append("#267c9c" if period == "summer" else "#ac6b42")
    fig, axes = plt.subplots(1, 2, figsize=(12.8, 8.6), sharey=True)
    chosen = pairs[pairs.comparison.eq("archive_minus_calendar")]
    for ax, (metric, title) in zip(axes, [("median_mae", "중앙값 절대오차 차이 (km/h)"),
                                         ("interval_score_alpha_0.2", "80% 구간 점수 차이")], strict=True):
        data = chosen[chosen.metric.eq(metric)].set_index(["period", "scope", "horizon", "seed"]).reindex(entries)
        if not data.quality_pass.eq(True).all() or not np.isfinite(data[["difference", "low", "high"]]).all().all():
            raise ValueError("짝 비교 그림의 구간·품질 오류")
        for i, (_, record) in enumerate(data.iterrows()):
            ax.plot([record.low, record.high], [i, i], color=shades[i], linewidth=1.8)
            ax.scatter(record.difference, i, color=shades[i], s=28, zorder=3)
        ax.axvline(0, color="#777", linestyle="--", linewidth=1)
        ax.set(xlabel=title, yticks=np.arange(len(names)), yticklabels=names, ylim=(len(names) - .3, -.7))
        ax.grid(axis="x", alpha=.16)
    fig.suptitle("공개 과거 월 입력의 추가 가치: 같은 시드의 달력 모형과 비교", fontsize=15, y=.985)
    fig.text(.02, .02, "차이 = 공개 과거 월 모형 - 달력 모형. 0보다 작으면 오차/점수가 감소한다. 모든 두 시드·시간대·시점 비교를 함께 표시.\n"
        "같은 달력 주를 2,000회 재표집한 기술적 95% 구간이며 인과효과나 다중비교 보정 구간이 아니다.", fontsize=9)
    fig.tight_layout(rect=(0, .085, 1, .95))
    second = OUT / "archive_calendar_differences.png"
    fig.savefig(second, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    write_json(OUT / "figures.json", dict(code_sha256=sha256(__file__),
        inputs={name: sha256(OUT / name) for name in ["metrics.csv", "paired_comparisons.csv", "result_validation.json"]},
        outputs={path.name: sha256(path) for path in [first, second]}))
