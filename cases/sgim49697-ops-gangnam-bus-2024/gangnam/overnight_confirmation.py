"""미열람 2025년 가을·겨울에서 기존 고정 모델과 경보 기준을 추가 평가한다."""

import copy
import json

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .overnight_baseline_evaluate import primary_slices, probability_rows
from .overnight_baseline_methods import expand_quantiles, interval_losses, paired_intervals
from .overnight_baseline_runner import KEY_FIELDS, load_model, quantiles
from .overnight_conditional_margin import margin_scores
from .overnight_conditional_target import attach
from .overnight_confirmation_data import MANIFEST, OUT, RAW, verify
from .overnight_forecast_diagnostics import paired_comparison
from .overnight_forecast_models import calibrated_probability, raw_score


def evaluation_frame(frame, cfg):
    """기간·중복·핵심 링크를 확인한 뒤 실제값 부재를 평가 분모에서 명시적으로 분리한다."""
    dates = frame.target_start.dt.strftime("%Y-%m-%d")
    if (frame.empty or not dates.between(*cfg["period"]).all() or frame.target_start.dt.year.ge(2026).any()
            or not set(frame.link_id).issubset(cfg["primary_links"]) or frame.duplicated(["link_id", "target_start"]).any()):
        raise ValueError("추가 평가의 날짜·링크·중복 조건 오류")
    finite = frame.speed_kmh.notna()
    if not np.isfinite(frame.loc[finite, "speed_kmh"]).all() or frame.loc[finite, "speed_kmh"].le(0).any():
        raise ValueError("추가 평가 속도의 유한 양수 조건 오류")
    return frame[finite].copy(), {"expected_rows": len(frame), "known_rows": int(finite.sum()), "unknown_rows": int((~finite).sum())}


