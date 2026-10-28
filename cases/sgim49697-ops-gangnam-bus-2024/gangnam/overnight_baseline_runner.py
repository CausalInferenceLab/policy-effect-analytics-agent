"""기존 시험을 재사용하는 기준 모델의 학습·보정·경보 규칙을 개발 기간에만 계산한다."""

from __future__ import annotations

import json
import time
import warnings
from importlib.metadata import version

import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .overnight_baseline_methods import (
    budget_threshold,
    calibration_expansion,
    empirical_model,
    empirical_prediction,
    weekly_prediction,
)
from .overnight_forecast_data import allowed_months
from .overnight_forecast_models import (
    calibrated_probability,
    choose_threshold,
    fit_calibrator,
    fit_classifier,
    fit_seasonal,
    quantile_prediction,
    raw_score,
)

OLD = CASE / "results/overnight/forecast"
OUT = CASE / "results/overnight/forecast_baselines"
RAW = CASE / "data/overnight/forecast_baselines"
KEY_FIELDS = ["link_id", "target_start", "origin", "speed_kmh"]


def configuration():
    cfg = read_yaml("overnight_forecast_baselines_config.yaml")
    base = read_yaml(cfg["base_config"])
    if cfg["locked_year"] != 2026 or base["locked_year"] != cfg["locked_year"]:
        raise ValueError("기준 모델의 잠금 연도 설정이 다릅니다")
    allowed_months("test", base)
    return cfg, base


def read_features(scope, horizon, base):
    audit_path = OLD / f"feature_audit_{scope}.json"
    audit = json.loads(audit_path.read_text())
    info = next(x for x in audit["outputs"] if x["horizon"] == horizon)
    path = CASE / info["path"]
    if not path.resolve().is_relative_to((CASE / "data/overnight/forecast").resolve()) or sha256(path) != info["sha256"]:
        raise ValueError("기준 모델의 기존 특징 경로·해시 불일치")
    if audit["protocol_sha256"] != sha256(CASE / "overnight_forecast_config.yaml"):
        raise ValueError("기존 특징 규약 해시 불일치")
    frame = pd.read_parquet(path)
    if frame.target_start.dt.year.ge(base["locked_year"]).any() or frame.duplicated(["link_id", "target_start"]).any():
        raise ValueError("기준 모델 특징의 잠금 연도·중복 키 오류")
    permitted = {"test"} if scope == "test" else {"train", "tuning", "calibration", "decision"}
    if not set(frame.split.unique()).issubset(permitted):
        raise ValueError("기준 모델 특징에 허용되지 않은 분할이 있습니다")
    for split, part in frame.groupby("split", observed=True):
        dates = part.target_start.dt.strftime("%Y-%m-%d")
        if not dates.between(*base["splits"][split]).all():
            raise ValueError("기준 모델 분할의 날짜 경계가 다릅니다")
    return frame, info, {str(audit_path.relative_to(CASE)): sha256(audit_path), info["path"]: info["sha256"]}


def load_model(entry):
    import joblib

    path = CASE / entry["model_path"]
    if not path.resolve().is_relative_to((CASE / "data").resolve()) or sha256(path) != entry["model_sha256"]:
        raise ValueError("기준 비교 모델 경로·해시 불일치")
    return joblib.load(path)


def store_model(model, name):
    import joblib

    path = RAW / "models" / (name + ".joblib")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError(f"기존 기준 모델을 덮어쓰지 않습니다: {path.name}")
    temporary = path.with_suffix(".joblib.tmp")
    joblib.dump(model, temporary, compress=3)
    temporary.replace(path)
    return {"model_path": str(path.relative_to(CASE)), "model_sha256": sha256(path)}


