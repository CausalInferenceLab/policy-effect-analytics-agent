"""다년 주변 교통량의 공식 월 원본을 검증하며 기존 파일과 함께 수집한다."""

from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .topis import BASE, session, validate_xlsx

RAW = CASE / "data/overnight/road_context"
MANIFEST = CASE / "overnight-road-context-sources.json"


def verify(entry, cfg):
    path = CASE / entry["path"]
    if not path.resolve().is_relative_to((CASE / "data").resolve()):
        raise ValueError("교통량 경로가 data 밖입니다")
    if pd.Period(entry["month"]).year >= cfg["locked_year"]:
        raise ValueError("잠금 연도 교통량 접근 금지")
    if path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
        raise ValueError("교통량 원본 해시 불일치")
    if entry["bytes"] > cfg["resources"]["file_limit_mib"] * 1024**2:
        raise ValueError("교통량 원본이 크기 상한을 넘습니다")
    validate_xlsx(path)
    return path


def collect():
    cfg = read_yaml("overnight_road_context_config.yaml")
    months = cfg["months"]
    if len(set(months)) != len(months) or any(pd.Period(m).year >= cfg["locked_year"] for m in months):
        raise ValueError("교통량 요청 월 중복·잠금 연도")
    if cfg["resources"]["download_workers"] not in {1, 2}:
        raise ValueError("교통량 동시 수집은 1~2개입니다")
    RAW.mkdir(parents=True, exist_ok=True)
    entries = {}
    paths = [CASE / "followup-sources.json", *([MANIFEST] if MANIFEST.exists() else []), *RAW.glob("*.source.json")]
    for path in paths:
        obj = json.loads(path.read_text())
        for e in obj["files"] if "files" in obj else [obj]:
            if e.get("kind") == "volume" and e["month"] in months:
                if e["month"] in entries and entries[e["month"]]["sha256"] != e["sha256"]:
                    raise ValueError("교통량 명세에 같은 월의 다른 원본이 있습니다")
                entries[e["month"]] = e
    for entry in entries.values():
        verify(entry, cfg)
    jobs = []
    with session() as client:
        for year in sorted({m[:4] for m in months}):
            response = client.post(BASE + "/refroom/selectRefRoomListASC.do",
                                   data={"blbdDivCd": "08", "bdwrDivCd": year, "mainBdwrRowNum": "12"}, timeout=(15, 60))
            response.raise_for_status()
            rows = {int(x["months"]): x for x in response.json()["rows"]}
            for month in months:
                if not month.startswith(year) or month in entries:
                    continue
                row = rows[int(month[-2:])]
                if not row.get("apndFileNm"):
                    raise ValueError(f"공식 교통량 목록에 첨부가 없습니다: {month}")
                jobs.append({"kind": "volume", "month": month, "path": f"data/overnight/road_context/volume_{month}.xlsx",
                             "source": cfg["volume"]["source"], "url": BASE + "/downloadFileRefRoom.do", "method": "POST",
                             "request": {k: row[k] for k in ("apndFileNm", "apndFilePathNm", "bdwrSeq", "blbdDivCd")}})

    def save():
        write_json(MANIFEST, {"description": "2023·2024년 주변 교통량의 월 원본과 재사용 출처",
                              "config_sha256": sha256(CASE / "overnight_road_context_config.yaml"),
                              "files": sorted(entries.values(), key=lambda e: e["month"])})

    def fetch(spec):
        if shutil.disk_usage(CASE).free < cfg["resources"]["minimum_free_gib"] * 1024**3:
            raise ValueError("교통량 수집의 디스크 여유 하한 미달")
        path = CASE / spec["path"]
        if path.exists():
            raise ValueError("출처 없는 교통량 파일을 덮어쓰지 않습니다")
        part = path.with_suffix(".xlsx.part")
        try:
            with session() as client, client.post(spec["url"], data=spec["request"], headers={"Referer": spec["source"]},
                                                  stream=True, timeout=(20, 120)) as response:
                response.raise_for_status()
                if "html" in response.headers.get("Content-Type", "").lower():
                    raise ValueError("교통량 파일 대신 HTML 응답")
                size = 0
                with part.open("wb") as f:
                    for chunk in response.iter_content(1024 * 1024):
                        size += len(chunk)
                        if size > cfg["resources"]["file_limit_mib"] * 1024**2:
                            raise ValueError("교통량 다운로드 크기 상한 초과")
                        f.write(chunk)
                if response.headers.get("Content-Length") and int(response.headers["Content-Length"]) != size:
                    raise ValueError("교통량 다운로드가 불완전합니다")
            validate_xlsx(part)
            entry = {**spec, "bytes": size, "sha256": sha256(part), "retrieved_at": utcnow()}
            part.replace(path)
            write_json(path.with_suffix(".xlsx.source.json"), entry)
            return entry
        finally:
            part.unlink(missing_ok=True)

    save()
    with ThreadPoolExecutor(max_workers=cfg["resources"]["download_workers"]) as pool:
        for entry in pool.map(fetch, jobs):
            entries[entry["month"]] = entry
            save()
            print(f"주변 교통량 수집: {entry['month']} {entry['bytes']:,} bytes", flush=True)
    print(f"주변 교통량 {len(entries)}개 원본 확인", flush=True)