def evaluate():
    from threadpoolctl import threadpool_limits

    cfg, manifest = verify()
    audit = json.loads((OUT / "feature_audit.json").read_text())
    if audit["selection_manifest_sha256"] != sha256(MANIFEST) or audit["coverage_sha256"] != sha256(OUT / "coverage.csv"):
        raise ValueError("추가 평가 특징·관측률 명세 변경")
    coverage = pd.read_csv(OUT / "coverage.csv")
    quality = bool(coverage.quality_pass.eq(True).all() and not audit["metadata_exclusions"])
    base = read_yaml("overnight_forecast_config.yaml")
    metric_base = copy.deepcopy(base)
    metric_base["splits"]["test"] = cfg["period"]
    baseline_cfg = read_yaml("overnight_forecast_baselines_config.yaml")
    conditional_cfg = read_yaml("overnight_conditional_low_config.yaml")
    margin_cfg = read_yaml("overnight_conditional_margin_config.yaml")
    thresholds = pd.read_csv(CASE / "results/overnight/conditional_low/training_thresholds.csv", dtype={"link_id": str})
    metrics_p, metrics_q, paired_p, paired_q, predictions, states, diagnostics = [], [], [], [], [], [], []
    inputs = {"results/overnight/confirmation/selection_manifest.json": sha256(MANIFEST),
              "results/overnight/confirmation/feature_audit.json": sha256(OUT / "feature_audit.json")}
    for horizon in cfg["horizons"]:
        ref = next(item for item in audit["outputs"] if item["horizon"] == horizon)
        path = (CASE / ref["path"]).resolve()
        if not path.is_relative_to(RAW.resolve()) or sha256(path) != ref["sha256"]:
            raise ValueError("추가 평가 특징 경로·해시 변경")
        inputs[ref["path"]] = ref["sha256"]
        frame, counts = evaluation_frame(pd.read_parquet(path), cfg)
        if frame.empty:
            raise ValueError("추가 검증의 유효 실제값이 없습니다. 대체 링크로 평가하지 않습니다")
        labelled = attach(frame, thresholds, conditional_cfg)
        states.append({"horizon": horizon, **counts, "relative_events": int(frame.label_q20.sum()),
                       "conditional_events": int(labelled[conditional_cfg["target_name"]].sum()),
                       "threshold_fallback_rows": int(labelled.calendar_q20_threshold_level.ne("link_weekday_hour").sum())})
        cache, entry_cache = {}, {}
        selected = [entry for entry in manifest["entries"] if entry["horizon"] == horizon]
        with threadpool_limits(limits=cfg["resources"]["cpu_threads"]):
            # 분위수 점수는 실제값을 사용하지 않는 기존 예측값에서 계산한다.
            for entry in [item for item in selected if item["confirmation_task"] == "quantile"]:
                output = frame[KEY_FIELDS].copy()
                values, diagnostic = quantiles(entry, load_model(entry), frame, baseline_cfg)
                if entry["confirmation_variant"] == "calibration_expanded":
                    values = expand_quantiles(values, entry["calibration"]["expansion"])
                output[["q10", "q50", "q90"]] = values
                if not np.isfinite(values).all() or np.any(values[:, 0] > values[:, 1]) or np.any(values[:, 1] > values[:, 2]):
                    raise ValueError("추가 검증 분위수의 결측·교차 오류")
                cache[("quantile", entry["name"])] = output
                diagnostics.append({"task": "quantile", "name": entry["name"], "horizon": horizon, **diagnostic})
                for scope, part in primary_slices(output, cfg["primary_links"]):
                    if part.empty:
                        metrics_q.append({"name": entry["name"], "horizon": horizon, "slice": scope, "rows": 0, "status": "no_targets"})
                    else:
                        metrics_q.append({"name": entry["name"], "horizon": horizon, "variant": entry["confirmation_variant"],
                            "slice": scope, "rows": len(part), "status": "evaluated", "comparison_quality_pass": quality,
                            **{key: float(value.mean()) for key, value in interval_losses(part).items()}})
            for entry in [item for item in selected if item["confirmation_task"] != "quantile"]:
                task = entry["confirmation_task"]
                output = frame[KEY_FIELDS].copy()
                if task == "relative_probability":
                    label = frame.label_q20
                    scores = raw_score(load_model(entry), frame)
                elif task == "conditional_probability":
                    label = labelled[conditional_cfg["target_name"]]
                    scores = raw_score(load_model(entry), labelled)
                elif task == "conditional_margin":
                    label = labelled[conditional_cfg["target_name"]]
                    raw = cache[("quantile", "catboost_frozen_quantile")].copy()
                    raw["calendar_q20_threshold"] = labelled.calendar_q20_threshold.to_numpy()
                    all_scores, floor_count = margin_scores(raw, margin_cfg["width_floor_kmh"])
                    scores = all_scores[entry["name"]]
                    diagnostics.append({"task": task, "name": entry["name"], "horizon": horizon, "width_floor_rows": floor_count})
                else:
                    raise ValueError("고정 후보에 없는 추가 평가 과제")
                output["label"] = label.astype(int).to_numpy()
                output["probability"] = calibrated_probability(scores, entry["calibrator"])
                cache[(task, entry["name"])] = output
                entry_cache[(task, entry["name"])] = entry
                metrics_p.extend({**row, "task": task, "comparison_quality_pass": quality}
                                 for row in probability_rows(output, entry, metric_base))
        pairs = [(('relative_probability', 'weekly_delayed'), ('relative_probability', 'calendar_only')),
                 (('relative_probability', 'recent_road_assumption'), ('relative_probability', 'weekly_delayed')),
                 (('conditional_margin', 'scaled_median_gap'), ('conditional_probability', 'recent_road_assumption')),
                 (('conditional_margin', 'median_gap'), ('conditional_probability', 'recent_road_assumption'))]
        for scope in cfg["paired_slices"]:
            def subset(data, scope=scope):
                return data[data.target_start.dt.hour.isin([17, 18, 19])] if scope == "primary_evening_17_19" else data
            for left, right in pairs:
                for rule in cfg["rules"]:
                    values = paired_comparison(subset(cache[left]), subset(cache[right]), entry_cache[left][rule]["threshold"],
                                               entry_cache[right][rule]["threshold"], **cfg["bootstrap"])
                    paired_p.extend({"horizon": horizon, "slice": scope, "left_task": left[0], "left": left[1],
                        "right_task": right[0], "right": right[1], "rule": rule, "comparison_quality_pass": quality, **row} for row in values)
            for name in ["weekly_empirical", "calendar_empirical"]:
                values = paired_intervals(subset(cache[("quantile", "catboost_frozen_quantile")]),
                                          subset(cache[("quantile", name)]), **cfg["bootstrap"])
                paired_q.extend({"horizon": horizon, "slice": scope, "left": "catboost_frozen_quantile", "right": name,
                                 "comparison_quality_pass": quality, **row} for row in values)
        for (task, name), data in cache.items():
            path = RAW / "predictions" / f"h{horizon}_{task}_{name}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            data.to_parquet(path, index=False)
            predictions.append({"horizon": horizon, "task": task, "name": name, "path": str(path.relative_to(CASE)),
                                "sha256": sha256(path), "rows": len(data)})
        print(f"가을·겨울 추가 검증 {horizon}시간 완료: {len(frame):,}개 유효 실제값", flush=True)
    tables = {"probability_metrics": metrics_p, "quantile_metrics": metrics_q, "probability_paired": paired_p,
              "quantile_paired": paired_q, "target_counts": states, "prediction_diagnostics": diagnostics}
    for name, records in tables.items():
        pd.DataFrame(records).to_csv(OUT / f"{name}.csv", index=False)
    write_json(OUT / "evaluation_audit.json", {"completed_at": utcnow(), "configuration": cfg, "inputs": inputs,
        "selection_manifest_sha256": sha256(MANIFEST), "comparison_quality_pass": quality, "predictions": predictions,
        "outputs": {name + ".csv": sha256(OUT / (name + ".csv")) for name in tables},
        "interpretation": "가을·겨울 미열람 기간의 고정 후보 추가 검증. 이전 시험 점수와 합치거나 기존 기준을 바꾸지 않음."})
