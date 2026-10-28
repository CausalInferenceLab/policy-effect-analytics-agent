"""학습 달력 분포 기준 저속의 동일 정보 집합 모델을 준비하고 사후 시험을 별도로 평가한다."""

import importlib.metadata
import json
import time
import warnings
from pathlib import Path

import pandas as pd

from .common import CASE, digest, read_yaml, sha256, utcnow, write_json
from .overnight_baseline_evaluate import probability_rows
from .overnight_baseline_methods import budget_threshold
from .overnight_baseline_runner import KEY_FIELDS, load_model, read_features, verify_manifest
from .overnight_conditional_target import attach, fit_thresholds
from .overnight_forecast_diagnostics import paired_comparison
from .overnight_forecast_models import (
    calibrated_probability,
    choose_threshold,
    fit_calibrator,
    fit_classifier,
    probability_metrics,
    raw_score,
)
from .overnight_relative_ablation import save_model

OUT = CASE / "results/overnight/conditional_low"
RAW = CASE / "data/overnight/conditional_low"
MANIFEST = OUT / "development_manifest.json"


def configuration():
    cfg = read_yaml("overnight_conditional_low_config.yaml")
    _, base, _ = verify_manifest()
    if cfg["locked_year"] != 2026 or cfg["horizons"] != base["horizons"] or cfg["threshold_training"] != base["splits"]["train"]:
        raise ValueError("달력 저속의 잠금 연도·간격·학습 기간 불일치")
    if set(cfg["feature_sets"]) != {"calendar_only", "weekly_delayed", "recent_road_assumption", "delayed_bus_ablation"}:
        raise ValueError("사전 고정 정보 집합과 다릅니다")
    return cfg, base


def predict(entry, model, data, label):
    output = data[KEY_FIELDS].copy()
    output["label"] = data[label].astype(int)
    output["probability"] = calibrated_probability(raw_score(model, data), entry["calibrator"])
    return output


def prepare():
    from threadpoolctl import threadpool_limits

    cfg, base = configuration()
    if MANIFEST.exists():
        verify()
        print("달력 기준 저속의 기존 준비 명세 검증 완료", flush=True)
        return
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    started, entries, inputs, summaries = time.monotonic(), [], {}, []
    thresholds = None
    label = cfg["target_name"]
    maximum_fpr = base["decision"]["maximum_false_positive_rate"]
    decision_days = len(pd.date_range(*base["splits"]["decision"]))
    for horizon in cfg["horizons"]:
        full, info, references = read_features("development", horizon, base)
        inputs.update(references)
        valid = full[full.speed_kmh.notna()].copy()
        table = fit_thresholds(valid[valid.split.eq("train")], cfg)
        if thresholds is None:
            thresholds = table
        elif not thresholds.equals(table):
            raise ValueError("두 간격의 학습 실제값·달력 저속 임계값이 다릅니다")
        frame = attach(valid, thresholds, cfg)
        train = frame[frame.split.eq("train")]
        core = frame[frame.link_id.isin(base["primary_links"])]
        tuning, calibration, decision = [core[core.split.eq(split)] for split in ["tuning", "calibration", "decision"]]
        grouped = frame.groupby(["split", "link_id"]).agg(rows=(label, "size"), positives=(label, "sum"),
                                                         prevalence=(label, "mean")).reset_index()
        summaries.append(grouped.assign(horizon=horizon))
        for feature_set in cfg["feature_sets"]:
            if time.monotonic() - started > cfg["resources"]["maximum_training_hours"] * 3600:
                raise ValueError("달력 저속의 사전 학습 시간 상한 초과")
            signature = digest({"cfg": cfg, "horizon": horizon, "feature_set": feature_set,
                                "features": info["sha256"], "code": sha256(Path(__file__)),
                                "target_code": sha256(CASE / "gangnam/overnight_conditional_target.py")})
            cache = RAW / "models" / f"h{horizon}_{feature_set}.json"
            if cache.exists():
                entry = json.loads(cache.read_text())
                if entry["signature"] != signature or sha256(CASE / entry["model_path"]) != entry["model_sha256"]:
                    raise ValueError("달력 저속 재개 모델의 설정·해시 불일치")
            else:
                begin = time.monotonic()
                with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=cfg["resources"]["cpu_threads"]):
                    warnings.simplefilter("always")
                    model = fit_classifier("catboost", cfg["depth"], train, tuning, info["feature_sets"][feature_set], base, cfg["seed"], label)
                    calibrator = fit_calibrator(raw_score(model, calibration), calibration[label])
                    decision_p = calibrated_probability(raw_score(model, decision), calibrator)
                    tuning_p = calibrated_probability(raw_score(model, tuning))
                entry = {"name": feature_set, "feature_set": feature_set, "horizon": horizon, "target_name": label,
                         "family": "catboost", "signature": signature, "calibrator": calibrator,
                         **save_model(model, cache.with_suffix(".joblib")),
                         "original_rule": choose_threshold(decision[label], decision_p, maximum_fpr),
                         "budget_rule": budget_threshold(decision[label], decision_p, decision_days, 2., maximum_fpr),
                         "tuning_metrics": probability_metrics(tuning[label], tuning_p),
                         "training_event": {"created_at": utcnow(), "elapsed_seconds": time.monotonic() - begin,
                              "training_rows": model["training_rows"], "iterations": model["iterations"],
                              "warnings": sorted({f"{type(w.message).__name__}: {w.message}" for w in caught})}}
                for split, data in [("calibration", calibration), ("decision", decision)]:
                    output = predict(entry, model, data, label)
                    path = RAW / "development_predictions" / f"h{horizon}_{feature_set}_{split}.parquet"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    output.to_parquet(path, index=False)
                    entry[split + "_predictions"] = {"path": str(path.relative_to(CASE)), "sha256": sha256(path), "rows": len(output)}
                write_json(cache, entry)
            entries.append(entry)
            print(f"달력 기준 저속 학습: h{horizon}, {feature_set}, {entry['training_event']['iterations']}회", flush=True)
    thresholds.to_csv(OUT / "training_thresholds.csv", index=False)
    pd.concat(summaries, ignore_index=True).to_csv(OUT / "development_target_counts.csv", index=False)
    paths = ["overnight_conditional_low_config.yaml", "gangnam/overnight_conditional_low.py", "gangnam/overnight_conditional_target.py",
             "gangnam/overnight_relative_ablation.py", "gangnam/overnight_baseline_runner.py", "gangnam/overnight_baseline_methods.py",
             "gangnam/overnight_baseline_evaluate.py", "gangnam/overnight_forecast_models.py", "gangnam/overnight_forecast_diagnostics.py",
             "results/overnight/forecast_baselines/supplement_manifest.json"]
    inputs.update({path: sha256(CASE / path) for path in paths})
    write_json(MANIFEST, {"prepared_at": utcnow(), "configuration": cfg, "entries": entries, "inputs": inputs,
                         "outputs": {name: sha256(OUT / name) for name in ["training_thresholds.csv", "development_target_counts.csv"]},
                         "elapsed_seconds": time.monotonic() - started,
                         "environment": {name: importlib.metadata.version(name) for name in ["numpy", "pandas", "catboost", "scikit-learn", "joblib"]},
                         "interpretation": cfg["interpretation"]})


