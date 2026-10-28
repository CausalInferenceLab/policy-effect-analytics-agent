"""개발 기간에서만 후보 선택·확률 보정·경보 기준을 정하고 모델별 재개 기록을 남긴다."""

from __future__ import annotations

import json
import time
import warnings
from pathlib import Path

import joblib
import pandas as pd
from threadpoolctl import threadpool_limits

from .common import CASE, digest, read_yaml, sha256, utcnow, write_json
from .overnight_forecast_data import BASE, OUT
from .overnight_forecast_models import (
    calibrated_probability,
    choose_threshold,
    fit_calibrator,
    fit_classifier,
    fit_quantile,
    fit_seasonal,
    probability_metrics,
    quantile_metrics,
    quantile_prediction,
    raw_score,
)

MODELS = BASE / "models"


def candidate_id(horizon, feature_set, family, parameter, seed, label):
    return f"h{horizon}_{feature_set}_{family}_{parameter}_s{seed}_{label}"


def train_candidate(frame, info, feature_set, family, parameter, cfg, seed, label="label_10"):
    horizon = info["horizon"]
    name = candidate_id(horizon, feature_set, family, parameter, seed, label)
    path = MODELS / (name + ".joblib")
    meta_path = OUT / "candidates" / (name + ".json")
    code = CASE / "gangnam/overnight_forecast_models.py"
    signature = digest({"protocol": sha256(CASE / "overnight_forecast_config.yaml"), "features": info["sha256"],
                        "model_code": sha256(code), "candidate": name, "runner": sha256(Path(__file__))})
    if path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text())
        if meta["signature"] != signature or meta["model_sha256"] != sha256(path):
            raise ValueError(f"기존 모델·입력·설정 해시가 달라 재개할 수 없습니다: {name}")
        print(f"학습 결과 재사용: {name}", flush=True)
        return meta
    target = "speed_kmh" if family == "quantile" else label
    train = frame[frame.split.eq("train") & frame[target].notna()]
    tuning = frame[frame.split.eq("tuning") & frame.link_id.isin(cfg["primary_links"]) & frame[target].notna()]
    if train.empty or tuning.empty:
        raise ValueError("학습·핵심 링크 선택 표본이 비었습니다")
    start = time.monotonic()
    print(f"학습 시작: {name}, 학습 유효 {len(train):,}행, 선택 {len(tuning):,}행", flush=True)
    with warnings.catch_warnings(record=True) as captured, threadpool_limits(limits=6):
        warnings.simplefilter("always")
        if family == "seasonal":
            model = fit_seasonal(train, label, cfg["models"]["seasonal_probability"]["smoothing_count"])
        elif family == "quantile":
            model = fit_quantile(parameter, train, tuning, info["feature_sets"][feature_set], cfg, seed)
        else:
            model = fit_classifier(family, parameter, train, tuning, info["feature_sets"][feature_set], cfg, seed, label)
    if family == "quantile":
        metrics = quantile_metrics(tuning.speed_kmh.to_numpy(), quantile_prediction(model, tuning), model["quantiles"])
    else:
        probability = calibrated_probability(raw_score(model, tuning))
        metrics = probability_metrics(tuning[label].to_numpy(), probability)
    MODELS.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".joblib.tmp")
    joblib.dump(model, temp, compress=3)
    temp.replace(path)
    meta = {"candidate": name, "horizon": horizon, "feature_set": feature_set, "family": family, "parameter": parameter,
        "seed": seed, "label": label, "signature": signature, "model_path": str(path.relative_to(CASE)),
        "model_sha256": sha256(path), "iterations": model.get("iterations"), "training_rows": model.get("training_rows", len(train)),
        "tuning_metrics": metrics, "elapsed_seconds": time.monotonic() - start, "created_at": utcnow(),
        "warnings": sorted({f"{type(w.message).__name__}: {w.message}" for w in captured}),
        "feature_sha256": info["sha256"], "model_code_sha256": sha256(code), "runner_sha256": sha256(Path(__file__))}
    write_json(meta_path, meta)
    print(f"학습 완료: {name}, {meta['elapsed_seconds']:.1f}초, 선택 지표 {metrics}", flush=True)
    return meta


def calibrate_and_choose(meta, frame, cfg):
    model_path = CASE / meta["model_path"]
    if sha256(model_path) != meta["model_sha256"]:
        raise ValueError("보정 대상 모델 해시 불일치")
    model = joblib.load(model_path)
    if meta["family"] == "quantile":
        return {**meta, "calibrator": None, "decision": None}
    label = meta["label"]
    valid = frame.link_id.isin(cfg["primary_links"]) & frame[label].notna()
    calibration = frame[valid & frame.split.eq("calibration")]
    decision = frame[valid & frame.split.eq("decision")]
    raw = raw_score(model, calibration)
    calibrator = fit_calibrator(raw, calibration[label])
    decision_probability = calibrated_probability(raw_score(model, decision), calibrator)
    threshold = choose_threshold(decision[label], decision_probability, cfg["decision"]["maximum_false_positive_rate"])
    return {**meta, "calibrator": calibrator, "decision": threshold,
        "calibration_metrics_before": probability_metrics(calibration[label], calibrated_probability(raw)),
        "calibration_metrics_after": probability_metrics(calibration[label], calibrated_probability(raw, calibrator)),
        "decision_metrics": probability_metrics(decision[label], decision_probability),
        "calibration_and_decision_scope": "fixed_primary_three_links"}


