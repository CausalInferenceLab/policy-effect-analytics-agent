"""이미 관측한 고정 시험에서 기준 모델·경보 예산·구간 보정의 사후 비교를 별도로 저장한다."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, sha256, utcnow, write_json
from .overnight_baseline_methods import expand_quantiles, interval_losses, paired_intervals
from .overnight_baseline_runner import (
    KEY_FIELDS,
    OLD,
    OUT,
    RAW,
    load_model,
    quantiles,
    read_features,
    verify_manifest,
)
from .overnight_forecast_diagnostics import align_predictions, paired_comparison
from .overnight_forecast_metrics import weighted_probability_metrics
from .overnight_forecast_models import calibrated_probability, probability_metrics, raw_score


def primary_slices(frame, primary):
    yield "primary_all_hours", frame
    yield "primary_evening_17_19", frame[frame.target_start.dt.hour.isin([17, 18, 19])]
    for link in primary:
        yield "link_" + link, frame[frame.link_id.eq(link)]
    for month, part in frame.groupby(frame.target_start.dt.strftime("%Y-%m")):
        yield "month_" + month, part


def frozen_predictions(entry, base):
    audit = json.loads((OLD / "test_evaluation_audit.json").read_text())
    info = next(x for x in audit["predictions"] if x["candidate"] == entry["candidate"])
    path = CASE / info["path"]
    if not path.resolve().is_relative_to((CASE / "data/overnight/forecast/test_predictions").resolve()) or sha256(path) != info["sha256"]:
        raise ValueError("기존 동결 예측 파일의 경로·해시 불일치")
    frame = pd.read_parquet(path)
    frame = frame.drop(columns="alert", errors="ignore")
    return frame[frame.link_id.isin(base["primary_links"])].copy(), info


def prediction(entry, frame, cfg, base):
    references = {}
    if entry["frozen_comparator"]:
        result, info = frozen_predictions(entry, base)
        references[info["path"]] = info["sha256"]
        diagnostics = {"source": "existing_frozen_predictions", "fallback_rows": 0}
    else:
        model = load_model(entry)
        result = frame[KEY_FIELDS].copy()
        if entry["task"] == "relative_probability":
            raw = raw_score(model, frame)
            result["label"] = frame.label_q20.astype(int)
            result["raw_probability"] = calibrated_probability(raw)
            result["probability"] = calibrated_probability(raw, entry["calibrator"])
            diagnostics = {"source": "new_training_only_baseline", "fallback_rows": 0}
        else:
            values, diagnostics = quantiles(entry, model, frame, cfg)
            result[["q10", "q50", "q90"]] = values
    expected = frame[KEY_FIELDS].copy()
    if entry["task"] == "relative_probability":
        expected["label"] = frame.label_q20.astype(int)
        align_predictions(result, expected)
    else:
        align_predictions(result.assign(label=0), expected.assign(label=0))
    return result, references, diagnostics


def calendar_days(slice_name, base):
    if slice_name.startswith("month_"):
        return pd.Period(slice_name.removeprefix("month_")).days_in_month
    return len(pd.date_range(*base["splits"]["test"]))


def probability_rows(frame, entry, base):
    rows = []
    for name, group in primary_slices(frame, base["primary_links"]):
        if group.empty:
            rows.append({"name": entry["name"], "horizon": entry["horizon"], "slice": name, "status": "no_targets", "rows": 0})
            continue
        point = probability_metrics(group.label, group.probability)
        for rule in ["original_rule", "budget_rule"]:
            threshold = entry[rule]["threshold"]
            days = calendar_days(name, base)
            measured = weighted_probability_metrics(group.label, group.probability, np.ones(len(group)), threshold, days)
            alerts = group.probability.ge(threshold)
            rows.append({"name": entry["name"], "horizon": entry["horizon"], "slice": name, "rule": rule, "status": "evaluated",
                         **point, **{k: float(v[0]) for k, v in measured.items()}, "threshold": threshold,
                         "alerts": int(alerts.sum()), "true_alerts": int((alerts & group.label.eq(1)).sum()),
                         "false_alerts": int((alerts & group.label.eq(0)).sum()), "calendar_days": days})
    return rows


def evaluate():
    from threadpoolctl import threadpool_limits

    cfg, base, manifest = verify_manifest()
    inputs, saved, metrics_p, metrics_q, differences_p, differences_q, diagnostics = {}, [], [], [], [], [], []
    predictions = RAW / "test_predictions"
    predictions.mkdir(parents=True, exist_ok=True)
    for horizon in base["horizons"]:
        full, _, references = read_features("test", horizon, base)
        inputs.update(references)
        frame = full[full.speed_kmh.notna() & full.link_id.isin(base["primary_links"])].copy()
        if frame.empty:
            raise ValueError("기준 비교 시험의 핵심 링크 표본이 없습니다")
        cache = {}
        selected = [e for e in manifest["entries"] if e["horizon"] == horizon]
        for entry in selected:
            with threadpool_limits(limits=cfg["resources"]["cpu_threads"]):
                output, references, diagnostic = prediction(entry, frame, cfg, base)
            inputs.update(references)
            diagnostics.append({"name": entry["name"], "horizon": horizon, **diagnostic})
            if entry["task"] == "relative_probability":
                variants = [("calibrated_probability", output)]
                metrics_p.extend(probability_rows(output, entry, base))
                cache[entry["name"]] = output
            else:
                adjusted = output.copy()
                adjusted[["q10", "q50", "q90"]] = expand_quantiles(output[["q10", "q50", "q90"]].to_numpy(), entry["calibration"]["expansion"])
                variants = [("raw", output), ("calibration_expanded", adjusted)]
                for variant, data in variants:
                    cache[(entry["name"], variant)] = data
                    for name, group in primary_slices(data, base["primary_links"]):
                        if group.empty:
                            metrics_q.append({"name": entry["name"], "horizon": horizon, "variant": variant, "slice": name, "rows": 0, "status": "no_targets"})
                            continue
                        metrics_q.append({"name": entry["name"], "horizon": horizon, "variant": variant, "slice": name,
                                          "rows": len(group), "status": "evaluated", "expansion": entry["calibration"]["expansion"] if variant != "raw" else 0,
                                          **{key: float(values.mean()) for key, values in interval_losses(group).items()}})
            for variant, data in variants:
                path = predictions / f"h{horizon}_{entry['name']}_{variant}.parquet"
                data.to_parquet(path, index=False)
                saved.append({"name": entry["name"], "horizon": horizon, "variant": variant,
                              "path": str(path.relative_to(CASE)), "sha256": sha256(path), "rows": len(data)})
        by_name = {e["name"]: e for e in selected}
        for scope, evening in [("primary_all_hours", False), ("primary_evening_17_19", True)]:
            def subset(data, evening=evening):
                return data[data.target_start.dt.hour.isin([17, 18, 19])] if evening else data
            for spec in cfg["relative_probability"]["models"]:
                name = spec["name"]
                for rule in ["original_rule", "budget_rule"]:
                    rows = paired_comparison(subset(cache["catboost_frozen_q20"]), subset(cache[name]),
                                             by_name["catboost_frozen_q20"][rule]["threshold"], by_name[name][rule]["threshold"])
                    differences_p.extend({"horizon": horizon, "slice": scope, "left": "catboost_frozen_q20", "right": name, "rule": rule, **r} for r in rows)
            for name in ["calendar_empirical", "weekly_empirical"]:
                for variant in ["raw", "calibration_expanded"]:
                    rows = paired_intervals(subset(cache[("catboost_frozen_quantile", variant)]), subset(cache[(name, variant)]))
                    differences_q.extend({"horizon": horizon, "slice": scope, "left": "catboost_frozen_quantile", "right": name, "variant": variant, **r} for r in rows)
            for name in ["calendar_empirical", "weekly_empirical", "catboost_frozen_quantile"]:
                rows = paired_intervals(subset(cache[(name, "calibration_expanded")]), subset(cache[(name, "raw")]))
                differences_q.extend({"horizon": horizon, "slice": scope, "left": name + "_expanded", "right": name + "_raw", "variant": "expansion_difference", **r} for r in rows)
        print(f"사후 기준 비교 평가: h{horizon}, 핵심 시험 {len(frame):,}행", flush=True)
        del full, frame, cache
    for name, rows in [("probability_metrics.csv", metrics_p), ("quantile_metrics.csv", metrics_q),
                       ("probability_paired.csv", differences_p), ("quantile_paired.csv", differences_q)]:
        pd.DataFrame(rows).to_csv(OUT / name, index=False)
    write_json(OUT / "evaluation_audit.json", {"completed_at": utcnow(), "code_sha256": sha256(Path(__file__)),
                                             "supplement_manifest_sha256": sha256(OUT / "supplement_manifest.json"),
                                             "mode": cfg["mode"], "inputs": inputs, "predictions": saved, "diagnostics": diagnostics,
                                             "outputs": {p.name: sha256(p) for p in OUT.glob("*.csv")},
                                             "uncertainty": "핵심 전체·저녁의 동일 주 공동 재표집 1000회, seed 17. 차이는 left-right.",
                                             "scope": "기존에 본 시험값의 사후 기준 모델 비교. 기존 동결 모델·임계값·시험 결과는 보존."})
