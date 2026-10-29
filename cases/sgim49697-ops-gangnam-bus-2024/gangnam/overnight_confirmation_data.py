"""미열람 가을·겨울 추가 검증의 후보를 동결하고 별도 원본·특징을 준비한다."""

import json
import shutil
import subprocess
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

import pandas as pd

from .common import CASE, digest, read_yaml, sha256, utcnow, write_json
from .overnight_forecast_features import build_frame, mask_changed_metadata
from .topis import download, list_months, parse_month, session

RAW = CASE / "data/overnight/confirmation"
OUT = CASE / "results/overnight/confirmation"
MANIFEST = OUT / "selection_manifest.json"
SOURCES = CASE / "overnight-confirmation-sources.json"
CONFIG = "overnight_confirmation_config.yaml"


def check_scope(cfg):
    months = [str(month) for month in pd.period_range(cfg["period"][0][:7], cfg["period"][1][:7], freq="M")]
    if (cfg["locked_year"] != 2026 or months != ["2025-09", "2025-10", "2025-11", "2025-12"]
            or cfg["months"] != months or cfg["period"] != ["2025-09-01", "2025-12-31"]
            or cfg["warmup_month"] != "2025-08"):
        raise ValueError("추가 검증의 고정 기간·준비 월·잠금 연도 오류")
    return months


def read_json(name):
    return json.loads((CASE / name).read_text())


def freeze():
    from .overnight_conditional_margin import verify as verify_previous

    cfg = read_yaml(CONFIG)
    check_scope(cfg)
    verify_previous()
    if MANIFEST.exists():
        verify(committed=False)
        return
    if list((RAW / "raw").glob("*.xlsx")):
        raise ValueError("추가 검증 원본을 본 뒤 첫 동결을 만들 수 없습니다")
    specs = {"relative_probability": "results/overnight/relative_ablation/development_manifest.json",
             "conditional_probability": "results/overnight/conditional_low/development_manifest.json",
             "conditional_margin": "results/overnight/conditional_margin/preparation_manifest.json",
             "quantile": "results/overnight/forecast_baselines/supplement_manifest.json"}
    entries = []
    for task, name in specs.items():
        wanted = cfg[task] if task != "quantile" else [item["name"] for item in cfg["quantiles"]]
        source = read_json(name)
        for horizon in cfg["horizons"]:
            for candidate in wanted:
                matched = [entry for entry in source["entries"] if entry["name"] == candidate and entry["horizon"] == horizon]
                if len(matched) != 1:
                    raise ValueError("추가 검증 후보가 기존 동결에서 유일하지 않습니다")
                entry = {**matched[0], "confirmation_task": task, "source_manifest": name}
                if task == "quantile":
                    entry["confirmation_variant"] = next(item["variant"] for item in cfg["quantiles"] if item["name"] == candidate)
                entries.append(entry)
    paths = [CONFIG, "data_contract.yaml", "overnight_forecast_config.yaml", "overnight_forecast_baselines_config.yaml",
             "overnight_conditional_low_config.yaml", "overnight_conditional_margin_config.yaml", *specs.values(),
             "results/overnight/forecast/selected_links.json", "results/overnight/forecast/extraction_test.json",
             "results/overnight/conditional_low/training_thresholds.csv", "gangnam/overnight_confirmation_data.py",
             "gangnam/overnight_confirmation.py", "gangnam/topis.py", "gangnam/overnight_forecast_features.py",
             "gangnam/overnight_baseline_runner.py", "gangnam/overnight_baseline_evaluate.py",
             "gangnam/overnight_baseline_methods.py", "gangnam/overnight_forecast_models.py",
             "gangnam/overnight_forecast_diagnostics.py", "gangnam/overnight_forecast_metrics.py",
             "gangnam/overnight_conditional_target.py", "gangnam/overnight_conditional_margin.py"]
    write_json(MANIFEST, {"frozen_at": utcnow(), "configuration": cfg, "entries": entries,
                         "inputs": {path: sha256(CASE / path) for path in paths},
                         "scope": "2025년 5~8월 탐색 후 정한 미열람 9~12월 추가 확인; 재학습·보정 없음"})
    print(f"가을·겨울 추가 검증 후보 {len(entries)}개 동결. 커밋 후에만 수집할 수 있습니다.", flush=True)


