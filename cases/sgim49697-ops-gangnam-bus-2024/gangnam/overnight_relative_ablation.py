"""상대 저속의 같은 CatBoost 설정에서 정보 집합별 예측 추가 가치를 사후 비교한다."""

import importlib.metadata
import json
import time
import warnings
from pathlib import Path

import pandas as pd

from .common import CASE, digest, read_yaml, sha256, utcnow, write_json
from .overnight_baseline_evaluate import prediction, probability_rows
from .overnight_baseline_methods import budget_threshold
from .overnight_baseline_runner import KEY_FIELDS, read_features
from .overnight_baseline_runner import verify_manifest as verify_baselines
from .overnight_forecast_diagnostics import paired_comparison
from .overnight_forecast_models import (
    calibrated_probability,
    choose_threshold,
    fit_calibrator,
    fit_classifier,
    probability_metrics,
    raw_score,
)

OUT = CASE / "results/overnight/relative_ablation"
RAW = CASE / "data/overnight/relative_ablation"
MANIFEST = OUT / "development_manifest.json"


def configuration():
    cfg = read_yaml("overnight_relative_ablation_config.yaml")
    _, base, baselines = verify_baselines()
    if cfg["locked_year"] != base["locked_year"] or cfg["horizons"] != base["horizons"]:
        raise ValueError("추가 정보 비교의 잠금 연도·간격이 다릅니다")
    if set(cfg["feature_sets"]) != {"calendar_only", "weekly_delayed", "recent_road_assumption"}:
        raise ValueError("사전에 고정한 정보 집합과 다릅니다")
    return cfg, base, baselines


def save_model(model, path):
    import joblib

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError("출처 없는 부분 모델을 덮어쓰지 않습니다")
    temporary = path.with_suffix(".joblib.tmp")
    joblib.dump(model, temporary, compress=3)
    temporary.replace(path)
    return {"model_path": str(path.relative_to(CASE)), "model_sha256": sha256(path)}


def prepare():
    from threadpoolctl import threadpool_limits

    cfg, base, baselines = configuration()
    if MANIFEST.exists():
        verify()
        print("추가 정보 비교의 기존 개발 명세 확인 완료", flush=True)
        return
    started = time.monotonic()
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    entries, references = [], {}
    maximum_fpr = base["decision"]["maximum_false_positive_rate"]
    decision_days = len(pd.date_range(*base["splits"]["decision"]))
    for horizon in cfg["horizons"]:
        frame, info, inputs = read_features("development", horizon, base)
        references.update(inputs)
        valid = frame[frame.speed_kmh.notna()]
        train = valid[valid.split.eq("train")]
        core = valid[valid.link_id.isin(base["primary_links"])]
        tuning, calibration, decision = [core[core.split.eq(split)] for split in ["tuning", "calibration", "decision"]]
        for feature_set in cfg["feature_sets"]:
            if time.monotonic() - started > cfg["resources"]["maximum_training_hours"] * 3600:
                raise ValueError("추가 모델 학습 시간 상한 초과")
            signature = digest({"configuration": cfg, "horizon": horizon, "feature_set": feature_set,
                                "features_sha256": info["sha256"], "code_sha256": sha256(Path(__file__)),
                                "model_code_sha256": sha256(CASE / "gangnam/overnight_forecast_models.py")})
            cache = RAW / "models" / f"h{horizon}_{feature_set}.json"
            if cache.exists():
                entry = json.loads(cache.read_text())
                if entry["signature"] != signature or sha256(CASE / entry["model_path"]) != entry["model_sha256"]:
                    raise ValueError("재개 모델 설정·해시 불일치")
            else:
                begin = time.monotonic()
                with warnings.catch_warnings(record=True) as captured, threadpool_limits(limits=cfg["resources"]["cpu_threads"]):
                    warnings.simplefilter("always")
                    model = fit_classifier("catboost", cfg["depth"], train, tuning, info["feature_sets"][feature_set],
                                           base, cfg["seed"], "label_q20")
                    calibrator = fit_calibrator(raw_score(model, calibration), calibration.label_q20)
                    decision_p = calibrated_probability(raw_score(model, decision), calibrator)
                    tuning_p = calibrated_probability(raw_score(model, tuning))
                entry = {"name": feature_set, "horizon": horizon, "feature_set": feature_set, "family": "catboost",
                         "task": "relative_probability", "frozen_comparator": False, "signature": signature,
                         "calibrator": calibrator,
                         **save_model(model, cache.with_suffix(".joblib")),
                         "original_rule": choose_threshold(decision.label_q20, decision_p, maximum_fpr),
                         "budget_rule": budget_threshold(decision.label_q20, decision_p, decision_days, 2., maximum_fpr),
                         "training_event": {"training_rows": model["training_rows"], "iterations": model["iterations"],
                             "elapsed_seconds": time.monotonic() - begin, "created_at": utcnow(),
                             "warnings": sorted({f"{type(w.message).__name__}: {w.message}" for w in captured})},
                         "tuning_metrics": probability_metrics(tuning.label_q20, tuning_p)}
                for split, data in [("calibration", calibration), ("decision", decision)]:
                    output = data[KEY_FIELDS].copy()
                    output["label"] = data.label_q20.astype(int)
                    output["probability"] = calibrated_probability(raw_score(model, data), calibrator)
                    target = RAW / "development_predictions" / f"h{horizon}_{feature_set}_{split}.parquet"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    output.to_parquet(target, index=False)
                    entry[split + "_predictions"] = {"path": str(target.relative_to(CASE)), "sha256": sha256(target), "rows": len(output)}
                write_json(cache, entry)
            entries.append(entry)
            print(f"상대 저속 정보 비교 학습: h{horizon}, {feature_set}, {entry['training_event']['iterations']}회", flush=True)
        frozen = next(entry for entry in baselines["entries"] if entry["horizon"] == horizon and entry["name"] == "catboost_frozen_q20")
        entries.append({**frozen, "name": "frozen_delayed_bus_ablation", "feature_set": "delayed_bus_ablation"})
    paths = ["overnight_relative_ablation_config.yaml", "overnight_forecast_config.yaml",
             "results/overnight/forecast_baselines/supplement_manifest.json", "gangnam/overnight_relative_ablation.py",
             "gangnam/overnight_baseline_evaluate.py", "gangnam/overnight_baseline_methods.py", "gangnam/overnight_baseline_runner.py",
             "gangnam/overnight_forecast_models.py", "gangnam/overnight_forecast_diagnostics.py", "gangnam/overnight_forecast_metrics.py"]
    references.update({path: sha256(CASE / path) for path in paths})
    write_json(MANIFEST, {"prepared_at": utcnow(), "configuration": cfg, "entries": entries, "inputs": references,
                         "elapsed_seconds": time.monotonic() - started,
                         "environment": {name: importlib.metadata.version(name) for name in ["numpy", "pandas", "catboost", "scikit-learn", "joblib"]},
                         "scope": "이미 관측한 시험의 사후 정보 집합 비교. 기존 모델·규칙을 교체하거나 새 독립 시험으로 해석하지 않음."})


