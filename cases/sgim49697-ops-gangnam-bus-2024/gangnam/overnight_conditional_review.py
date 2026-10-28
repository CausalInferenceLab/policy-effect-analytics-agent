"""조건부 저속 라벨의 발생 분포와 개발·시험 경보 분포를 같은 고정 기준에서 진단한다."""

import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .common import CASE, sha256, utcnow, write_json  # noqa: E402
from .overnight_baseline_runner import load_model  # noqa: E402
from .overnight_conditional_low import OUT, verify  # noqa: E402
from .overnight_forecast_metrics import weighted_probability_metrics  # noqa: E402
from .overnight_forecast_models import probability_metrics  # noqa: E402
from .overnight_operations_plots import style  # noqa: E402

MODELS = ["calendar_only", "weekly_delayed", "recent_road_assumption", "delayed_bus_ablation"]
LABELS = ["달력", "주간 도로", "최근 도로 가정", "지연 버스 추가"]


def save(fig, name, note):
    fig.text(.02, .015, note, fontsize=9, va="bottom")
    fig.tight_layout(rect=(0, .11, 1, .93))
    fig.savefig(OUT / name, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def run():
    _, _, manifest = verify()
    audit_path = OUT / "evaluation_audit.json"
    audit = json.loads(audit_path.read_text())
    inputs, summaries, importances = {str(audit_path.relative_to(CASE)): sha256(audit_path)}, [], []
    for entry in manifest["entries"]:
        model = load_model(entry)["estimator"]
        for feature, importance in zip(model.feature_names_, model.get_feature_importance(), strict=True):
            importances.append({"name": entry["name"], "horizon": entry["horizon"], "feature": feature,
                                "prediction_values_change_importance": float(importance)})
        test = next(x for x in audit["predictions"] if x["name"] == entry["name"] and x["horizon"] == entry["horizon"])
        for split, ref in [("calibration", entry["calibration_predictions"]), ("decision", entry["decision_predictions"]), ("test", test)]:
            path = CASE / ref["path"]
            if not path.resolve().is_relative_to((CASE / "data").resolve()) or sha256(path) != ref["sha256"]:
                raise ValueError("조건부 저속 진단의 예측 경로·해시 불일치")
            inputs[ref["path"]] = ref["sha256"]
            frame = pd.read_parquet(path)
            for month, group in frame.groupby(frame.target_start.dt.strftime("%Y-%m")):
                days = pd.Period(month).days_in_month
                base = {"name": entry["name"], "horizon": entry["horizon"], "split": split, "month": month,
                        **probability_metrics(group.label, group.probability),
                        "probability_mean": group.probability.mean(), "probability_unique": group.probability.nunique(),
                        **{f"probability_p{int(q * 100)}": group.probability.quantile(q) for q in [.1, .5, .9]}}
                for rule in ["original_rule", "budget_rule"]:
                    threshold = entry[rule]["threshold"]
                    metrics = weighted_probability_metrics(group.label, group.probability, np.ones(len(group)), threshold, days)
                    summaries.append({**base, "rule": rule, "threshold": threshold,
                                      **{k: float(v[0]) for k, v in metrics.items()}})
    pd.DataFrame(summaries).to_csv(OUT / "monthly_score_diagnostics.csv", index=False)
    pd.DataFrame(importances).to_csv(OUT / "model_feature_importance.csv", index=False)
    style()
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.7))
    names = [("conditional_low", "같은 요일·시간 하위 20%", "#397b91"),
             ("unconditional_low", "링크 전체 하위 20%", "#cc784a"), ("absolute_low", "절대 10km/h 미만", "#8a9eac")]
    for ax, unit in zip(axes, ["hour", "month"], strict=True):
        path = OUT / f"h1_targets_by_{unit}.csv"
        inputs[str(path.relative_to(CASE))] = sha256(path)
        data = pd.read_csv(path)
        for column, label, color in names:
            ax.plot(data[unit], 100 * data[column] / data.rows, marker="o" if unit == "month" else None, label=label, color=color, lw=2)
        ax.set(ylabel="관측 속도 중 해당 라벨 비율 (%)", xlabel="기록 시각" if unit == "hour" else "2025년 시험 월", ylim=(0, 75))
        if unit == "hour":
            ax.set_xticks(list(range(0, 24, 3)))
            ax.axvspan(16.5, 19.5, color="#ddd", alpha=.35)
        else:
            ax.legend(fontsize=9, loc="upper left")
    fig.suptitle("저속의 정의에 따라 반복 출퇴근 패턴과 발생 빈도가 달라짐", fontsize=15)
    save(fig, "target_profiles.png", "세 라벨은 같은 핵심 3개 링크·8,820개 관측에 적용. 1·3시간 예측의 실제 라벨은 같아 한 번만 표시.\n같은 요일·시간 기준도 사고·비반복 혼잡의 정답이 아니며 미래 발생률이 20%로 고정되지 않음.")

    path = OUT / "metrics.csv"
    inputs[str(path.relative_to(CASE))] = sha256(path)
    data = pd.read_csv(path)
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    for horizon, offset, color in [(1, -.16, "#397b91"), (3, .16, "#cc784a")]:
        for ax, metric, scope, title in [(axes[0], "average_precision", "primary_all_hours", "전체 AP"),
                                          (axes[1], "average_precision", "primary_evening_17_19", "저녁 AP"),
                                          (axes[2], "alerts_per_day", "primary_all_hours", "평균 하루 경보: 4월 예산 규칙")]:
            selected = data[data.horizon.eq(horizon) & data.slice.eq(scope) & data.rule.eq("budget_rule")].set_index("name").reindex(MODELS)
            bars = ax.bar(np.arange(4) + offset, selected[metric], width=.3, color=color, label=f"{horizon}시간")
            ax.bar_label(bars, labels=[f"{v:.3f}" if metric == "average_precision" else f"{v:.1f}" for v in selected[metric]], fontsize=8, padding=3)
            ax.set(title=title, xticks=np.arange(4), xticklabels=LABELS)
            ax.tick_params(axis="x", labelrotation=22)
            if metric == "average_precision":
                ax.axhline(selected.prevalence.iloc[0], color="#888", ls="--", lw=.8)
                ax.set_ylim(0, .48)
            else:
                ax.axhline(2, color="#888", ls="--", lw=.8)
                ax.set_ylim(0, 43)
    axes[0].legend(fontsize=9)
    fig.suptitle("조건부 저속 분류는 구분력이 낮고 개발 기간의 경보 제한도 유지하지 못함", fontsize=15)
    save(fig, "classification_limits.png", "점선: AP 그림은 시험 발생률, 경보 그림은 4월 평균 하루 2개 기준. 달력 모델은 무경보이므로 정밀도는 정의되지 않음.\n시험 결과를 보고 모델·라벨·경보 임계값을 바꾸지 않은 탐색 결과. 달력·주간 모델의 두 간격은 같은 입력이므로 독립 확인이 아님.")
    outputs = ["monthly_score_diagnostics.csv", "model_feature_importance.csv", "target_profiles.png", "classification_limits.png"]
    write_json(OUT / "review_audit.json", {"completed_at": utcnow(), "code_sha256": sha256(Path(__file__)),
                                          "inputs": inputs, "outputs": {n: sha256(OUT / n) for n in outputs}})
