"""추가 버스·재차인원 원본에서 고정 정류장 행을 추출하고 월 경계 중복을 보존한다."""

from __future__ import annotations

import csv
import io
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd

from .common import CASE, digest, read_yaml, sha256, write_json
from .followup import RENAME, VALUES, clean_duplicates

BASE = CASE / "data/overnight"
OUT = CASE / "results/overnight"


def schema(kind, hours):
    keys = ["기준_날짜", "노선_ID"]
    if kind == "bus_passengers":
        keys += ["출발_정류장_ID", "도착_정류장_ID", "정류장_순서"]
        columns = ["재차인원합_일", *[f"재차인원합_{h}시" for h in hours]]
        rename = {"재차인원합_일": "daily_total", **{f"재차인원합_{h}시": f"h{h:02}" for h in hours}}
    elif kind in {"bus_time", "bus_trips"}:
        keys += (["출발_정류장_ID", "출발_정류장_순서", "도착_정류장_ID", "도착_정류장_순서"]
                 if kind == "bus_time" else ["정류장_ID", "정류장_순서"])
        columns = [f"{VALUES[kind]}_{h:02}시" for h in hours]
        rename = {c: f"h{h:02}" for c, h in zip(columns, hours, strict=True)}
    else:
        raise ValueError(f"지원하지 않는 추가 버스 종류: {kind}")
    return keys, columns, RENAME | rename


def choose_chunk(chunk, kind, stops, columns):
    if kind == "bus_trips":
        chosen = chunk["정류장_ID"].isin(stops)
    else:
        chosen = chunk["출발_정류장_ID"].isin(stops) | chunk["도착_정류장_ID"].isin(stops)
    frame = chunk.loc[chosen].copy()
    for column in columns:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
        if np.isinf(frame[column]).any():
            raise ValueError("버스 원본에 무한대 값이 있습니다")
    return frame


def extract(job):
    entry, stops, hours, folder = job
    kind, month = entry["kind"], entry["month"]
    if month < "2023-01":
        raise ValueError("2022년 버스 원본은 헤더·행 불일치 검증 전까지 별도 보류합니다")
    if month >= "2025-05":
        raise ValueError("개발용 버스 추출은 2025년 4월까지 허용합니다")
    path = CASE / entry["path"]
    if not path.resolve().is_relative_to((CASE / "data").resolve()) or sha256(path) != entry["sha256"]:
        raise ValueError("버스 원본 경로·해시 불일치")
    target = BASE / folder / "processed" / f"{kind}_{month}.parquet"
    info_path = target.with_suffix(".json")
    stops_hash = digest(sorted(stops))
    if target.exists():
        info = json.loads(info_path.read_text())
        if (info["raw_sha256"] != entry["sha256"] or info["stops_hash"] != stops_hash
                or info["hours"] != hours or info["sha256"] != sha256(target)):
            raise ValueError("추가 버스 캐시 설정·해시 불일치")
        if info.get("schema_revision") == 2:
            return info
    if kind != "bus_passengers":
        old_entries = json.loads((CASE / "results/directional/extraction_audit.json").read_text())
        found = [x for x in old_entries if x["kind"] == kind and x["month"] == month]
        if len(found) == 1:
            info = found[0]
            old = CASE / info["path"]
            if (info["raw_sha256"] == entry["sha256"] and info["stops_hash"] == stops_hash
                    and set(hours).issubset(info["hours"]) and sha256(old) == info["sha256"]):
                return {**info, "reused": "directional_verified_cache"}
    keys, columns, rename = schema(kind, hours)
    parts, dates, total, members_audit = [], set(), 0, []
    with ZipFile(path) as archive:
        members = sorted(n for n in archive.namelist() if n.lower().endswith(".csv"))
        if not members:
            raise ValueError("버스 압축파일에 CSV가 없습니다")
        for name in members:
            with archive.open(name) as stream:
                reader = csv.reader(io.TextIOWrapper(stream, encoding="cp949"))
                header = next(reader, [])
                first = next(reader, None)
                if not set(keys + columns).issubset(header) or (first is not None and len(header) != len(first)):
                    members_audit.append({"member": name, "status": "quarantined_header_row_mismatch",
                        "header_columns": len(header), "first_row_columns": len(first) if first is not None else 0})
                    print(f"원본 주간 파일 격리: {kind} {month} {name}", flush=True)
                    continue
                if first is None:
                    members_audit.append({"member": name, "status": "empty"})
                    continue
                members_audit.append({"member": name, "status": "accepted", "header_columns": len(header)})
            with archive.open(name) as stream:
                for chunk in pd.read_csv(stream, encoding="cp949", dtype=str, usecols=keys + columns, chunksize=100000):
                    total += len(chunk)
                    pd.to_datetime(chunk["기준_날짜"].unique(), format="%Y%m%d", errors="raise")
                    dates.update(chunk["기준_날짜"].unique())
                    parts.append(choose_chunk(chunk, kind, stops, columns))
    frame = (pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=keys + columns)).rename(columns=rename)
    pd.to_datetime(list(dates), format="%Y%m%d", errors="raise")
    if frame[list(rename[k] for k in keys)].isna().any().any():
        raise ValueError("버스 원본 결합 키 결측")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".parquet.tmp")
    frame.to_parquet(temp, index=False)
    temp.replace(target)
    info = {"kind": kind, "month": month, "path": str(target.relative_to(CASE)), "raw_sha256": entry["sha256"],
            "rows_scanned": total, "rows_selected": len(frame), "dates": sorted(dates), "hours": hours,
            "stops_hash": stops_hash, "sha256": sha256(target), "parser_sha256": sha256(Path(__file__)),
            "schema_revision": 2, "member_validation": members_audit}
    write_json(info_path, info)
    print(f"추가 버스 추출: {kind} {month} {len(frame):,}행", flush=True)
    return info


