"""2025년 일반도로 비교에 필요한 교통량 4개월을 수집하고 기존 2024년 원본을 재사용한다."""

import json
import shutil
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .overnight_road_context_data import verify
from .topis import BASE, session, validate_xlsx

RAW = CASE / "data/overnight/road_persistence"
MANIFEST = CASE / "overnight-road-persistence-sources.json"


def collect():
    cfg = read_yaml("overnight_road_persistence_config.yaml")
    months = cfg["months"]
    if len(months) != len(set(months)) or any(pd.Period(m).year >= cfg["locked_year"] for m in months):
        raise ValueError("교통량 월 중복 또는 잠금 연도 접근")
    RAW.mkdir(parents=True, exist_ok=True)
    entries = {}
    sources = [CASE / cfg["volume"]["original_sources"], *([MANIFEST] if MANIFEST.exists() else []), *RAW.glob("*.source.json")]
    for path in sources:
        obj = json.loads(path.read_text())
        for item in obj["files"] if "files" in obj else [obj]:
            if item.get("kind") != "volume" or item["month"] not in months:
                continue
            if item["month"] in entries and entries[item["month"]]["sha256"] != item["sha256"]:
                raise ValueError("같은 월 교통량의 원본 해시 충돌")
            verify(item, cfg)
            entries[item["month"]] = item
    jobs = []
    with session() as client:
        for year in sorted({m[:4] for m in months if m not in entries}):
            response = client.post(BASE + "/refroom/selectRefRoomListASC.do",
                                   data={"blbdDivCd": "08", "bdwrDivCd": year, "mainBdwrRowNum": "12"}, timeout=(15, 60))
            response.raise_for_status()
            rows = {int(row["months"]): row for row in response.json()["rows"]}
            for month in [m for m in months if m.startswith(year) and m not in entries]:
                row = rows[int(month[-2:])]
                if not row.get("apndFileNm"):
                    raise ValueError(f"공식 목록의 첨부 없음: {month}")
                jobs.append({"kind": "volume", "month": month, "path": f"data/overnight/road_persistence/volume_{month}.xlsx",
                             "source": cfg["volume"]["source"], "url": BASE + "/downloadFileRefRoom.do", "method": "POST",
                             "request": {k: row[k] for k in ["apndFileNm", "apndFilePathNm", "bdwrSeq", "blbdDivCd"]}})

    def fetch(item):
        if shutil.disk_usage(CASE).free < cfg["resources"]["minimum_free_gib"] * 1024**3:
            raise ValueError("수집 디스크 여유 하한 미달")
        path = CASE / item["path"]
        if path.exists():
            raise ValueError("출처 없는 교통량 파일 덮어쓰기 금지")
        part = path.with_suffix(".xlsx.part")
        try:
            with session() as client, client.post(item["url"], data=item["request"], headers={"Referer": item["source"]},
                                                  stream=True, timeout=(20, 120)) as response:
                response.raise_for_status()
                if "html" in response.headers.get("Content-Type", "").lower():
                    raise ValueError("교통량 원본 대신 HTML 응답")
                size = 0
                with part.open("wb") as target:
                    for chunk in response.iter_content(1024 * 1024):
                        size += len(chunk)
                        if size > cfg["resources"]["file_limit_mib"] * 1024**2:
                            raise ValueError("교통량 파일 크기 상한 초과")
                        target.write(chunk)
                if response.headers.get("Content-Length") and int(response.headers["Content-Length"]) != size:
                    raise ValueError("불완전한 교통량 다운로드")
            validate_xlsx(part)
            entry = {**item, "bytes": size, "sha256": sha256(part), "retrieved_at": utcnow()}
            part.replace(path)
            write_json(path.with_suffix(".xlsx.source.json"), entry)
            return entry
        finally:
            part.unlink(missing_ok=True)

    def save():
        write_json(MANIFEST, {"description": "2024·2025년 고정 교통량 지점 비교의 월 원본",
                             "config_sha256": sha256(CASE / "overnight_road_persistence_config.yaml"),
                             "code_sha256": sha256(__file__), "files": sorted(entries.values(), key=lambda row: row["month"])})

    workers = cfg["resources"]["download_workers"]
    if workers not in {1, 2}:
        raise ValueError("교통량 동시 다운로드는 최대 2개")
    save()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for entry in pool.map(fetch, jobs):
            entries[entry["month"]] = entry
            save()
            print(f"교통량 연장 수집: {entry['month']}, {entry['bytes']:,} bytes", flush=True)
    if set(entries) != set(months):
        raise ValueError("교통량 수집 월 범위 불일치")
    print(f"교통량 원본 {len(entries)}개 검증 완료", flush=True)
