"""새 예측의 개발 기간만 먼저 수집하고 시험 자료는 모델 동결 뒤에만 허용한다."""

from __future__ import annotations

import json
import shutil
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from .common import CASE, digest, read_yaml, sha256, write_json
from .topis import download, list_months, parse_month, session

BASE = CASE / "data/overnight/forecast"
OUT = CASE / "results/overnight/forecast"
MANIFEST = CASE / "overnight-forecast-sources.json"


def allowed_months(scope, cfg):
    if scope not in {"development", "test"}:
        raise ValueError("예측 자료 범위는 development 또는 test입니다")
    if scope == "test":
        frozen = OUT / "selection_manifest.json"
        if not frozen.exists():
            raise ValueError("모델·보정기·경보 기준 동결 전에는 시험 파일을 수집·파싱할 수 없습니다")
        manifest = json.loads(frozen.read_text())
        if manifest.get("protocol_sha256") != sha256(CASE / "overnight_forecast_config.yaml"):
            raise ValueError("동결 뒤 예측 규약이 변경되었습니다")
        if not manifest.get("selection_complete"):
            raise ValueError("선택 완료 표식이 없습니다")
        for item in manifest.get("frozen_files", []):
            path = CASE / item["path"]
            if not path.resolve().is_relative_to(CASE.resolve()) or sha256(path) != item["sha256"]:
                raise ValueError("동결된 모델·설정 파일의 경로 또는 해시가 다릅니다")
        if not manifest.get("frozen_files"):
            raise ValueError("동결할 파일 목록이 비어 있습니다")
        start, end = cfg["splits"]["test"]
    else:
        start, end = cfg["splits"]["train"][0], cfg["splits"]["decision"][1]
    months = [str(p) for p in pd.period_range(start[:7], end[:7], freq="M")]
    if any(int(m[:4]) >= cfg["locked_year"] for m in months):
        raise ValueError("2026년 이후 잠금 연도 접근 금지")
    return months


def verify(entry):
    path = CASE / entry["path"]
    if not path.resolve().is_relative_to((CASE / "data").resolve()):
        raise ValueError("예측 원본 경로가 data 밖입니다")
    if path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
        raise ValueError("예측 원본 해시·크기 불일치")
    return path


def fetch(job):
    month, spec = job
    if shutil.disk_usage(CASE).free < 25 * 1024**3:
        raise ValueError("남은 디스크가 25 GiB보다 적어 수집을 중단합니다")
    with session() as client:
        path, entry = download(client, spec, month, BASE / "roads/raw")
    return {**entry, "path": str(path.relative_to(CASE)), "kind": "road_speed"}


def collect(scope="development"):
    cfg = read_yaml("overnight_forecast_config.yaml")
    months = allowed_months(scope, cfg)
    BASE.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    previous = json.loads(MANIFEST.read_text())["files"] if MANIFEST.exists() else []
    entries = {x["month"]: x for x in previous}
    for month in months:
        old = CASE / f"data/raw/{month}.xlsx"
        if month not in entries and old.exists() and old.with_suffix(".source.json").exists():
            entry = json.loads(old.with_suffix(".source.json").read_text())
            entries[month] = {**entry, "path": str(old.relative_to(CASE)), "kind": "road_speed", "reuse": "original_source"}
    for path in (BASE / "roads/raw").glob("*.source.json"):
        entry = json.loads(path.read_text())
        month = entry["month"]
        if month in months:
            entries.setdefault(month, {**entry, "path": str(path.with_suffix("").with_suffix(".xlsx").relative_to(CASE)), "kind": "road_speed"})
    for month in months:
        if month in entries:
            verify(entries[month])
    jobs = []
    with session() as client:
        catalog = {}
        for month in months:
            if month in entries:
                continue
            year, number = map(int, month.split("-"))
            if year not in catalog:
                catalog[year] = list_months(client, year)
            if number not in catalog[year]:
                raise ValueError(f"TOPIS 목록에 필요한 월이 없습니다: {month}")
            jobs.append((month, catalog[year][number]))
    def save():
        write_json(MANIFEST, {"description": "2025 저속 경보용 TOPIS 원본. 개발 기간 우선 수집, 시험은 모델 동결 뒤 접근.",
                              "files": sorted(entries.values(), key=lambda x: x["month"])})
    save()
    with ThreadPoolExecutor(max_workers=2) as pool:
        for entry in pool.map(fetch, jobs):
            entries[entry["month"]] = entry
            save()
            print(f"예측 원본 확보: {entry['month']} {entry['bytes']:,} bytes", flush=True)
    print(f"{scope}: {len(months)}개월 원본 확인", flush=True)