def run():
    if (OUT / "selection_manifest.json").exists():
        raise ValueError("시험 전 동결 이후 추가 학습은 허용하지 않습니다")
    cfg = read_yaml("overnight_forecast_config.yaml")
    audit = json.loads((OUT / "feature_audit_development.json").read_text())
    if audit["protocol_sha256"] != sha256(CASE / "overnight_forecast_config.yaml"):
        raise ValueError("특징 생성 이후 예측 규약 변경")
    if not audit["bus_features_available"]:
        raise ValueError("버스 보조 특징을 준비한 뒤 모든 후보를 함께 선택합니다")
    candidates, selected = [], []
    spent = 0.

    def fit(*args, **kwargs):
        nonlocal spent
        if spent >= cfg["training"]["resource_budget_hours"] * 3600:
            raise RuntimeError("고정한 모델 학습 4시간 예산을 넘었습니다. 시험값을 열지 않고 미완료 상태를 기록합니다")
        result = train_candidate(*args, **kwargs)
        spent += result["elapsed_seconds"]
        candidates.append(result)
        write_json(OUT / "training_progress.json", {"status": "in_progress", "accounted_training_seconds": spent, "candidates": candidates})
        return result

    for info in audit["outputs"]:
        path = CASE / info["path"]
        if sha256(path) != info["sha256"]:
            raise ValueError("모델 특징 해시 불일치")
        frame = pd.read_parquet(path)
        if frame.split.eq("test").any() or frame.target_start.dt.year.ge(2026).any():
            raise ValueError("개발 학습 입력에 시험·잠금 자료가 있습니다")
        seed = cfg["training"]["primary_seed"]
        seasonal = fit(frame, info, "calendar_only", "seasonal", "fixed", cfg, seed)
        horizon_selected = [seasonal]
        for feature_set in info["feature_sets"]:
            for family, parameters in [("logistic", cfg["models"]["logistic"]["C"]),
                                       ("catboost", cfg["models"]["catboost_classifier"]["depth"])]:
                options = [fit(frame, info, feature_set, family, parameter, cfg, seed) for parameter in parameters]
                best = max(options, key=lambda x: (x["tuning_metrics"]["average_precision"], -float(x["parameter"])))
                horizon_selected.append(best)
        champion = max(horizon_selected, key=lambda x: x["tuning_metrics"]["average_precision"])
        for candidate in horizon_selected:
            candidate = {**candidate, "role": "primary_selected" if candidate["candidate"] == champion["candidate"] else "selected_baseline"}
            selected.append(calibrate_and_choose(candidate, frame, cfg))
        if champion["family"] != "seasonal":
            repeated = fit(frame, info, champion["feature_set"], champion["family"], champion["parameter"], cfg,
                           cfg["training"]["seeds"][1])
            selected.append(calibrate_and_choose({**repeated, "role": "primary_seed_sensitivity"}, frame, cfg))
        relative = fit(frame, info, champion["feature_set"], champion["family"], champion["parameter"], cfg, seed, "label_q20")
        selected.append(calibrate_and_choose({**relative, "role": "training_q20_label_sensitivity"}, frame, cfg))
        quantiles = [fit(frame, info, cfg["models"]["catboost_quantile"]["feature_set"], "quantile", depth, cfg, seed)
                     for depth in cfg["models"]["catboost_quantile"]["depth"]]
        best_quantile = min(quantiles, key=lambda x: (x["tuning_metrics"]["mean_pinball"], x["parameter"]))
        selected.append({**best_quantile, "role": "quantile_selected", "calibrator": None, "decision": None})
        write_json(OUT / "selected_models_development.json", selected)
        print(f"{info['horizon']}시간 후보 선택·보정·경보 기준 완료: {champion['candidate']}", flush=True)
    write_json(OUT / "training_progress.json", {"status": "selection_ready_for_review_and_freeze", "accounted_training_seconds": spent,
        "candidates": candidates, "selected_count": len(selected), "completed_at": utcnow()})
    flat = [{k: v for k, v in item.items() if k in {"candidate", "horizon", "feature_set", "family", "parameter", "seed", "label", "iterations", "training_rows", "elapsed_seconds"}}
            | {f"tuning_{k}": v for k, v in item["tuning_metrics"].items()} for item in candidates]
    pd.DataFrame(flat).to_csv(OUT / "tuning_candidates.csv", index=False)
    print(f"시험 전 선택 준비 완료: 후보 {len(candidates)}개, 보정·선택 {len(selected)}개", flush=True)