def verify(committed=True):
    cfg = read_yaml(CONFIG)
    check_scope(cfg)
    record = json.loads(MANIFEST.read_text())
    if record["configuration"] != cfg:
        raise ValueError("추가 검증 동결 설정 변경")
    for name, expected in record["inputs"].items():
        path = (CASE / name).resolve()
        if not path.is_relative_to(CASE.resolve()) or sha256(path) != expected:
            raise ValueError(f"추가 검증 동결 입력 변경: {name}")
    for entry in record["entries"]:
        if "model_path" in entry:
            path = (CASE / entry["model_path"]).resolve()
            if not path.is_relative_to((CASE / "data").resolve()) or sha256(path) != entry["model_sha256"]:
                raise ValueError("추가 검증 모델 변경")
    if committed:
        relative = str(MANIFEST.relative_to(CASE.parents[1]))
        saved = subprocess.run(["git", "show", "HEAD:" + relative], cwd=CASE, capture_output=True, check=True).stdout
        if saved != MANIFEST.read_bytes():
            raise ValueError("추가 검증 동결 명세를 먼저 커밋해야 합니다")
    return cfg, record


def verify_source(entry):
    path = (CASE / entry["path"]).resolve()
    if (not path.is_relative_to(RAW.resolve()) or path.stat().st_size != entry["bytes"]
            or sha256(path) != entry["sha256"]):
        raise ValueError("추가 검증 원본 경로·크기·해시 불일치")
    return path


def fetch(job):
    month, spec = job
    if month not in {"2025-09", "2025-10", "2025-11", "2025-12"} or shutil.disk_usage(CASE).free < 25 * 1024**3:
        raise ValueError("추가 검증 수집 기간·디스크 조건 오류")
    with session() as client:
        path, entry = download(client, spec, month, RAW / "raw")
    return {**entry, "path": str(path.relative_to(CASE)), "kind": "road_speed"}


def collect():
    cfg, _ = verify()
    entries = {entry["month"]: entry for entry in read_json(SOURCES.name)["files"]} if SOURCES.exists() else {}
    for path in (RAW / "raw").glob("*.source.json"):
        entry = json.loads(path.read_text())
        if entry["month"] in cfg["months"]:
            entries.setdefault(entry["month"], {**entry, "path": str(path.with_suffix("").with_suffix(".xlsx").relative_to(CASE)), "kind": "road_speed"})
    if set(entries) - set(cfg["months"]):
        raise ValueError("추가 검증 출처에 범위 밖 월이 있습니다")
    for entry in entries.values():
        verify_source(entry)
    with session() as client:
        catalog = list_months(client, 2025)
    jobs = [(month, catalog[int(month[-2:])]) for month in cfg["months"] if month not in entries]
    with ThreadPoolExecutor(max_workers=cfg["resources"]["download_workers"]) as pool:
        for entry in pool.map(fetch, jobs):
            entries[entry["month"]] = entry
            write_json(SOURCES, {"selection_manifest_sha256": sha256(MANIFEST), "files": sorted(entries.values(), key=lambda item: item["month"])})
            print(f"추가 검증 원본: {entry['month']} {entry['bytes']:,} bytes", flush=True)
    if not SOURCES.exists():
        write_json(SOURCES, {"selection_manifest_sha256": sha256(MANIFEST), "files": sorted(entries.values(), key=lambda item: item["month"])})


def parse_entry(job):
    entry, roads, rules = job
    source = verify_source(entry)
    path = RAW / "processed" / (entry["month"] + ".parquet")
    signature = digest({"roads": roads, "rules": rules})
    if path.exists():
        info = json.loads(path.with_suffix(".json").read_text())
        if info["sha256"] != sha256(path) or info["source_sha256"] != entry["sha256"] or info["signature"] != signature:
            raise ValueError("추가 검증 가공 캐시 변경")
        return info
    frame, metadata = parse_month(source, entry["month"], roads, rules)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.parquet")
    frame.to_parquet(temporary, index=False)
    temporary.replace(path)
    info = {**metadata, "path": str(path.relative_to(CASE)), "sha256": sha256(path), "signature": signature,
            "source_sha256": entry["sha256"], "rows": len(frame)}
    write_json(path.with_suffix(".json"), info)
    print(f"추가 검증 추출: {entry['month']} {len(frame):,}행", flush=True)
    return info


