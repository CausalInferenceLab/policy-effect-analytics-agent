"""방향·계절 점검의 추가 원본을 수집하고 기존 후속 원본과 추출 캐시를 보존한다."""

from __future__ import annotations

import json
import re
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd

from .common import CASE, digest, read_yaml, sha256, utcnow, write_json
from .followup import RENAME, VALUES, registry
from .followup_data import DATASETS, fetch_one, verify
from .topis import session

RAW = CASE / "data/directional"
CACHE = RAW / "processed"
OUT = CASE / "results/directional"
MANIFEST = CASE / "directional-sources.json"


def sources():
    return json.loads(MANIFEST.read_text())["files"] if MANIFEST.exists() else []


def collect():
    cfg = read_yaml("directional_config.yaml")
    RAW.mkdir(parents=True, exist_ok=True)
    existing = {(x["kind"], x["month"]): x for x in sources()}
    for x in json.loads((CASE / "followup-sources.json").read_text())["files"]:
        if x["kind"] in cfg["bus_kinds"]:
            existing.setdefault((x["kind"], x["month"]), x)
    for path in RAW.glob("*.source.json"):
        x = json.loads(path.read_text())
        existing.setdefault((x["kind"], x["month"]), x)
    for x in existing.values():
        verify(x)
    jobs = []
    with session() as client:
        for kind in cfg["bus_kinds"]:
            dataset, prefix = DATASETS[kind]
            source = f"https://data.seoul.go.kr/dataList/{dataset}/S/1/datasetView.do"
            response = client.get(source, timeout=(15, 60))
            response.raise_for_status()
            for month in cfg["months"] + cfg.get("boundary_months", []):
                if (kind, month) in existing:
                    continue
                title = f"{prefix}_{month.replace('-', '')}.zip"
                match = re.search(re.escape(title) + r"[^>]*downloadFile\('([^']+)'\)", response.text)
                if not match:
                    raise ValueError(f"공식 월 파일의 다운로드 인자 없음: {title}")
                jobs.append({"kind": kind, "month": month, "path": f"data/directional/{kind}_{month}.zip",
                             "source": source, "url": "https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do?&useCache=false",
                             "method": "POST", "request": {"infId": dataset, "infSeq": "3", "seq": match[1], "seqNo": ""}})
    def save():
        write_json(MANIFEST, {"description": "전년 동기간과 가을 지속성 점검용 원본. 기존 후속 파일을 재사용하며 재배포하지 않음.",
                              "files": sorted(existing.values(), key=lambda x: (x["kind"], x["month"]))})
    save()
    with ThreadPoolExecutor(max_workers=2) as pool:
        for x in pool.map(fetch_one, jobs):
            existing[(x["kind"], x["month"])] = x
            save()
            print(f"수집: {x['kind']} {x['month']} {x['bytes']:,} bytes", flush=True)
    print(f"방향·계절 원본 {len(existing)}개", flush=True)


def extract(args):
    entry, stops, hours = args
    path = verify(entry)
    cols = [f"{VALUES[entry['kind']]}_{h:02}시" for h in hours]
    keys = ["기준_날짜", "노선_ID"]
    keys += (["출발_정류장_ID", "출발_정류장_순서", "도착_정류장_ID", "도착_정류장_순서"]
             if entry["kind"] == "bus_time" else ["정류장_ID", "정류장_순서"])
    parts, dates, total = [], set(), 0
    with ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            with archive.open(name) as f:
                for chunk in pd.read_csv(f, encoding="cp949", dtype=str, usecols=keys + cols, chunksize=100000):
                    total += len(chunk)
                    dates.update(chunk["기준_날짜"].unique())
                    chosen = chunk[keys[2]].isin(stops)
                    if entry["kind"] == "bus_time":
                        chosen |= chunk["도착_정류장_ID"].isin(stops)
                    part = chunk.loc[chosen].copy()
                    for col in cols:
                        part[col] = pd.to_numeric(part[col], errors="raise")
                        if not np.isfinite(part[col].dropna()).all():
                            raise ValueError("비유한 버스 수치")
                    parts.append(part)
    d = pd.concat(parts, ignore_index=True).rename(columns=RENAME | {c: f"h{h:02}" for c, h in zip(cols, hours, strict=True)})
    pd.to_datetime(d.date, format="%Y%m%d", errors="raise")
    target = CACHE / f"{entry['kind']}_{entry['month']}.parquet"
    temporary = target.with_suffix(".parquet.tmp")
    d.to_parquet(temporary, index=False)
    temporary.replace(target)
    info = {"kind": entry["kind"], "month": entry["month"], "path": str(target.relative_to(CASE)),
            "raw_sha256": entry["sha256"], "rows_scanned": total, "rows_selected": len(d), "dates": sorted(dates),
            "hours": hours, "stops_hash": digest(sorted(stops)), "parser_sha256": sha256(Path(__file__)), "sha256": sha256(target)}
    write_json(target.with_suffix(".json"), info)
    print(f"추출: {entry['kind']} {entry['month']} {len(d):,}행", flush=True)
    return info


