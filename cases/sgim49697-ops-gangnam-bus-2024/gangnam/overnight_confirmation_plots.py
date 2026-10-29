"""미열람 가을·겨울의 속도 구간 기준 비교와 조건부 저속 경보 한계를 그린다."""

import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .common import CASE, sha256, write_json  # noqa: E402
from .overnight_confirmation_data import OUT  # noqa: E402
from .overnight_operations_plots import style  # noqa: E402


def run():
    style()
    audit = json.loads((OUT / "evaluation_audit.json").read_text())
    inputs = {}
    for name in ["probability_metrics.csv", "quantile_metrics.csv"]:
        path = OUT / name
        if sha256(path) != audit["outputs"][name]:
            raise ValueError("추가 검증 그림 입력 변경")
        inputs[name] = sha256(path)
    if not audit["comparison_quality_pass"]:
        raise ValueError("추가 검증 품질 보류를 통과한 비교로 그리지 않습니다")
    q = pd.read_csv(OUT / "quantile_metrics.csv")
    p = pd.read_csv(OUT / "probability_metrics.csv")
    ordering = [(1, "primary_all_hours"), (3, "primary_all_hours"),
                (1, "primary_evening_17_19"), (3, "primary_evening_17_19")]
    positions = np.arange(4)
    labels = ["1시간 · 전체", "3시간 · 전체", "1시간 · 17~19시", "3시간 · 17~19시"]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.6))
    models = [("calendar_empirical", "달력 기준", "#a8b5bc"), ("weekly_empirical", "주간 기준 + 고정 보정", "#d0a176"),
              ("catboost_frozen_quantile", "고정 CatBoost", "#31778e")]
    for i, (name, label, color) in enumerate(models):
        rows = q[q.name.eq(name)].set_index(["horizon", "slice"]).reindex(ordering)
        if rows["interval_score_alpha_0.2"].isna().any():
            raise ValueError("추가 검증 구간 그림의 행 누락")
        x = positions + (i - 1) * .23
        axes[0].bar(x, rows["interval_score_alpha_0.2"], width=.21, label=label, color=color)
        axes[1].plot(x, 100 * rows.coverage, "o", ms=7, label=label, color=color)
    axes[0].set(ylabel="구간 점수 (작을수록 좋음)", title="폭과 구간 밖 오차를 함께 평가")
    axes[1].axhline(80, color="#666", lw=1, ls="--")
    axes[1].set(ylabel="실제 속도 포함률 (%)", ylim=(68, 85), title="80% 목표 포함률과 비교")
    for axis in axes:
        axis.set_xticks(positions, labels, fontsize=9)
        axis.legend(fontsize=8, loc="upper left")
    fig.suptitle("2025년 9~12월 추가 검증 · 재학습과 보정 변경 없음", fontsize=15)
    fig.text(.02, .025, "핵심 남행 일반도로 3개 링크, 간격별 8,784행. 주간·달력 기준의 보정량은 2025년 3월 값 그대로.\n"
             "원본을 열기 전 후보·코드 동결. 버스 운행시간 예측이나 실시간 운영 실험이 아님.", fontsize=9)
    fig.tight_layout(rect=(0, .12, 1, .93))
    first = OUT / "quantile_confirmation.png"
    fig.savefig(first, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    old_paths = [CASE / "results/overnight/conditional_low/metrics.csv", CASE / "results/overnight/conditional_margin/metrics.csv"]
    previous = pd.concat([pd.read_csv(path).assign(task=task) for path, task in
                          zip(old_paths, ["conditional_probability", "conditional_margin"], strict=True)], ignore_index=True)
    inputs.update({str(path.relative_to(CASE)): sha256(path) for path in old_paths})
    specs = [("conditional_probability", "recent_road_assumption", "기존 이진 분류", "#b7a087"),
             ("conditional_margin", "scaled_median_gap", "폭 정규화 차이 점수", "#31778e")]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.7))
    for i, (task, name, label, color) in enumerate(specs):
        values = []
        for data, horizon in [(previous, 1), (previous, 3), (p, 1), (p, 3)]:
            row = data[data.task.eq(task) & data.name.eq(name) & data.horizon.eq(horizon)
                       & data["slice"].eq("primary_all_hours") & data.rule.eq("budget_rule")]
            if len(row) != 1:
                raise ValueError("조건부 저속 그림의 고유 행 오류")
            values.append(row.average_precision.iloc[0])
        axes[0].bar(positions + (i - .5) * .34, values, width=.31, color=color, label=label)
        for horizon, marker in [(1, "o"), (3, "s")]:
            row = p[p.task.eq(task) & p.name.eq(name) & p.horizon.eq(horizon)
                    & p["slice"].eq("primary_all_hours") & p.rule.eq("budget_rule")].iloc[0]
            axes[1].scatter(row.alerts_per_day, row.recall * 100, marker=marker, s=65, color=color,
                            label=f"{label} · {horizon}시간")
            axes[1].annotate(f"{row.alerts_per_day:.1f}개 / {row.recall:.1%}", (row.alerts_per_day, row.recall * 100),
                              xytext=(7, 6 if horizon == 1 else -15), textcoords="offset points", fontsize=8)
    axes[0].set(xticks=positions, xticklabels=["5~8월 · 1시간", "5~8월 · 3시간", "9~12월 · 1시간", "9~12월 · 3시간"],
                ylabel="AP (클수록 좋음)", ylim=(0, .6), title="순위 구분력의 개선은 추가 기간에도 남음")
    axes[0].tick_params(axis="x", labelsize=8)
    axes[0].legend(fontsize=8, loc="upper right")
    axes[1].set(xlabel="추가 기간의 하루 경보 수", ylabel="추가 기간의 재현율 (%)", xlim=(0, 69), ylim=(0, 100),
                title="현재 기준의 경보량과 재현율")
    axes[1].legend(fontsize=8, loc="upper left")
    fig.suptitle("같은 요일·시간 하위 20% 저속 · 4월 경보 기준 유지", fontsize=15)
    fig.text(.02, .025, "오른쪽은 4월 평균 2개/일 기준을 그대로 적용한 결과이며 실제 발행 상한이 아님.\n"
             "5~8월과 9~12월은 각각 집계했다. 추가 기간 결과로 모델·확률 보정·임계값을 바꾸지 않음.", fontsize=9)
    fig.tight_layout(rect=(0, .12, 1, .93))
    second = OUT / "conditional_confirmation.png"
    fig.savefig(second, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    write_json(OUT / "figures.json", {"code_sha256": sha256(Path(__file__)), "inputs": inputs,
                                      "outputs": {path.name: sha256(path) for path in [first, second]}})