def prepare(scope):
    if scope not in {"passengers", "multiyear"}:
        raise ValueError("추가 추출 범위는 passengers 또는 multiyear입니다")
    manifest = "overnight-passenger-sources.json" if scope == "passengers" else "overnight-multiyear-sources.json"
    entries = json.loads((CASE / manifest).read_text())["files"]
    held = [x for x in entries if x["month"] < "2023-01"]
    entries = [x for x in entries if x["month"] >= "2023-01"]
    if held:
        write_json(OUT / scope / "held_2022_schema.json", {
            "status": "excluded_pending_source_schema_verification", "files": held,
            "reason": "2022년 4월 일부 주간 CSV는 헤더 31개/데이터 33개, 5월은 첫 헤더 손상 및 빈 파일 발견. 자동 열 이동으로 복구하지 않음.",
            "previous_generated_2022_caches": "어떠한 패널·집계·학습에도 사용하지 않음"})
    hours = list(range(24)) if scope == "passengers" else read_yaml("overnight_multiyear_config.yaml")["parse_hours"]
    stops = sorted(pd.read_csv(CASE / "results/directional/station_registry.csv", dtype={"stop": str}).stop)
    with ProcessPoolExecutor(max_workers=2) as pool:
        outputs = list(pool.map(extract, [(x, stops, hours, scope) for x in entries]))
    write_json(OUT / scope / "extraction_audit.json", outputs)
    print(f"추가 버스 {scope}: {len(outputs)}개 추출 완료", flush=True)


def load_wide(scope, kind, months):
    entries = [x for x in json.loads((OUT / scope / "extraction_audit.json").read_text()) if x["kind"] == kind]
    frames, dates = [], set()
    for item in entries:
        path = CASE / item["path"]
        if not path.resolve().is_relative_to((CASE / "data").resolve()) or sha256(path) != item["sha256"]:
            raise ValueError("추가 버스 추출 파일 경로·해시 불일치")
        frames.append(pd.read_parquet(path))
        dates.update(pd.to_datetime(item["dates"], format="%Y%m%d").strftime("%Y-%m-%d"))
    keys = ["date", "route", "stop", "sequence"]
    if kind in {"bus_time", "bus_passengers"}:
        keys.append("arrival")
    if kind == "bus_time":
        keys.append("arrival_sequence")
    frame, audit = clean_duplicates(pd.concat(frames, ignore_index=True), keys)
    frame["date"] = pd.to_datetime(frame.date, format="%Y%m%d").dt.strftime("%Y-%m-%d")
    frame = frame[frame.date.str[:7].isin(months) & frame.route.ne("0")].copy()
    expected = {str(d.date()) for month in months for d in pd.date_range(month + "-01", periods=pd.Period(month).days_in_month)}
    audit.update(source_available_dates=sorted(expected & dates), source_missing_dates=sorted(expected - dates),
                 rows=len(frame), inputs=[{"path": x["path"], "sha256": x["sha256"]} for x in entries])
    return frame, audit
