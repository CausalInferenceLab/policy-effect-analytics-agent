"""2025년 승차 원본을 별도 경로에 수집하고 전체 CSV 행 구조를 검증하며 고정 정류장을 추출한다."""

import csv
import io
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd

from .common import CASE, digest, read_yaml, sha256, write_json
from .followup import RENAME
from .followup_data import verify
from .overnight_bus_data import collect_requests

RAW = CASE / "data/overnight/operations_persistence"
OUT = CASE / "results/overnight/operations_persistence"
MANIFEST = CASE / "overnight-operations-persistence-sources.json"
KEYS = ["기준_날짜", "노선_ID", "정류장_ID", "정류장_순서"]


def collect():
    cfg = read_yaml("overnight_operations_persistence_config.yaml")
    wanted = {(cfg["kind"], month) for month in cfg["boarding_download_months"]}
    if cfg["kind"] != "bus_boardings" or cfg["locked_year"] != 2026:
        raise ValueError("운영 연장의 종류·잠금 연도 설정 오류")
    collect_requests(wanted, MANIFEST, RAW, "2025년 고정 공통 셀의 승차 기록 연장. 4월은 주간 파일의 월 경계용이며 결과 기간은 고정.")


def read_archive(path, stops, hours):
    columns = [f"승차_승객_수_{hour:02}시" for hour in hours]
    selected, dates, total, members = [], set(), 0, []
    with ZipFile(path) as archive:
        names = sorted(name for name in archive.namelist() if name.lower().endswith(".csv"))
        if not names:
            raise ValueError("승차 ZIP에 CSV가 없습니다")
        for name in names:
            with archive.open(name) as stream:
                reader = csv.reader(io.TextIOWrapper(stream, encoding="cp949"))
                header = next(reader, [])
                if len(header) != len(set(header)) or not set(KEYS + columns).issubset(header):
                    raise ValueError(f"승차 CSV 필수 열 누락·헤더 중복: {name}")
                indexes = [header.index(column) for column in KEYS + columns]
                date_index, stop_index = header.index("기준_날짜"), header.index("정류장_ID")
                scanned = 0
                for row in reader:
                    scanned += 1
                    if len(row) != len(header):
                        raise ValueError(f"승차 CSV 행 길이 오류: {name}, 데이터 {scanned}행")
                    dates.add(row[date_index])
                    if row[stop_index] in stops:
                        selected.append([row[index] for index in indexes])
                total += scanned
                members.append({"member": name, "header_columns": len(header), "rows_scanned": scanned,
                                "status": "all_row_widths_verified" if scanned else "empty"})
    pd.to_datetime(list(dates), format="%Y%m%d", errors="raise")
    frame = pd.DataFrame(selected, columns=KEYS + columns)
    if frame[KEYS].isna().any().any() or frame[KEYS].eq("").any().any():
        raise ValueError("승차 선택 행의 결합 키 결측")
    for column in columns:
        frame[column] = pd.to_numeric(frame[column].mask(frame[column].eq("")), errors="raise")
        if np.isinf(frame[column]).any():
            raise ValueError("승차 기록에 무한대가 있습니다")
    frame = frame.rename(columns=RENAME | {column: f"h{hour:02}" for column, hour in zip(columns, hours, strict=True)})
    return frame, sorted(dates), total, members


def extract(job):
    entry, stops, hours = job
    if entry["kind"] != "bus_boardings" or entry["month"] not in ["2025-04", "2025-05", "2025-06", "2025-07", "2025-08"]:
        raise ValueError("운영 연장 추출의 허용 종류·월 범위 밖")
    path = verify(entry)
    target = RAW / "processed" / f"bus_boardings_{entry['month']}.parquet"
    sidecar = target.with_suffix(".json")
    signature = digest({"raw": entry["sha256"], "stops": sorted(stops), "hours": hours, "parser": sha256(Path(__file__))})
    if target.exists():
        info = json.loads(sidecar.read_text())
        if info["signature"] != signature or sha256(target) != info["sha256"]:
            raise ValueError("승차 연장 추출 캐시의 설정·해시 불일치")
        return info
    frame, dates, total, members = read_archive(path, set(stops), hours)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".parquet.tmp")
    frame.to_parquet(temporary, index=False)
    temporary.replace(target)
    info = {"kind": entry["kind"], "month": entry["month"], "path": str(target.relative_to(CASE)),
            "raw_sha256": entry["sha256"], "sha256": sha256(target), "signature": signature,
            "rows_scanned": total, "rows_selected": len(frame), "dates": dates, "hours": hours,
            "stops_hash": digest(sorted(stops)), "parser_sha256": sha256(Path(__file__)), "members": members}
    write_json(sidecar, info)
    print(f"승차 연장 추출: {entry['month']}, 전체 {total:,}행 / 선택 {len(frame):,}행", flush=True)
    return info


def prepare():
    cfg = read_yaml("overnight_operations_persistence_config.yaml")
    entries = json.loads(MANIFEST.read_text())["files"]
    if len(entries) != len(cfg["boarding_download_months"]) or {entry["month"] for entry in entries} != set(cfg["boarding_download_months"]):
        raise ValueError("승차 연장 원본의 월 범위 누락·중복")
    registry = CASE / "results/directional/station_registry.csv"
    stops = sorted(pd.read_csv(registry, dtype={"stop": str}).stop)
    hours = sorted({hour for band in read_yaml(cfg["calendar_from"])["bands"].values() for hour in band})
    workers = cfg["resources"]["parser_workers"]
    if workers not in {1, 2}:
        raise ValueError("승차 동시 파서는 최대 2개")
    with ProcessPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(extract, [(entry, stops, hours) for entry in entries]))
    write_json(OUT / "extraction_audit.json", results)
    write_json(OUT / "preparation_audit.json", {"config_sha256": sha256(CASE / "overnight_operations_persistence_config.yaml"),
               "source_manifest_sha256": sha256(MANIFEST), "registry_sha256": sha256(registry), "code_sha256": sha256(Path(__file__)),
               "extraction_audit_sha256": sha256(OUT / "extraction_audit.json"), "rows_scanned": sum(item["rows_scanned"] for item in results)})
