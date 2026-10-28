"""월별 카드의 반복 행 대조용 일별 승하차 CSV를 제한된 월에 대해 수집한다."""

from __future__ import annotations

import csv
import json
import shutil
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .overnight_auxiliary_data import URL, download_request
from .topis import session

RAW = CASE / "data/overnight/daily_cards"
OUT = CASE / "results/overnight/daily_cards"
MANIFEST = CASE / "overnight-daily-card-sources.json"
HEADERS = ["사용일자", "노선번호", "노선명", "표준버스정류장ID", "버스정류장ARS번호", "역명", "승차총승객수", "하차총승객수", "등록일자"]


def validate(path, month):
    for encoding in ["cp949", "utf-8-sig"]:
        try:
            with path.open(encoding=encoding, newline="") as f:
                reader = csv.reader(f)
                header, row = next(reader, None), next(reader, None)
            if header == HEADERS and row and len(row) == len(HEADERS) and row[0][:6] == month.replace("-", ""):
                return encoding
        except UnicodeError:
            continue
    raise ValueError("일별 카드 CSV의 헤더·첫 날짜·인코딩이 요청과 다릅니다")


def verify(entry):
    path = CASE / entry["path"]
    if not path.resolve().is_relative_to((CASE / "data").resolve()):
        raise ValueError("일별 카드 경로가 data 밖입니다")
    if path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
        raise ValueError("일별 카드 원본 해시 불일치")
    if validate(path, entry["month"]) != entry["encoding"]:
        raise ValueError("일별 카드 인코딩 변경")
    return path


def collect():
    cfg = read_yaml("overnight_daily_card_config.yaml")
    if cfg["resources"]["download_workers"] not in {1, 2} or cfg["locked_year"] != 2026:
        raise ValueError("일별 카드 수집의 동시 작업·잠금 연도 설정 오류")
    months = cfg["months"]
    if len(months) != len(set(months)) or any(pd.Period(m, freq="M").year >= cfg["locked_year"] for m in months):
        raise ValueError("일별 카드 중복 월 또는 잠금 연도 요청")
    RAW.mkdir(parents=True, exist_ok=True)
    entries = {}
    for path in ([MANIFEST] if MANIFEST.exists() else []) + list(RAW.glob("*.source.json")):
        data = json.loads(path.read_text())
        for e in data["files"] if "files" in data else [data]:
            if e["month"] in entries and entries[e["month"]]["sha256"] != e["sha256"]:
                raise ValueError("같은 월의 출처 해시 충돌")
            entries[e["month"]] = e
    if not set(entries).issubset(months):
        raise ValueError("설정 밖의 일별 카드 원본이 명세에 있습니다")
    for e in entries.values():
        verify(e)
    source = f"https://data.seoul.go.kr/dataList/{cfg['dataset']}/S/1/datasetView.do"
    with session() as client:
        response = client.get(source, timeout=(15, 60))
        response.raise_for_status()
    jobs = []
    for month in months:
        if month in entries:
            continue
        title = f"BUS_STATION_BOARDING_MONTH_{month.replace('-', '')}.csv"
        jobs.append({"month": month, "source": source, "url": URL, "method": "POST", "title": title,
                     "request": download_request(response.text, cfg["dataset"], title),
                     "path": str((RAW / f"card_daily_{month}.csv").relative_to(CASE))})

    def save():
        write_json(MANIFEST, {"description": "월별 시간대 카드와의 집계·중복 구분 대조용 서울 면허 일별 카드 원본",
                              "config_sha256": sha256(CASE / "overnight_daily_card_config.yaml"),
                              "files": sorted(entries.values(), key=lambda x: x["month"])})

    def fetch(spec):
        if shutil.disk_usage(CASE).free < cfg["resources"]["minimum_free_gib"] * 1024**3:
            raise ValueError("디스크 여유가 수집 하한보다 작습니다")
        path = CASE / spec["path"]
        if path.exists():
            raise ValueError("출처 없는 일별 카드 파일을 덮어쓰지 않습니다")
        part = path.with_suffix(".csv.part")
        try:
            with session() as client, client.post(URL, data=spec["request"], headers={"Referer": source},
                                                  stream=True, timeout=(20, 120)) as r:
                r.raise_for_status()
                if "html" in r.headers.get("Content-Type", "").lower():
                    raise ValueError("일별 카드 대신 HTML 응답")
                size = 0
                with part.open("wb") as f:
                    for chunk in r.iter_content(1024 * 1024):
                        size += len(chunk)
                        if size > cfg["resources"]["compressed_csv_limit_mib"] * 1024**2:
                            raise ValueError("일별 카드 원본 크기가 상한을 초과합니다")
                        f.write(chunk)
                if r.headers.get("Content-Length") and int(r.headers["Content-Length"]) != size:
                    raise ValueError("불완전한 일별 카드 다운로드")
            encoding = validate(part, spec["month"])
            entry = {**spec, "bytes": size, "sha256": sha256(part), "encoding": encoding, "retrieved_at": utcnow()}
            part.replace(path)
            write_json(path.with_suffix(".csv.source.json"), entry)
            return entry
        finally:
            part.unlink(missing_ok=True)

    save()
    with ThreadPoolExecutor(max_workers=cfg["resources"]["download_workers"]) as pool:
        for entry in pool.map(fetch, jobs):
            entries[entry["month"]] = entry
            save()
            print(f"일별 카드 수집: {entry['month']} {entry['bytes']:,} bytes", flush=True)
    print(f"일별 카드 원본 {len(entries)}개 확인", flush=True)