def verify():
    cfg, base = configuration()
    manifest = json.loads(MANIFEST.read_text())
    for name, expected in manifest["inputs"].items():
        if sha256(CASE / name) != expected:
            raise ValueError(f"달력 저속 준비 입력의 해시 변경: {name}")
    for name, expected in manifest["outputs"].items():
        if sha256(OUT / name) != expected:
            raise ValueError("달력 저속 학습 임계값·집계 해시 변경")
    for entry in manifest["entries"]:
        for item in [{"path": entry["model_path"], "sha256": entry["model_sha256"]},
                     entry["calibration_predictions"], entry["decision_predictions"]]:
            path = CASE / item["path"]
            if not path.resolve().is_relative_to((CASE / "data").resolve()) or sha256(path) != item["sha256"]:
                raise ValueError("달력 저속 모델·개발 예측 경로 또는 해시 변경")
    return cfg, base, manifest


def evaluate():
    cfg, base, manifest = verify()
    table = pd.read_csv(OUT / "training_thresholds.csv", dtype={"link_id": str})
    rows, paired, saved, diagnostics, inputs = [], [], [], [], {}
    label = cfg["target_name"]
    for horizon in cfg["horizons"]:
        full, _, references = read_features("test", horizon, base)
        inputs.update(references)
        core = attach(full[full.link_id.isin(base["primary_links"]) & full.speed_kmh.notna()].copy(), table, cfg)
        entries = [entry for entry in manifest["entries"] if entry["horizon"] == horizon]
        cache, by_name = {}, {entry["name"]: entry for entry in entries}
        for entry in entries:
            output = predict(entry, load_model(entry), core, label)
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
                    a, b = [part[part.target_start.dt.hour.isin([17, 18, 19])] for part in [a, b]]
                for rule in ["original_rule", "budget_rule"]:
                    comparison = paired_comparison(a, b, by_name[left][rule]["threshold"], by_name[right][rule]["threshold"],
                                                   cfg["bootstrap"]["calendar_weeks"], cfg["bootstrap"]["seed"])
                    paired.extend({"horizon": horizon, "slice": "primary_evening_17_19" if evening else "primary_all_hours",
                                   "left": left, "right": right, "rule": rule, **row} for row in comparison)
        summary = core.groupby("calendar_q20_threshold_level")[label].agg(rows="size", positives="sum").reset_index()
        diagnostics.extend(summary.assign(horizon=horizon).to_dict("records"))
        profile = core.assign(hour=core.target_start.dt.hour, month=core.target_start.dt.strftime("%Y-%m"))
        for dimension in ["hour", "month", "link_id"]:
            grouped = profile.groupby(dimension).agg(rows=(label, "size"), conditional_low=(label, "sum"),
                        unconditional_low=("label_q20", "sum"), absolute_low=("label_10", "sum")).reset_index()
            grouped.to_csv(OUT / f"h{horizon}_targets_by_{dimension}.csv", index=False)
        overlap = core.groupby([label, "label_q20", "label_10"]).size().rename("rows").reset_index()
        overlap.to_csv(OUT / f"h{horizon}_target_overlap.csv", index=False)
        print(f"달력 기준 저속 평가: h{horizon}, {len(core):,}행 / 새 표적 {int(core[label].sum()):,}개", flush=True)
    pd.DataFrame(rows).to_csv(OUT / "metrics.csv", index=False)
    pd.DataFrame(paired).to_csv(OUT / "paired_comparisons.csv", index=False)
    write_json(OUT / "evaluation_audit.json", {"completed_at": utcnow(), "development_manifest_sha256": sha256(MANIFEST),
               "code_sha256": sha256(Path(__file__)), "inputs": inputs, "predictions": saved, "threshold_diagnostics": diagnostics,
               "outputs": {path.name: sha256(path) for path in OUT.glob("*.csv")}, "interpretation": cfg["interpretation"]})
