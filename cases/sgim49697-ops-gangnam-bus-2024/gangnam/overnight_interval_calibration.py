"""기존 분위수 모델의 고정·순차 구간 보정을 준비 명세와 분리된 사후 평가로 실행한다."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .overnight_baseline_evaluate import primary_slices
from .overnight_baseline_methods import interval_losses, paired_intervals
from .overnight_baseline_runner import (
    KEY_FIELDS,
    load_model,
    quantiles,
    read_features,
    verify_manifest,
)
from .overnight_forecast_diagnostics import align_predictions
from .overnight_interval_methods import VALUES, adjust, expansion, scores

OUT = CASE / "results/overnight/interval_calibration"
RAW = CASE / "data/overnight/interval_calibration"
MANIFEST = OUT / "preparation_manifest.json"


def configuration():
    cfg = read_yaml("overnight_interval_calibration_config.yaml")
    _, base, original = verify_manifest()
    if cfg["horizons"] != base["horizons"] or cfg["locked_year"] != 2026:
        raise ValueError("보정 비교의 간격·잠금 연도가 다릅니다")
    if cfg["evaluation"] != base["splits"]["test"] or cfg["evaluation"][1] >= "2026-01-01":
        raise ValueError("보정 평가가 원래 시험 범위 밖입니다")
    if cfg["static_calibration"] != base["splits"]["calibration"]:
        raise ValueError("고정 보정 기간이 원래 3월과 다릅니다")
    if cfg["rolling_warmup"][1] >= cfg["evaluation"][0] or len({item["name"] for item in cfg["variants"]}) != len(cfg["variants"]):
        raise ValueError("보정 준비·평가 기간 중첩 또는 방식 이름 중복")
    return cfg, base, original


def read_prediction(info):
    path = CASE / info["path"]
    if not path.resolve().is_relative_to((CASE / "data").resolve()) or sha256(path) != info["sha256"]:
        raise ValueError("구간 보정 예측 입력의 경로·해시 불일치")
    result = pd.read_parquet(path)
    if len(result) != info["rows"]:
        raise ValueError("구간 보정 예측 입력의 행 수 불일치")
    scores(result)
    return result


def prepare():
    cfg, base, original = configuration()
    if MANIFEST.exists():
        verify()
        print("기존 구간 보정 준비 명세 검증 완료", flush=True)
        return
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    inputs, entries, static_rows = {}, [], []
    for horizon in cfg["horizons"]:
        entry = next(item for item in original["entries"] if item["name"] == cfg["model"] and item["horizon"] == horizon)
        full, _, references = read_features("development", horizon, base)
        inputs.update(references)
        dates = full.target_start.dt.strftime("%Y-%m-%d")
        frame = full[full.link_id.isin(base["primary_links"]) & full.speed_kmh.notna()
                     & dates.between(*cfg["rolling_warmup"])].copy()
        if not set(frame.split).issubset({"calibration", "decision"}) or set(frame.link_id) != set(base["primary_links"]):
            raise ValueError("보정 준비의 분할 또는 핵심 링크 범위 불일치")
        model = load_model(entry)
        values, _ = quantiles(entry, model, frame, {})
        warmup = frame[KEY_FIELDS].copy()
        warmup[["q10", "q50", "q90"]] = values
        scores(warmup)
        static = warmup[warmup.target_start.dt.strftime("%Y-%m-%d").between(*cfg["static_calibration"])].copy()
        cached = read_prediction(entry["calibration_predictions"])
        paired = align_predictions(static.assign(label=0), cached.assign(label=0))
        for name in VALUES:
            np.testing.assert_array_equal(paired[name + "_left"].to_numpy(), paired[name + "_right"].to_numpy())
        target = RAW / f"h{horizon}_warmup.parquet"
        if target.exists():
            raise ValueError("명세 없는 구간 준비 캐시를 덮어쓰지 않습니다")
        warmup.to_parquet(target, index=False)
        entries.append({"horizon": horizon, "candidate": entry["candidate"], "model_path": entry["model_path"],
                        "model_sha256": entry["model_sha256"], "warmup": {"path": str(target.relative_to(CASE)),
                        "sha256": sha256(target), "rows": len(warmup)}, "static_rows": len(static)})
        static["evening"] = static.target_start.dt.hour.isin([17, 18, 19])
        for link, band, part in [("all", "all", static), *[(link, str(band), part) for (link, band), part in static.groupby(["link_id", "evening"])]]:
            static_rows.append({"horizon": horizon, "link_id": link, "evening": band, "scores": len(part),
                                "expansion": expansion(scores(part), cfg["target_coverage"]),
                                "group_minimum_pass": bool(len(part) >= cfg["minimum_group_scores"])})
        print(f"구간 보정 준비: h{horizon}, 3~4월 {len(warmup):,}행, 기존 3월 예측 정확 일치", flush=True)
    paths = ["overnight_interval_calibration_config.yaml", "gangnam/overnight_interval_methods.py",
             "gangnam/overnight_interval_calibration.py", "gangnam/overnight_baseline_evaluate.py",
             "gangnam/overnight_baseline_methods.py", "gangnam/overnight_baseline_runner.py",
             "gangnam/overnight_forecast_diagnostics.py", cfg["base_manifest"]]
    inputs.update({path: sha256(CASE / path) for path in paths})
    pd.DataFrame(static_rows).to_csv(OUT / "static_calibration.csv", index=False)
    write_json(MANIFEST, {"prepared_at": utcnow(), "configuration": cfg, "entries": entries, "inputs": inputs,
                         "outputs": {"static_calibration.csv": sha256(OUT / "static_calibration.csv")},
                         "interpretation": "사후 탐색. 준비 코드·3~4월 예측을 저장한 뒤 기존 시험의 순차 공개를 재생하며 원래 모델은 변경하지 않음."})


def verify():
    cfg, base, _ = configuration()
    manifest = json.loads(MANIFEST.read_text())
    for name, expected in manifest["inputs"].items():
        if sha256(CASE / name) != expected:
            raise ValueError(f"구간 보정 준비 입력 해시 변경: {name}")
    for entry in manifest["entries"]:
        for item in [entry["warmup"], {"path": entry["model_path"], "sha256": entry["model_sha256"]}]:
            path = CASE / item["path"]
            if not path.resolve().is_relative_to((CASE / "data").resolve()) or sha256(path) != item["sha256"]:
                raise ValueError("구간 보정 준비 예측·모델 해시 변경")
    for name, expected in manifest["outputs"].items():
        if sha256(OUT / name) != expected:
            raise ValueError("구간 보정 준비 표 해시 변경")
    return cfg, base, manifest


def slices(frame, links):
    yield from primary_slices(frame, links)
    for link in links:
        yield "evening_link_" + link, frame[frame.link_id.eq(link) & frame.target_start.dt.hour.isin([17, 18, 19])]


def evaluate():
    cfg, base, manifest = verify()
    original_audit_path = CASE / "results/overnight/forecast_baselines/evaluation_audit.json"
    original = json.loads(original_audit_path.read_text())
    metrics, paired, daily_rows, diagnostics, predictions = [], [], [], [], []
    inputs = {str(original_audit_path.relative_to(CASE)): sha256(original_audit_path)}
    for entry in manifest["entries"]:
        horizon = entry["horizon"]
        info = next(item for item in original["predictions"] if item["name"] == cfg["model"]
                    and item["horizon"] == horizon and item["variant"] == "raw")
        test = read_prediction(info)
        inputs[info["path"]] = info["sha256"]
        if not test.target_start.dt.strftime("%Y-%m-%d").between(*cfg["evaluation"]).all():
            raise ValueError("구간 시험 예측에 다른 날짜 또는 잠금 연도가 있습니다")
        if set(test.link_id) != set(base["primary_links"]):
            raise ValueError("구간 시험 예측의 핵심 링크 범위 불일치")
        if not (test.target_start - test.origin).eq(pd.Timedelta(hours=horizon - 1)).all():
            raise ValueError("구간 시험 예측의 원점·목표 시각 간격 오류")
        warmup = read_prediction(entry["warmup"])
        static = warmup[warmup.target_start.dt.strftime("%Y-%m-%d").between(*cfg["static_calibration"])].copy()
        cache = {}
        for variant in cfg["variants"]:
            output = adjust(test, static, warmup, cfg, variant)
            name = variant["name"]
            cache[name] = output
            for scope, part in slices(output, base["primary_links"]):
                losses = interval_losses(part)
                metrics.append({"horizon": horizon, "variant": name, "slice": scope, "rows": len(part),
                                **{key: float(value.mean()) for key, value in losses.items()},
                                "mean_expansion": float(part.expansion.mean()), "maximum_expansion": float(part.expansion.max()),
                                "negative_lower_rows": int(part.q10.lt(0).sum())})
            loss_frame = pd.DataFrame(interval_losses(output), index=output.index)
            loss_frame["date"] = output.target_start.dt.strftime("%Y-%m-%d")
            loss_frame["evening"] = output.target_start.dt.hour.isin([17, 18, 19])
            loss_frame["expansion"] = output.expansion
            for evening in [False, True]:
                part = loss_frame[loss_frame.evening] if evening else loss_frame
                grouped = part.groupby("date").agg(**{key: (key, "mean") for key in interval_losses(output)},
                                                   mean_expansion=("expansion", "mean"), rows=("coverage", "size")).reset_index()
                daily_rows.append(grouped.assign(horizon=horizon, variant=name, evening_only=evening))
            available = output.latest_label_available_at.dropna()
            diagnostics.append({"horizon": horizon, "variant": name, "delay_hours": variant["delay_hours"],
                                "future_label_violations": int((output.latest_label_available_at > output.origin).sum()),
                                "source_counts": {key: int(value) for key, value in output.calibration_source.value_counts().items()},
                                "minimum_scores": int(output.calibration_scores.min()), "maximum_scores": int(output.calibration_scores.max()),
                                "minimum_expansion": float(output.expansion.min()), "maximum_expansion": float(output.expansion.max()),
                                "latest_used_label_release": str(available.max()) if len(available) else None})
            path = RAW / f"h{horizon}_{name}_test.parquet"
            output.to_parquet(path, index=False)
            predictions.append({"horizon": horizon, "variant": name, "path": str(path.relative_to(CASE)), "sha256": sha256(path), "rows": len(output)})
        pairs = [(item["name"], "raw") for item in cfg["variants"] if item["name"] != "raw"]
        pairs += [("static_link_band", "static_global"), *[(f"rolling_link_band_d{delay}", f"rolling_global_d{delay}")
                                                         for delay in cfg["label_delay_assumptions_hours"]]]
        for left, right in pairs:
            for evening in [False, True]:
                a, b = cache[left], cache[right]
                if evening:
                    a, b = [part[part.target_start.dt.hour.isin([17, 18, 19])] for part in [a, b]]
                rows = paired_intervals(a, b, cfg["bootstrap"]["draws"], cfg["bootstrap"]["seed"])
                paired.extend({"horizon": horizon, "slice": "evening" if evening else "all", "left": left, "right": right, **row} for row in rows)
        print(f"구간 보정 순차 평가: h{horizon}, {len(cache)}개 방식 × {len(test):,}행", flush=True)
    outputs = {"metrics.csv": pd.DataFrame(metrics), "paired_comparisons.csv": pd.DataFrame(paired),
               "daily_metrics.csv": pd.concat(daily_rows, ignore_index=True)}
    for name, frame in outputs.items():
        frame.to_csv(OUT / name, index=False)
    write_json(OUT / "evaluation_audit.json", {"completed_at": utcnow(), "preparation_manifest_sha256": sha256(MANIFEST),
               "code_sha256": sha256(Path(__file__)), "inputs": inputs, "diagnostics": diagnostics, "predictions": predictions,
               "outputs": {name: sha256(OUT / name) for name in outputs}, "interpretation": cfg["interpretation"]})