def prepare():
    cfg, _ = verify()
    sources = read_json(SOURCES.name)
    if sources["selection_manifest_sha256"] != sha256(MANIFEST) or {entry["month"] for entry in sources["files"]} != set(cfg["months"]):
        raise ValueError("추가 검증 원본 명세·기간 오류")
    base = read_yaml("overnight_forecast_config.yaml")
    if cfg["primary_links"] != base["primary_links"] or cfg["horizons"] != base["horizons"]:
        raise ValueError("기존 핵심 링크·간격과 다른 추가 검증")
    rules = read_yaml("data_contract.yaml")["checks"]["missing_values"]["value"]
    with ProcessPoolExecutor(max_workers=cfg["resources"]["parse_workers"]) as pool:
        entries = list(pool.map(parse_entry, [(entry, cfg["roads"], rules) for entry in sources["files"]]))
    old = read_json("results/overnight/forecast/extraction_test.json")
    warmup = [entry for entry in old if entry["month"] == cfg["warmup_month"]]
    if len(warmup) != 1:
        raise ValueError("8월 준비 캐시가 유일하지 않습니다")
    all_entries = warmup + entries
    parts = []
    for entry in all_entries:
        path = (CASE / entry["path"]).resolve()
        if not path.is_relative_to((CASE / "data").resolve()) or sha256(path) != entry["sha256"]:
            raise ValueError("추가 검증 특징의 가공 입력 변경")
        frame = pd.read_parquet(path)
        if frame.interval_start_kst.dt.year.ge(2026).any() or not frame.interval_start_kst.dt.strftime("%Y-%m").eq(entry["month"]).all():
            raise ValueError("추가 검증 특징의 날짜·잠금 오류")
        if ((frame.speed_kmh.notna()) & ~frame.is_valid).any():
            raise ValueError("추가 검증 무효 속도에 값이 남았습니다")
        parts.append(frame[frame.link_id.isin(cfg["primary_links"])][["link_id", "interval_start_kst", "speed_kmh"]])
    joined = pd.concat(parts, ignore_index=True)
    if joined.duplicated(["link_id", "interval_start_kst"]).any():
        raise ValueError("추가 검증 시각·링크 중복")
    index = pd.date_range(cfg["warmup_month"] + "-01", cfg["period"][1] + " 23:00", freq="h", tz=base["timezone"])
    matrix = joined.pivot(index="interval_start_kst", columns="link_id", values="speed_kmh").reindex(index)
    chosen = {key: value for key, value in read_json("results/overnight/forecast/selected_links.json").items() if key in cfg["primary_links"]}
    matrix, exclusions = mask_changed_metadata(matrix, all_entries, chosen, base)
    outputs, coverages = [], []
    for horizon in cfg["horizons"]:
        frame = build_frame(matrix, chosen, horizon, base)
        frame = frame[frame.target_start.dt.strftime("%Y-%m-%d").between(*cfg["period"])].copy()
        frame["split"] = "confirmation"
        path = RAW / f"features_h{horizon}.parquet"
        frame.to_parquet(path, index=False)
        outputs.append({"horizon": horizon, "path": str(path.relative_to(CASE)), "sha256": sha256(path), "rows": len(frame)})
        coverage = frame.assign(month=frame.target_start.dt.strftime("%Y-%m")).groupby(["month", "link_id"]).speed_kmh.agg(["count", "size"]).reset_index()
        coverage["observed_fraction"] = coverage["count"] / coverage["size"]
        coverage["quality_pass"] = coverage.observed_fraction.ge(cfg["minimum_link_month_observed_fraction"])
        coverages.append(coverage.assign(horizon=horizon))
    pd.concat(coverages, ignore_index=True).to_csv(OUT / "coverage.csv", index=False)
    write_json(OUT / "feature_audit.json", {"prepared_at": utcnow(), "selection_manifest_sha256": sha256(MANIFEST),
        "source_manifest_sha256": sha256(SOURCES), "metadata_exclusions": exclusions, "outputs": outputs,
        "coverage_sha256": sha256(OUT / "coverage.csv"), "inputs": [{"path": entry["path"], "sha256": entry["sha256"]} for entry in all_entries],
        "extractions": entries, "warmup_month": cfg["warmup_month"], "period": cfg["period"]})
    print("가을·겨울 특징 준비 완료. 원래 모델·시험 설정은 변경하지 않았습니다.", flush=True)