def prepare():
    cfg, stops = read_yaml("directional_config.yaml"), set(registry().stop)
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    jobs, entries = [], []
    for source in sources():
        targets = [CACHE / f"{source['kind']}_{source['month']}.parquet",
                   CASE / f"data/followup/processed/{source['kind']}_{source['month']}.parquet"]
        for target in targets:
            if not target.exists() or not target.with_suffix(".json").exists():
                continue
            info = json.loads(target.with_suffix(".json").read_text())
            if (sha256(target) != info["sha256"] or source["sha256"] != info["raw_sha256"]
                    or info["hours"] != cfg["profile_hours"] or info["stops_hash"] != digest(sorted(stops))):
                raise ValueError(f"기존 캐시 조건·해시 불일치: {target}")
            entries.append({**info, "kind": source["kind"], "month": source["month"], "path": str(target.relative_to(CASE))})
            break
        else:
            jobs.append((source, stops, cfg["profile_hours"]))
    with ProcessPoolExecutor(max_workers=2) as pool:
        entries.extend(pool.map(extract, jobs))
    write_json(OUT / "extraction_audit.json", sorted(entries, key=lambda x: (x["kind"], x["month"])))


def collect_history():
    """2023년 월별 카드 파일은 승객 결과 대신 표준 정류장 ID·ARS의 당시 대응 확인에 쓴다."""
    source = "https://data.seoul.go.kr/dataList/OA-12913/F/1/datasetView.do"
    manifest = CASE / "directional-history-sources.json"
    entries = json.loads(manifest.read_text())["files"] if manifest.exists() else []
    by_month = {x["month"]: x for x in entries}
    folder = RAW / "history"
    folder.mkdir(parents=True, exist_ok=True)
    if set(by_month) == {"202305", "202307"}:
        for entry in by_month.values():
            if sha256(CASE / entry["path"]) != entry["sha256"]:
                raise ValueError("역사적 정류장 원본 변경")
        return
    with session() as client:
        r = client.get(source, timeout=(15, 60))
        r.raise_for_status()
        for month in ("202305", "202307"):
            path = folder / f"boarding_{month}.csv"
            if month in by_month:
                if sha256(path) != by_month[month]["sha256"]:
                    raise ValueError("역사적 정류장 원본 변경")
                continue
            if path.exists():
                raise ValueError("출처 없는 역사적 정류장 원본")
            title = f"2023년_버스노선별_정류장별_시간대별_승하차_인원_정보({month[-2:]}월).csv"
            match = re.search(re.escape(title) + r"[^>]*downloadFile\('([^']+)'\)", r.text)
            if not match:
                raise ValueError(f"역사적 정류장 파일 목록 없음: {month}")
            url = "https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do?&useCache=false"
            request = {"infId": "OA-12913", "infSeq": "3", "seq": match[1], "seqNo": ""}
            response = client.post(url, data=request, headers={"Referer": source}, timeout=(20, 90))
            response.raise_for_status()
            if len(response.content) > 30 * 1024**2:
                raise ValueError("역사적 카드 CSV가 30 MiB를 초과합니다")
            d = pd.read_csv(BytesIO(response.content), encoding="cp949", dtype=str,
                            usecols=["사용년월", "표준버스정류장ID", "버스정류장ARS번호"])
            if set(d["사용년월"]) != {month}:
                raise ValueError("역사적 카드 CSV의 실제 월 불일치")
            path.write_bytes(response.content)
            by_month[month] = {"month": month, "path": str(path.relative_to(CASE)), "source": source,
                               "url": url, "method": "POST", "request": request, "bytes": len(response.content),
                               "sha256": sha256(path), "retrieved_at": utcnow()}
            write_json(manifest, {"description": "2023년 표준 정류장 ID·ARS 대조용 카드 월별 원본", "files": list(by_month.values())})
            print(f"역사적 정류장 대조: {month}", flush=True)