def quantiles(entry, model, frame, cfg):
    if entry["name"] == "calendar_empirical":
        prediction, levels = empirical_prediction(model, frame)
        return prediction, {"fallback_rows": int((levels > 0).sum())}
    if entry["name"] == "weekly_empirical":
        spec = cfg["quantiles"]["baselines"]["weekly_empirical"]
        prediction, fallback = weekly_prediction(model, frame, spec["lag_columns"], spec["minimum_observed_lags"])
        return prediction, {"fallback_rows": int(fallback.sum())}
    return quantile_prediction(model, frame), {"fallback_rows": 0}


def save_development(frame, entry, split, probability=None, prediction=None):
    output = frame[KEY_FIELDS].copy()
    if probability is not None:
        output["label"] = frame.label_q20.astype(int)
        output["probability"] = probability
    else:
        output[["q10", "q50", "q90"]] = prediction
    path = RAW / "development_predictions" / f"h{entry['horizon']}_{entry['name']}_{split}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    output.to_parquet(path, index=False)
    return {"path": str(path.relative_to(CASE)), "sha256": sha256(path), "rows": len(output)}


def prepare():
    from threadpoolctl import threadpool_limits

    cfg, base = configuration()
    selection_path = OUT / "supplement_manifest.json"
    if selection_path.exists():
        verify_manifest()
        print("기존 기준 모델·개발 선택 명세의 해시 확인 완료", flush=True)
        return
    start = time.monotonic()
    OUT.mkdir(parents=True, exist_ok=True)
    original = json.loads((OLD / "selected_models_development.json").read_text())
    budget = cfg["relative_probability"]["additional_budget"]
    decision_days = len(pd.date_range(*base["splits"]["decision"]))
    seed = cfg["relative_probability"]["seed"]
    entries, inputs, events = [], {}, []
    for horizon in base["horizons"]:
        frame, info, references = read_features("development", horizon, base)
        inputs.update(references)
        valid = frame[frame.speed_kmh.notna()]
        train = valid[valid.split.eq("train")]
        core = valid[valid.link_id.isin(base["primary_links"])]
        calibration, decision = core[core.split.eq("calibration")], core[core.split.eq("decision")]
        if train.empty or calibration.empty or decision.empty:
            raise ValueError("기준 모델 학습·보정·선택 표본이 비었습니다")
        relative = []
        for spec in cfg["relative_probability"]["models"]:
            if time.monotonic() - start > cfg["resources"]["maximum_training_hours"] * 3600:
                raise ValueError("기준 모델 학습 시간 상한 초과")
            before = time.monotonic()
            with warnings.catch_warnings(record=True) as captured, threadpool_limits(limits=cfg["resources"]["cpu_threads"]):
                warnings.simplefilter("always")
                if spec["family"] == "seasonal":
                    model = fit_seasonal(train, "label_q20", spec["smoothing_count"])
                else:
                    model = fit_classifier("logistic", spec["C"], train, train.iloc[:0], info["feature_sets"][spec["feature_set"]], base, seed, "label_q20")
                calibrator = fit_calibrator(raw_score(model, calibration), calibration.label_q20)
            entry = {"name": spec["name"], "horizon": horizon, "task": "relative_probability", "family": spec["family"],
                     "frozen_comparator": False, "calibrator": calibrator, **store_model(model, f"h{horizon}_{spec['name']}")}
            relative.append((entry, model))
            events.append({"name": entry["name"], "horizon": horizon, "training_rows": model.get("training_rows", len(train)),
                           "elapsed_seconds": time.monotonic() - before, "iterations": model.get("iterations"),
                           "warnings": sorted({f"{type(w.message).__name__}: {w.message}" for w in captured})})
        old = next(x for x in original if x["horizon"] == horizon and x["role"] == "training_q20_label_sensitivity")
        relative.append(({"name": "catboost_frozen_q20", "horizon": horizon, "task": "relative_probability", "family": "catboost",
                          "frozen_comparator": True, "candidate": old["candidate"], "calibrator": old["calibrator"],
                          "model_path": old["model_path"], "model_sha256": old["model_sha256"], "original_decision": old["decision"]}, load_model(old)))
        for entry, model in relative:
            probability = calibrated_probability(raw_score(model, decision), entry["calibrator"])
            entry["original_rule"] = entry.get("original_decision") or choose_threshold(decision.label_q20, probability, base["decision"]["maximum_false_positive_rate"])
            entry["budget_rule"] = budget_threshold(decision.label_q20, probability, decision_days,
                                                     budget["maximum_alerts_per_calendar_day"], budget["maximum_false_positive_rate"])
            entry["decision_predictions"] = save_development(decision, entry, "decision", probability=probability)
            entry["calibration_predictions"] = save_development(calibration, entry, "calibration", probability=calibrated_probability(raw_score(model, calibration), entry["calibrator"]))
            entries.append(entry)
        empirical = empirical_model(train, cfg["quantiles"]["baselines"]["calendar_empirical"]["minimum_group_rows"])
        stored = store_model(empirical, f"h{horizon}_calendar_empirical")
        qs = [({"name": name, "horizon": horizon, "task": "quantile", "frozen_comparator": False, **stored}, empirical)
              for name in ["calendar_empirical", "weekly_empirical"]]
        old = next(x for x in original if x["horizon"] == horizon and x["role"] == "quantile_selected")
        qs.append(({"name": "catboost_frozen_quantile", "horizon": horizon, "task": "quantile", "frozen_comparator": True,
                    "candidate": old["candidate"], "model_path": old["model_path"], "model_sha256": old["model_sha256"]}, load_model(old)))
        for entry, model in qs:
            prediction, fallback = quantiles(entry, model, calibration, cfg)
            entry["calibration"] = {**calibration_expansion(calibration.speed_kmh, prediction,
                                      cfg["quantiles"]["calibration_sensitivity"]["nominal_coverage"]), **fallback}
            entry["calibration_predictions"] = save_development(calibration, entry, "calibration", prediction=prediction)
            entries.append(entry)
        print(f"기준 모델 개발 완료: h{horizon}, 학습 {len(train):,}, 보정 {len(calibration):,}, 선택 {len(decision):,}", flush=True)
        del frame, valid, train, core
    references = ["overnight_forecast_baselines_config.yaml", "overnight_forecast_config.yaml",
                  "gangnam/overnight_baseline_methods.py", "gangnam/overnight_baseline_runner.py", "gangnam/overnight_baseline_evaluate.py",
                  "gangnam/overnight_forecast_models.py", "gangnam/overnight_forecast_metrics.py",
                  "gangnam/overnight_forecast_diagnostics.py", "gangnam/common.py",
                  "results/overnight/forecast/selection_manifest.json", "results/overnight/forecast/selected_models_development.json",
                  "results/overnight/forecast/test_evaluation_audit.json"]
    inputs.update({p: sha256(CASE / p) for p in references})
    write_json(selection_path, {"prepared_at": utcnow(), "mode": cfg["mode"], "inputs": inputs, "entries": entries,
                                "training_events": events, "elapsed_seconds": time.monotonic() - start,
                                "environment": {name: version(name) for name in ["numpy", "pandas", "scikit-learn", "catboost", "joblib"]},
                                "scope": "이미 관측한 2025년 시험의 사후 기준 비교; 새 독립 시험 또는 기존 모델 재선택이 아님"})


def verify_manifest():
    cfg, base = configuration()
    manifest = json.loads((OUT / "supplement_manifest.json").read_text())
    for path, expected in manifest["inputs"].items():
        if sha256(CASE / path) != expected:
            raise ValueError(f"기준 모델 개발 이후 입력·코드 변경: {path}")
    for entry in manifest["entries"]:
        if sha256(CASE / entry["model_path"]) != entry["model_sha256"]:
            raise ValueError("기준 모델 해시 변경")
        for name in ["decision_predictions", "calibration_predictions"]:
            if name in entry and sha256(CASE / entry[name]["path"]) != entry[name]["sha256"]:
                raise ValueError("기준 모델 개발 예측 해시 변경")
    return cfg, base, manifest