def prepare_entry(job):
    entry, roads, rules = job
    month = entry["month"]
    target = BASE / f"roads/processed/{month}.parquet"
    meta_path = target.with_suffix(".json")
    signature = digest({"roads": roads, "rules": rules})
    if target.exists():
        if not meta_path.exists():
            raise ValueError("출처 없는 예측 가공 캐시")
        meta = json.loads(meta_path.read_text())
        if (sha256(target) != meta["sha256"] or meta["source_sha256"] != entry["sha256"]
                or meta["data_rules_hash"] != signature):
            raise ValueError("예측 가공 캐시·원본·설정 불일치")
        if meta.get("reused") and not set(roads).issubset(read_yaml("corridors.yaml")["candidate_roads"]):
            raise ValueError("재사용 캐시에 요청 도로 일부가 없습니다. 기존 가공물을 격리한 뒤 원본에서 다시 추출하세요")
        return meta
    source = verify(entry)
    old = CASE / f"data/processed/{month}.parquet"
    old_info = old.with_suffix(".json")
    old_meta = CASE / f"data/metadata/{month}.json"
    reused = None
    old_cfg = read_yaml("corridors.yaml")
    if (old.exists() and old_info.exists() and old_meta.exists()
            and set(roads).issubset(old_cfg["candidate_roads"])):
        info = json.loads(old_info.read_text())
        if (sha256(old) != info["parquet_sha256"] or info["source_sha256"] != entry["sha256"]
                or info["contract_hash"] != digest(read_yaml("data_contract.yaml"))
                or info["road_selection_hash"] != digest(old_cfg["candidate_roads"])):
            raise ValueError("기존 속도 가공 캐시가 당시 규약과 다릅니다")
        meta = json.loads(old_meta.read_text())
        if meta["source_sha256"] != entry["sha256"]:
            raise ValueError("기존 속도 메타데이터 출처가 다릅니다")
        meta = {**meta, "metadata": [x for x in meta["metadata"] if x["도로명"] in roads]}
        ids = {x["링크아이디"] for x in meta["metadata"]}
        frame = pd.read_parquet(old)
        frame = frame[frame.link_id.isin(ids)].copy()
        reused = {"path": str(old.relative_to(CASE)), "sha256": info["parquet_sha256"],
                  "prior_metadata_exclusions": read_yaml("data_contract.yaml").get("metadata_policy", {}).get("excluded_links", [])}
    else:
        frame, meta = parse_month(source, month, roads, rules)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".parquet.tmp")
    frame.to_parquet(temp, index=False)
    temp.replace(target)
    info = {**meta, "rows": len(frame), "path": str(target.relative_to(CASE)), "source_sha256": entry["sha256"],
            "sha256": sha256(target), "data_rules_hash": signature, "reused": reused, "parser_sha256": sha256(Path(__file__))}
    write_json(meta_path, info)
    print(f"예측 속도 준비: {month} {len(frame):,}행", flush=True)
    return info


def prepare(scope="development"):
    cfg = read_yaml("overnight_forecast_config.yaml")
    months = allowed_months(scope, cfg)
    entries = {x["month"]: x for x in json.loads(MANIFEST.read_text())["files"]}
    if not set(months).issubset(entries):
        raise ValueError("예측 월 원본 수집이 끝나지 않았습니다")
    rules = read_yaml("data_contract.yaml")["checks"]["missing_values"]["value"]
    jobs = [(entries[m], cfg["roads"], rules) for m in months]
    with ProcessPoolExecutor(max_workers=2) as pool:
        prepared = list(pool.map(prepare_entry, jobs))
    write_json(OUT / f"extraction_{scope}.json", prepared)
    print(f"{scope} 속도 추출 {len(prepared)}개월 완료", flush=True)
