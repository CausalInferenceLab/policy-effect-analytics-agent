"""동결 모델의 2025년 여름 시험 예측과 모든 지정 집단의 확률·경보·구간 평가를 저장한다."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .overnight_forecast_data import BASE, OUT, allowed_months
from .overnight_forecast_metrics import (
    probability_bootstrap,
    quantile_bootstrap,
    quantile_losses,
    weighted_probability_metrics,
)
from .overnight_forecast_models import (
    calibrated_probability,
    probability_metrics,
    quantile_prediction,
    raw_score,
)


def slices(frame, primary):
    core = frame[frame.link_id.isin(primary)]
    yield "primary_all_hours", core, True
    yield "primary_evening_17_19", core[core.target_start.dt.hour.isin([17, 18, 19])], True
    for link in primary:
        yield "link_" + link, core[core.link_id.eq(link)], True
    for month, group in core.groupby(core.target_start.dt.strftime("%Y-%m")):
        yield "month_" + month, group, True
    yield "all_selected_links_secondary", frame, False


def evaluate():
    cfg = read_yaml("overnight_forecast_config.yaml")
    allowed_months("test", cfg)
    selection = json.loads((OUT / "selected_models_development.json").read_text())
    audit = json.loads((OUT / "feature_audit_test.json").read_text())
    if audit["protocol_sha256"] != sha256(CASE / "overnight_forecast_config.yaml") or not audit["bus_features_available"]:
        raise ValueError("시험 특징 규약 또는 버스 보조 특징이 맞지 않습니다")
    predictions = BASE / "test_predictions"
    predictions.mkdir(parents=True, exist_ok=True)
    metrics, intervals, prediction_audit, events = [], [], [], []
    for info in audit["outputs"]:
        path = CASE / info["path"]
        if sha256(path) != info["sha256"]:
            raise ValueError("시험 특징 해시 불일치")
        frame = pd.read_parquet(path)
        if not frame.split.eq("test").all() or frame.target_start.dt.year.ge(2026).any():
            raise ValueError("고정한 시험 범위를 벗어난 값")
        for item in [x for x in selection if x["horizon"] == info["horizon"]]:
            model_path = CASE / item["model_path"]
            if sha256(model_path) != item["model_sha256"]:
                raise ValueError("시험 모델 해시 불일치")
            model = joblib.load(model_path)
            valid = frame[frame.speed_kmh.notna()].copy()
            output = valid[["link_id", "target_start", "origin", "speed_kmh"]].copy()
            with threadpool_limits(limits=6):
                if item["family"] == "quantile":
                    output[["q10", "q50", "q90"]] = quantile_prediction(model, valid)
                else:
                    raw = raw_score(model, valid)
                    output["label"] = valid[item["label"]].astype(int)
                    output["raw_probability"] = calibrated_probability(raw)
                    output["probability"] = calibrated_probability(raw, item["calibrator"])
                    output["alert"] = output.probability.ge(item["decision"]["threshold"])
            target = predictions / (item["candidate"] + ".parquet")
            output.to_parquet(target, index=False)
            prediction_audit.append({"candidate": item["candidate"], "path": str(target.relative_to(CASE)), "sha256": sha256(target), "rows": len(output)})
            tags = {k: item[k] for k in ["candidate", "horizon", "feature_set", "family", "parameter", "seed", "label", "role"]}
            for name, group, bootstrap in slices(output, cfg["primary_links"]):
                if group.empty:
                    metrics.append({**tags, "slice": name, "rows": 0, "status": "no_observed_target"})
                    continue
                if item["family"] == "quantile":
                    stats = {key: float(values.mean()) for key, values in quantile_losses(group).items()}
                    stats["rows"] = len(group)
                    confidence, cluster = quantile_bootstrap(group) if bootstrap else ([], {})
                else:
                    threshold = item["decision"]["threshold"]
                    stats = probability_metrics(group.label, group.probability)
                    weighted = weighted_probability_metrics(group.label, group.probability, np.ones(len(group)), threshold,
                                                              group.target_start.dt.date.nunique())
                    stats.update({k: float(v[0]) for k, v in weighted.items() if k in {"precision", "recall", "false_positive_rate", "alerts_per_day"}})
                    stats.update(threshold=threshold, calibration_slope=item["calibrator"]["slope"], alerts=int(group.alert.sum()))
                    confidence, cluster = probability_bootstrap(group, threshold) if bootstrap else ([], {})
                    if name == "primary_all_hours":
                        raw_stats = probability_metrics(group.label, group.raw_probability)
                        metrics.append({**tags, "slice": "primary_all_hours_before_calibration", "status": "evaluated", **raw_stats})
                        if item["role"] == "primary_selected":
                            counts = group.assign(date=group.target_start.dt.strftime("%Y-%m-%d")).groupby("date").agg(
                                observed=("label", "size"), low_speed=("label", "sum"), alerts=("alert", "sum"))
                            events.append(counts.reset_index().assign(candidate=item["candidate"], horizon=item["horizon"]))
                metrics.append({**tags, "slice": name, "status": "evaluated", **stats})
                intervals.extend({**tags, "slice": name, **cluster, **interval} for interval in confidence)
            print(f"동결 시험 평가: {item['candidate']} {len(output):,}행", flush=True)
    pd.DataFrame(metrics).to_csv(OUT / "test_metrics.csv", index=False)
    pd.DataFrame(intervals).to_csv(OUT / "test_week_bootstrap.csv", index=False)
    pd.concat(events, ignore_index=True).to_csv(OUT / "test_primary_daily_events.csv", index=False)
    write_json(OUT / "test_evaluation_audit.json", {"completed_at": utcnow(), "code_sha256": sha256(Path(__file__)),
        "selection_manifest_sha256": sha256(OUT / "selection_manifest.json"), "feature_audit_sha256": sha256(OUT / "feature_audit_test.json"),
        "models_evaluated": len(prediction_audit), "predictions": prediction_audit,
        "outputs": {name: sha256(OUT / name) for name in ["test_metrics.csv", "test_week_bootstrap.csv", "test_primary_daily_events.csv"]},
        "bootstrap": "달력 주를 모든 링크·시간에 공동 적용. 1,000회, 시드 17, 유한 지표가 없는 재표집 횟수도 공개.",
        "scope": "회고 시험. 실제 API 지연·버스 승객 도착시간·정책 반사실 성능을 검증한 것이 아님."})