def verify():
    cfg, base, _ = configuration()
    manifest = json.loads(MANIFEST.read_text())
    for name, expected in manifest["inputs"].items():
        if sha256(CASE / name) != expected:
            raise ValueError(f"추가 정보 비교 입력 해시 변경: {name}")
    for entry in manifest["entries"]:
        paths = [{"path": entry["model_path"], "sha256": entry["model_sha256"]},
                 entry["calibration_predictions"], entry["decision_predictions"]]
        for item in paths:
            path = CASE / item["path"]
            if not path.resolve().is_relative_to((CASE / "data").resolve()) or sha256(path) != item["sha256"]:
                raise ValueError("추가 정보 비교의 모델·개발 예측 경로 또는 해시 변경")
    return cfg, base, manifest


def evaluate():
    cfg, base, manifest = verify()
    rows, paired, saved, inputs = [], [], [], {}
    for horizon in cfg["horizons"]:
        frame, _, refs = read_features("test", horizon, base)
        inputs.update(refs)
        core = frame[frame.link_id.isin(base["primary_links"]) & frame.speed_kmh.notna()].copy()
        selected = [entry for entry in manifest["entries"] if entry["horizon"] == horizon]
        cache, by_name = {}, {entry["name"]: entry for entry in selected}
        for entry in selected:
            output, refs, _ = prediction(entry, core, {}, base)
            inputs.update(refs)
            rows.extend(probability_rows(output, entry, base))
            target = RAW / "test_predictions" / f"h{horizon}_{entry['name']}.parquet"
            target.parent.mkdir(parents=True, exist_ok=True)
            output.to_parquet(target, index=False)
            saved.append({"name": entry["name"], "horizon": horizon, "path": str(target.relative_to(CASE)),
                          "sha256": sha256(target), "rows": len(output)})
            cache[entry["name"]] = output
        for left, right in cfg["paired_comparisons"]:
            for evening in [False, True]:
                a, b = cache[left], cache[right]
                if evening:
                    a, b = [data[data.target_start.dt.hour.isin([17, 18, 19])] for data in [a, b]]
                for rule in ["original_rule", "budget_rule"]:
                    metrics = paired_comparison(a, b, by_name[left][rule]["threshold"], by_name[right][rule]["threshold"],
                                                cfg["bootstrap"]["calendar_weeks"], cfg["bootstrap"]["seed"])
                    paired.extend({"horizon": horizon, "slice": "primary_evening_17_19" if evening else "primary_all_hours",
                                   "left": left, "right": right, "rule": rule, **row} for row in metrics)
        print(f"상대 저속 정보 비교 평가: h{horizon}, {len(core):,}행", flush=True)
    pd.DataFrame(rows).to_csv(OUT / "metrics.csv", index=False)
    pd.DataFrame(paired).to_csv(OUT / "paired_comparisons.csv", index=False)
    write_json(OUT / "evaluation_audit.json", {"completed_at": utcnow(), "development_manifest_sha256": sha256(MANIFEST),
                    "code_sha256": sha256(Path(__file__)), "inputs": inputs, "predictions": saved,
                    "outputs": {name: sha256(OUT / name) for name in ["metrics.csv", "paired_comparisons.csv"]}})
