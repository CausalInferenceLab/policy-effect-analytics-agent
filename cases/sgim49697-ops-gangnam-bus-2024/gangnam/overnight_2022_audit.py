"""보류한 2022년 버스 원본의 모든 행 폭·헤더·날짜를 점검하되 운행시간을 분석하지 않는다."""

from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

import pandas as pd

from .common import CASE, sha256, utcnow, write_json
from .overnight_bus_extract import schema

OUT = CASE / "results/overnight/schema2022"


def audit_reader(reader, required):
    header = next(reader, [])
    counts, dates, width_examples = Counter(), Counter(), {}
    missing = sorted(set(required) - set(header))
    duplicate_headers = sorted(k for k, v in Counter(header).items() if v > 1)
    date_index = header.index("기준_날짜") if "기준_날짜" in header else None
    invalid_dates, rows = 0, 0
    for row in reader:
        rows += 1
        counts[len(row)] += 1
        if len(row) not in width_examples:
            width_examples[len(row)] = {"first_field": row[0][:24] if row else "",
                "extra_field_types": ["timestamp_like" if re.fullmatch(r"\d{4}[-/]\d{2}[-/]\d{2}.*", x) else
                                      "numeric_like" if re.fullmatch(r"[+-]?\d+(\.\d+)?", x) else "other"
                                      for x in row[len(header):]], "row_number": rows + 1}
        if date_index is None or len(row) <= date_index or not re.fullmatch(r"\d{8}", row[date_index]):
            invalid_dates += 1
        else:
            dates[row[date_index]] += 1
    invalid_calendar = []
    for value in list(dates):
        try:
            datetime.strptime(value, "%Y%m%d")
        except ValueError:
            invalid_dates += dates.pop(value)
            invalid_calendar.append(value)
    header_ok = not missing and not duplicate_headers
    widths_ok = not rows or set(counts) == {len(header)}
    usable = header_ok and widths_ok and invalid_dates == 0 and rows > 0
    status = ("empty" if not rows else "header_mismatch" if not header_ok else
              "row_width_mismatch" if not widths_ok else "invalid_dates" if invalid_dates else "structurally_usable")
    return {"header": header, "rows": rows, "header_columns": len(header), "row_width_counts": dict(counts),
        "width_examples": width_examples, "missing_required_headers": missing, "duplicate_headers": duplicate_headers,
        "invalid_date_rows": invalid_dates, "invalid_calendar_values": invalid_calendar,
        "dates": dict(sorted(dates.items())), "status": status, "structurally_usable": usable}


def audit_file(entry):
    path = CASE / entry["path"]
    if entry["month"][:4] != "2022" or not path.resolve().is_relative_to((CASE / "data/overnight").resolve()):
        raise ValueError("2022년 보류 원본만 검사할 수 있습니다")
    if sha256(path) != entry["sha256"]:
        raise ValueError("2022년 원본 해시 불일치")
    keys, values, _ = schema(entry["kind"], list(range(24)))
    members = []
    with ZipFile(path) as archive:
        for name in sorted(n for n in archive.namelist() if n.lower().endswith(".csv")):
            with archive.open(name) as stream:
                result = audit_reader(csv.reader(io.TextIOWrapper(stream, encoding="cp949")), keys + values)
            members.append({"member": name, **result})
    print(f"2022 전체 행 형식 점검: {entry['kind']} {entry['month']} {sum(x['rows'] for x in members):,}행", flush=True)
    return {"kind": entry["kind"], "month": entry["month"], "path": entry["path"], "sha256": entry["sha256"], "members": members}


def run():
    source = CASE / "results/overnight/multiyear/held_2022_schema.json"
    entries = json.loads(source.read_text())["files"]
    with ProcessPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(audit_file, entries))
    OUT.mkdir(parents=True, exist_ok=True)
    rows, dates = [], []
    for entry in results:
        for member in entry["members"]:
            tags = {"kind": entry["kind"], "month": entry["month"], "member": member["member"]}
            rows.append({**tags, **{k: member[k] for k in ["rows", "header_columns", "invalid_date_rows", "status", "structurally_usable"]},
                "row_width_counts": json.dumps(member["row_width_counts"], sort_keys=True),
                "missing_required_headers": "|".join(member["missing_required_headers"]),
                "date_count": len(member["dates"]), "first_date": min(member["dates"], default=""), "last_date": max(member["dates"], default="")})
            dates.extend({**tags, "date": datetime.strptime(day, "%Y%m%d").strftime("%Y-%m-%d"), "rows": count,
                          "structurally_usable": member["structurally_usable"]} for day, count in member["dates"].items())
    pd.DataFrame(rows).to_csv(OUT / "members.csv", index=False)
    pd.DataFrame(dates).to_csv(OUT / "source_dates.csv", index=False)
    write_json(OUT / "audit.json", {"completed_at": utcnow(), "code_sha256": sha256(Path(__file__)), "source_manifest_sha256": sha256(source),
        "files": results, "outputs": {name: sha256(OUT / name) for name in ["members.csv", "source_dates.csv"]},
        "scope": "전체 CSV 행의 구조 검사. 알려지지 않은 열을 제거하거나 헤더를 고쳐 분석에 넣지 않음. 구조 적합은 단위·정류장 이력·비교 가능성의 검증이 아님."})
