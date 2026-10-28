"""분석에 사용한 2023~2025년 버스 압축 원본의 모든 CSV 행 구조를 별도로 감사한다."""

from __future__ import annotations

import csv
import io
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from zipfile import ZipFile

import pandas as pd

from .common import CASE, digest, sha256, utcnow, write_json
from .followup import VALUES
from .overnight_2022_audit import audit_reader
from .overnight_bus_extract import schema

OUT = CASE / "results/overnight/archive_audit"
CACHE = CASE / "data/overnight/archive_audit"
MANIFESTS = ["directional-sources.json", "overnight-multiyear-sources.json", "overnight-forecast-bus-test-sources.json", "overnight-passenger-sources.json"]


def scan(job):
    entry, code_hash = job
    if not "2023-01" <= entry["month"] <= "2025-08":
        raise ValueError("2023년~2025년 8월 범위 밖 원본 검사 금지")
    path = CASE / entry["path"]
    if not path.resolve().is_relative_to((CASE / "data").resolve()) or sha256(path) != entry["sha256"]:
        raise ValueError("원본 경로·해시 불일치")
    target = CACHE / f"{entry['kind']}_{entry['month']}.json"
    if target.exists():
        cached = json.loads(target.read_text())
        if cached["raw_sha256"] == entry["sha256"] and cached["checker_sha256"] == code_hash:
            return cached
    if entry["kind"] == "bus_boardings":
        required = ["기준_날짜", "노선_ID", "정류장_ID", "정류장_순서", *[f"{VALUES['bus_boardings']}_{h:02}시" for h in range(24)]]
    else:
        keys, values, _ = schema(entry["kind"], list(range(24)))
        required = keys + values
    members = []
    with ZipFile(path) as archive:
        for name in sorted(n for n in archive.namelist() if n.lower().endswith(".csv")):
            with archive.open(name) as stream:
                info = audit_reader(csv.reader(io.TextIOWrapper(stream, encoding="cp949")), required)
            members.append({"member": name, **info})
    result = {"kind": entry["kind"], "month": entry["month"], "path": entry["path"], "raw_sha256": entry["sha256"],
        "checker_sha256": code_hash, "members": members, "completed_at": utcnow()}
    write_json(target, result)
    print(f"사용 원본 전체 행 검사: {entry['kind']} {entry['month']} {sum(x['rows'] for x in members):,}행", flush=True)
    return result


def run():
    by_key = {}
    for name in MANIFESTS:
        for entry in json.loads((CASE / name).read_text())["files"]:
            if "2023-01" <= entry["month"] <= "2025-08":
                key = (entry["kind"], entry["month"])
                if key in by_key and by_key[key]["sha256"] != entry["sha256"]:
                    raise ValueError("같은 원본 종류·월의 해시가 서로 다릅니다")
                by_key[key] = entry
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    hashes = {str(p.relative_to(CASE)): sha256(p) for p in [Path(__file__), CASE / "gangnam/overnight_2022_audit.py"]}
    checker = digest(hashes)
    with ProcessPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(scan, [(v, checker) for _, v in sorted(by_key.items())]))
    rows = []
    for entry in results:
        for member in entry["members"]:
            rows.append({"kind": entry["kind"], "month": entry["month"], "member": member["member"],
                **{k: member[k] for k in ["rows", "header_columns", "invalid_date_rows", "status", "structurally_usable"]},
                "row_width_counts": json.dumps(member["row_width_counts"], sort_keys=True),
                "missing_required_headers": "|".join(member["missing_required_headers"]),
                "date_count": len(member["dates"]), "first_date": min(member["dates"], default=""), "last_date": max(member["dates"], default="")})
    pd.DataFrame(rows).to_csv(OUT / "members.csv", index=False)
    write_json(OUT / "audit.json", {"completed_at": utcnow(), "code_hashes": hashes,
        "source_manifests": {name: sha256(CASE / name) for name in MANIFESTS}, "files": len(results),
        "members": len(rows), "rows_scanned": sum(x["rows"] for x in rows),
        "non_usable_members": [x for x in rows if not x["structurally_usable"]],
        "members_sha256": sha256(OUT / "members.csv"),
        "detailed_cache": [{"kind": x["kind"], "month": x["month"], "path": str((CACHE / f"{x['kind']}_{x['month']}.json").relative_to(CASE)),
                            "sha256": sha256(CACHE / f"{x['kind']}_{x['month']}.json")} for x in results],
        "scope": "기존 추출·모델을 수정하지 않는 추가 형식 감사. 새 손상 발견 시 결과 영향부터 별도로 판단. 2026년 자료 미접근."})
