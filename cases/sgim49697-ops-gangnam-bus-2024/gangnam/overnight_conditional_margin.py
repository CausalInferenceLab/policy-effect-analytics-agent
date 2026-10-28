"""고정 분위수 속도 예측과 달력 저속 기준의 차이를 개발 기간에서 보정해 비교한다."""

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .overnight_baseline_evaluate import probability_rows
from .overnight_baseline_methods import budget_threshold
from .overnight_baseline_runner import KEY_FIELDS
from .overnight_conditional_low import verify as verify_target
from .overnight_conditional_target import attach
from .overnight_forecast_diagnostics import align_predictions, paired_comparison
from .overnight_forecast_models import calibrated_probability, choose_threshold, fit_calibrator
from .overnight_interval_calibration import verify as verify_quantiles

OUT = CASE / "results/overnight/conditional_margin"
RAW = CASE / "data/overnight/conditional_margin"
MANIFEST = OUT / "preparation_manifest.json"


def margin_scores(frame, floor):
    """양수는 예측 중앙값이 저속 기준보다 낮다는 뜻이며 실제 속도·라벨을 읽지 않는다."""
    values = frame[["q10", "q50", "q90", "calendar_q20_threshold"]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or not np.isfinite(floor) or floor <= 0:
        raise ValueError("차이 점수에는 유한한 분위수·임계값과 양수 폭 하한이 필요합니다")
    if np.any(values[:, 0] > values[:, 1]) or np.any(values[:, 1] > values[:, 2]) or np.any(values[:, 3] <= 0):
        raise ValueError("교차 분위수 또는 양수가 아닌 달력 임계값")
    gap = values[:, 3] - values[:, 1]
    width = values[:, 2] - values[:, 0]
    return {"median_gap": gap, "scaled_median_gap": gap / np.maximum(width, floor)}, int((width < floor).sum())


def warmup_parts(frame, base):
    dates = frame.target_start.dt.strftime("%Y-%m-%d")
    masks = {name: dates.between(*base["splits"][name]) for name in ["calibration", "decision"]}
    if frame.empty or not (masks["calibration"] | masks["decision"]).all() or not all(mask.any() for mask in masks.values()):
        raise ValueError("개발 보정에는 지정된 3월·4월만 모두 있어야 합니다")
    return {name: frame.loc[mask].copy() for name, mask in masks.items()}


def read_prediction(ref):
    path = CASE / ref["path"]
    if not path.resolve().is_relative_to((CASE / "data").resolve()) or sha256(path) != ref["sha256"]:
        raise ValueError("차이 점수의 기존 예측 경로·해시 불일치")
    return pd.read_parquet(path)


def configuration():
    cfg = read_yaml("overnight_conditional_margin_config.yaml")
    target, base, _ = verify_target()
    _, other_base, quantiles = verify_quantiles()
    if base != other_base or cfg["locked_year"] != 2026 or cfg["horizons"] != base["horizons"]:
        raise ValueError("차이 점수의 원래 예측 설정·잠금 연도 불일치")
    if set(cfg["scores"]) != {"median_gap", "scaled_median_gap"} or cfg["width_floor_kmh"] <= 0:
        raise ValueError("고정한 차이 점수·폭 하한 설정과 다릅니다")
    return cfg, target, base, quantiles


def predict(frame, scores, calibrator, label):
    result = frame[KEY_FIELDS].copy()
    result["label"] = frame[label].astype(int)
    result["probability"] = calibrated_probability(scores, calibrator)
    return result


def prepare():
    cfg, target, base, quantiles = configuration()
    if MANIFEST.exists():
        verify()
        print("기존 차이 점수 개발 명세 검증 완료", flush=True)
        return
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    table = pd.read_csv(CASE / cfg["threshold_table"], dtype={"link_id": str})
    paths = ["overnight_conditional_margin_config.yaml", cfg["target_config"], cfg["target_manifest"], cfg["threshold_table"],
             cfg["quantile_manifest"], "results/overnight/forecast_baselines/evaluation_audit.json",
             "results/overnight/conditional_low/evaluation_audit.json", "gangnam/overnight_conditional_margin.py",
             "gangnam/overnight_conditional_target.py", "gangnam/overnight_forecast_models.py",
             "gangnam/overnight_baseline_methods.py", "gangnam/overnight_baseline_evaluate.py", "gangnam/overnight_forecast_diagnostics.py"]
    inputs = {name: sha256(CASE / name) for name in paths}
    entries = []
    for source in quantiles["entries"]:
        horizon = source["horizon"]
        frame = attach(read_prediction(source["warmup"]), table, target)
        inputs[source["warmup"]["path"]] = source["warmup"]["sha256"]
        parts = warmup_parts(frame, base)
        scores = {split: margin_scores(part, cfg["width_floor_kmh"])[0] for split, part in parts.items()}
        for name in cfg["scores"]:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                calibrator = fit_calibrator(scores["calibration"][name], parts["calibration"][target["target_name"]])
            entry = {"name": name, "horizon": horizon, "calibrator": calibrator,
                     "warnings": [str(w.message) for w in caught], "source_quantile_candidate": source["candidate"]}
            for split, part in parts.items():
                output = predict(part, scores[split][name], calibrator, target["target_name"])
                path = RAW / f"h{horizon}_{name}_{split}.parquet"
                output.to_parquet(path, index=False)
                inputs[str(path.relative_to(CASE))] = sha256(path)
                entry[split + "_predictions"] = {"path": str(path.relative_to(CASE)), "sha256": sha256(path), "rows": len(output)}
                if split == "decision":
                    maximum = base["decision"]["maximum_false_positive_rate"]
                    entry["original_rule"] = choose_threshold(output.label, output.probability, maximum)
                    entry["budget_rule"] = budget_threshold(output.label, output.probability,
                        len(pd.date_range(*base["splits"]["decision"])), maximum_alerts=2., maximum_fpr=maximum)
            entries.append(entry)
    write_json(MANIFEST, {"prepared_at": utcnow(), "configuration": cfg, "entries": entries, "inputs": inputs,
                         "interpretation": cfg["interpretation"]})
    print(f"차이 점수 보정 준비: {len(entries)}개, 회귀 재학습 0회", flush=True)


def verify():
    cfg, target, base, _ = configuration()
    manifest = json.loads(MANIFEST.read_text())
    for name, expected in manifest["inputs"].items():
        if sha256(CASE / name) != expected:
            raise ValueError(f"차이 점수의 개발 입력·코드·예측 해시 변경: {name}")
    return cfg, target, base, manifest


def evaluate():
    cfg, target, base, manifest = verify()
    table = pd.read_csv(CASE / cfg["threshold_table"], dtype={"link_id": str})
    source = json.loads((CASE / "results/overnight/forecast_baselines/evaluation_audit.json").read_text())
    classifiers = json.loads((CASE / "results/overnight/conditional_low/evaluation_audit.json").read_text())
    _, _, class_manifest = verify_target()
    rows, paired, saved, diagnostics, inputs = [], [], [], [], {}
    for horizon in cfg["horizons"]:
        ref = next(x for x in source["predictions"] if x["name"] == "catboost_frozen_quantile" and x["variant"] == "raw" and x["horizon"] == horizon)
        frame = attach(read_prediction(ref), table, target)
        if not frame.target_start.dt.strftime("%Y-%m-%d").between(*base["splits"]["test"]).all():
            raise ValueError("차이 점수의 원래 시험 날짜 범위 밖입니다")
        inputs[ref["path"]] = ref["sha256"]
        scores, floored = margin_scores(frame, cfg["width_floor_kmh"])
        class_ref = next(x for x in classifiers["predictions"] if x["name"] == "recent_road_assumption" and x["horizon"] == horizon)
        predictions = {"recent_road_classifier": read_prediction(class_ref)}
        inputs[class_ref["path"]] = class_ref["sha256"]
        entries = {"recent_road_classifier": next(x for x in class_manifest["entries"] if x["name"] == "recent_road_assumption" and x["horizon"] == horizon)}
        for entry in [x for x in manifest["entries"] if x["horizon"] == horizon]:
            output = predict(frame, scores[entry["name"]], entry["calibrator"], target["target_name"])
            align_predictions(output, predictions["recent_road_classifier"])
            rows.extend(probability_rows(output, entry, base))
            path = RAW / f"h{horizon}_{entry['name']}_test.parquet"
            output.to_parquet(path, index=False)
            saved.append({"name": entry["name"], "horizon": horizon, "path": str(path.relative_to(CASE)), "sha256": sha256(path), "rows": len(output)})
            predictions[entry["name"]], entries[entry["name"]] = output, entry
        for left, right in [("median_gap", "recent_road_classifier"), ("scaled_median_gap", "recent_road_classifier"), ("scaled_median_gap", "median_gap")]:
            for scope in ["primary_all_hours", "primary_evening_17_19"]:
                a, b = predictions[left], predictions[right]
                if scope.endswith("17_19"):
                    a, b = [x[x.target_start.dt.hour.isin([17, 18, 19])] for x in [a, b]]
                for rule in ["original_rule", "budget_rule"]:
                    measured = paired_comparison(a, b, entries[left][rule]["threshold"], entries[right][rule]["threshold"],
                                                 cfg["bootstrap"]["calendar_weeks"], cfg["bootstrap"]["seed"])
                    paired.extend({"horizon": horizon, "slice": scope, "left": left, "right": right, "rule": rule, **m} for m in measured)
        diagnostics.append({"horizon": horizon, "rows": len(frame), "width_floored_rows": floored, "positives": int(frame[target["target_name"]].sum())})
        print(f"차이 점수 평가: h{horizon}, {len(frame):,}개 관측", flush=True)
    pd.DataFrame(rows).to_csv(OUT / "metrics.csv", index=False)
    pd.DataFrame(paired).to_csv(OUT / "paired_comparisons.csv", index=False)
    write_json(OUT / "evaluation_audit.json", {"completed_at": utcnow(), "preparation_manifest_sha256": sha256(MANIFEST),
        "code_sha256": sha256(Path(__file__)), "inputs": inputs, "predictions": saved, "diagnostics": diagnostics,
        "outputs": {p.name: sha256(p) for p in OUT.glob("*.csv")}, "interpretation": cfg["interpretation"]})
