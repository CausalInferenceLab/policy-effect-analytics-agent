"""환승·출도착 월 원본의 모든 행 구조와 고정 정류장 관련 기록을 순차 검사한다."""

from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from zipfile import ZipFile

import pandas as pd

from .common import CASE, sha256, utcnow, write_json
from .overnight_auxiliary_data import MANIFEST, verify

OUT = CASE / "results/overnight/auxiliary"
CACHE = CASE / "data/overnight/auxiliary/processed"
REGISTRY = CASE / "results/directional/station_registry.csv"
TRANSFER = ["기준_날짜", "하차_정류장/역사_ID", "승차_정류장/역사_ID", "시간대", "환승_수_합",
            *[f"환승_수_합_{x}" for x in ["일반", "어린이", "청소년", "경로", "장애인"]],
            "환승_시간_평균", *[f"환승_시간_평균_{x}" for x in ["일반", "어린이", "청소년", "경로", "장애인"]]]
OD = ["기준_날짜", "승차_정류장/역사_ID", "하차_정류장/역사_ID", "승객_수", *[f"승객_수_{h:02}시" for h in range(24)]]


def header_encoding(first_line, expected):
    for encoding in ["cp949", "utf-8-sig"]:
        try:
            if next(csv.reader([first_line.decode(encoding)])) == expected:
                return encoding
        except UnicodeError:
            continue
    raise ValueError("알려진 인코딩으로 공식 헤더를 정확히 읽을 수 없습니다")


def scan_member(stream, expected, day, stops, writer):
    reader = csv.reader(stream)
    header = next(reader, None)
    if header != expected:
        raise ValueError(f"환승·출도착 헤더 변경: {header}")
    counts, lengths, samples = Counter(), Counter(), set()
    for row in reader:
        counts["rows"] += 1
        if len(row) != len(header):
            raise ValueError(f"행 너비 불일치: {day} {counts['rows']}")
        if row[0] != day:
            raise ValueError(f"파일명과 실제 날짜 불일치: {day} {row[0]}")
        a, b = row[1:3]
        lengths[f"{len(a)}_{len(b)}"] += 1
        if not a.isdigit() or not b.isdigit():
            counts["nondecimal_id_rows"] += 1
            if len(samples) < 10:
                samples.add((a, b))
        if a in stops or b in stops:
            writer.writerow(row)
            counts["selected_rows"] += 1
            counts["both_endpoints_selected"] += int(a in stops and b in stops)
    return {"date": day, "rows": counts["rows"], "selected_rows": counts["selected_rows"],
            "both_endpoints_selected": counts["both_endpoints_selected"],
            "nondecimal_id_rows": counts["nondecimal_id_rows"], "id_length_pair_counts": dict(lengths),
            "nondecimal_id_examples": sorted(samples), "status": "data" if counts["rows"] else "header_only"}


def extract(entry):
    verify(entry)
    stops = set(pd.read_csv(REGISTRY, dtype={"stop": str}).stop)
    kind, month = entry["kind"], entry["month"]
    expected = TRANSFER if kind == "transfer_probe" else OD
    target = CACHE / f"{kind}_{month}_v2.csv"
    sidecar = target.with_suffix(".json")
    identity = {"raw_sha256": entry["sha256"], "code_sha256": sha256(Path(__file__)),
                "registry_sha256": sha256(REGISTRY)}
    if target.exists() and sidecar.exists():
        audit = json.loads(sidecar.read_text())
        if all(audit[k] == v for k, v in identity.items()) and audit["sha256"] == sha256(target):
            return audit
        raise ValueError("환승·출도착 추출 캐시가 변경되었습니다")
    if target.exists():
        raise ValueError("감사 명세 없는 추출 파일을 덮어쓰지 않습니다")
    part = target.with_suffix(".csv.part")
    members, seen = [], set()
    try:
        with ZipFile(CASE / entry["path"]) as archive, part.open("w", newline="", encoding="utf-8") as output:
            writer = csv.writer(output)
            writer.writerow(expected)
            for name in sorted(archive.namelist()):
                match = re.search(r"_(20\d{6})\.csv$", name)
                if not match or match[1][:6] != month.replace("-", "") or match[1] in seen:
                    raise ValueError(f"월 범위 밖 또는 중복된 파일 날짜: {name}")
                seen.add(match[1])
                with archive.open(name) as f:
                    encoding = header_encoding(f.readline(), expected)
                with archive.open(name) as f:
                    audit = scan_member(io.TextIOWrapper(f, encoding=encoding), expected, match[1], stops, writer)
                members.append({"member": name, "encoding": encoding, **audit})
                print(f"보조 구조 검사 {kind} {match[1]} {audit['rows']:,}행 / 선택 {audit['selected_rows']:,}", flush=True)
        days = {d.strftime("%Y%m%d") for d in pd.date_range(month + "-01", periods=pd.Period(month).days_in_month)}
        if seen != days:
            raise ValueError(f"월별 파일 날짜 구성 불일치: {sorted(days - seen)}")
        part.replace(target)
        audit = {"kind": kind, "month": month, **identity, "path": str(target.relative_to(CASE)),
                 "sha256": sha256(target), "completed_at": utcnow(), "columns": expected,
                 "rows_scanned": sum(x["rows"] for x in members),
                 "selected_rows": sum(x["selected_rows"] for x in members), "members": members,
                 "source_missing_dates": [x["date"] for x in members if not x["rows"]],
                 "scope": "모든 행의 열 수·날짜·ID 길이를 확인하고 기존 32개 정류장 중 하나를 끝점으로 가진 행을 보존. 수치 정의는 별도 검증."}
        write_json(sidecar, audit)
        return audit
    finally:
        part.unlink(missing_ok=True)


def run():
    CACHE.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    entries = [x for x in json.loads(MANIFEST.read_text())["files"] if x["kind"] in {"transfer_probe", "od_probe"}]
    if {(x["kind"], x["month"]) for x in entries} != {("transfer_probe", "2024-05"), ("od_probe", "2024-05")}:
        raise ValueError("최초 환승·출도착 탐색은 2024년 5월 두 파일로 제한합니다")
    with ProcessPoolExecutor(max_workers=2) as pool:
        audits = list(pool.map(extract, entries))
    rows = []
    for audit in audits:
        for m in audit["members"]:
            rows.append({"kind": audit["kind"], "month": audit["month"], **m,
                         "id_length_pair_counts": json.dumps(m["id_length_pair_counts"], sort_keys=True),
                         "nondecimal_id_examples": json.dumps(m["nondecimal_id_examples"], ensure_ascii=False)})
    pd.DataFrame(rows).to_csv(OUT / "probe_members.csv", index=False)
    write_json(OUT / "probe_audit.json", {"completed_at": utcnow(), "sources_sha256": sha256(MANIFEST),
                                         "files": audits, "members_sha256": sha256(OUT / "probe_members.csv")})
