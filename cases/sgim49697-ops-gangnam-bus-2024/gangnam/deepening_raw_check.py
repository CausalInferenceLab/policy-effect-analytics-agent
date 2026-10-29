"""별도 CSV 순회로 폐선 경계의 원래 기록과 계산 입력을 직접 비교한다."""

from __future__ import annotations

import csv
import io
import json
import math
from collections import defaultdict
from datetime import datetime
from zipfile import ZipFile

import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json

OUT = CASE / "results/deepening/cohort"


def numeric(value):
    if not value.strip():
        return None
    result = float(value)
    if math.isnan(result):
        return None
    if not math.isfinite(result):
        raise ValueError("원본에 무한대 수치")
    return result


def value_status(value):
    return "blank" if value is None else "positive" if value > 0 else "zero" if value == 0 else "negative"


def expected_header(kind):
    if kind == "bus_time":
        return ["기준_날짜", "노선_ID", "출발_정류장_ID", "도착_정류장_ID", "운행시간",
                *[f"운행시간_{h:02}시" for h in range(24)], "출발_정류장_순서", "도착_정류장_순서"]
    if kind == "bus_trips":
        return ["기준_날짜", "노선_ID", "정류장_ID", "버스운행횟수",
                *[f"버스운행횟수_{h:02}시" for h in range(24)], "정류장_순서"]
    raise ValueError("지원하지 않는 원본 종류")


def scan_archive(path, kind, dates, routes, stops):
    """캐시 파서와 독립된 표준 csv.reader로 전체 행 너비·선택 원래 값을 확인한다."""
    records = defaultdict(set)
    audit = {"members": [], "rows_scanned": 0, "selected_rows": 0}
    observed_dates = set()
    wanted = {d.replace("-", "") for d in dates}
    with ZipFile(path) as archive:
        members = sorted(n for n in archive.namelist() if n.lower().endswith(".csv"))
        if not members:
            raise ValueError("CSV가 없는 ZIP")
        for member in members:
            count = 0
            with archive.open(member) as binary:
                reader = csv.reader(io.TextIOWrapper(binary, encoding="cp949"), strict=True)
                header = next(reader, [])
                if header != expected_header(kind):
                    raise ValueError(f"독립 원본 헤더 불일치: {member}")
                for row in reader:
                    if len(row) != len(header):
                        raise ValueError(f"독립 원본 행 너비 오류: {member}, 자료행 {count + 1}")
                    count += 1
                    date, route, stop = row[:3]
                    if len(date) != 8 or not date.isascii() or not date.isdigit() or not date.startswith("2024"):
                        raise ValueError("고정 2024년 원본 날짜 범위 오류")
                    observed_dates.add(date)
                    if date not in wanted or route not in routes or stop not in stops:
                        continue
                    arrival = row[3] if kind == "bus_time" else ""
                    first_hour = 5 if kind == "bus_time" else 4
                    values = tuple(numeric(x) for x in row[first_hour:first_hour + 24])
                    sequence = tuple(row[first_hour + 24:])
                    records[(date, route, stop, arrival)].add((sequence, values))
                    audit["selected_rows"] += 1
            audit["members"].append({"name": member, "rows": count, "width_check": "passed"})
            audit["rows_scanned"] += count
    for date in observed_dates:
        datetime.strptime(date, "%Y%m%d")
    audit["source_dates"] = sorted(observed_dates)
    audit["selected_unique_keys"] = len(records)
    audit["multiple_selected_records"] = sum(len(v) > 1 for v in records.values())
    return records, audit


def lookup(records, key, hour):
    matches = records.get(key, set())
    if not matches:
        return "row_absent", None
    if len(matches) > 1:
        # 재방문/상충 행을 어느 쪽으로도 자동 선택하지 않는다.
        return "multiple_records_quarantined", None
    _, values = next(iter(matches))
    value = values[hour]
    return value_status(value), value


def run():
    cfg = read_yaml("deepening_raw_check_config.yaml")
    if cfg["locked_year"] != 2026 or any(not d.startswith("2024-") for d in cfg["dates"]):
        raise ValueError("독립 원본 확인의 날짜 잠금 오류")
    cohort = json.loads((CASE / cfg["cohort_audit"]).read_text())
    cache = CASE / cohort["grid_path"]
    if sha256(cache) != cohort["grid_sha256"]:
        raise ValueError("비교할 격자 해시 변경")
    routes = pd.read_csv(CASE / cfg["route_selection"], dtype={"route": str})
    routes = set(routes.loc[routes.eligible, "route"])
    stops = {s[k] for s in cfg["segments"] for k in ["stop", "arrival"]}
    manifest = json.loads((CASE / cfg["source_manifest"]).read_text())["files"]
    entries = [e for e in manifest if e.get("month") == cfg["source_month"] and e.get("kind") in cfg["kinds"]]
    if len(entries) != len(cfg["kinds"]) or {e["kind"] for e in entries} != set(cfg["kinds"]):
        raise ValueError("월별 원본 출처 누락/중복")
    scanned, raw = {}, {}
    for entry in entries:
        path = CASE / entry["path"]
        if not path.resolve().is_relative_to((CASE / "data").resolve()) or sha256(path) != entry["sha256"]:
            raise ValueError("독립 대조 원본 경로·해시 불일치")
        raw[entry["kind"]], report = scan_archive(path, entry["kind"], cfg["dates"], routes, stops)
        scanned[entry["kind"]] = {"path": entry["path"], "sha256": entry["sha256"], **report}
        print(f"별도 원본 순회: {entry['kind']} {report['rows_scanned']:,}행", flush=True)
    data = pd.read_parquet(cache, filters=[("date", "in", cfg["dates"])])
    if len(data) != len(cfg["dates"]) * len(routes) * len(cfg["segments"]) * len(cfg["report_hours"]):
        raise ValueError("독립 대조 격자 크기 불일치")
    checks = []
    for row in data.itertuples(index=False):
        for metric, kind, stop, arrival, status, value in [
            ("time", "bus_time", row.stop, row.arrival, row.record_status, row.raw_value),
            ("departure_trips", "bus_trips", row.stop, "", row.departure_status, row.departure_trips),
            ("arrival_trips", "bus_trips", row.arrival, "", row.arrival_status, row.arrival_trips)]:
            date = row.date.replace("-", "")
            raw_status, raw_value = lookup(raw[kind], (date, row.route, stop, arrival), row.hour)
            normalized_status = "row_absent" if raw_status == "multiple_records_quarantined" else raw_status
            if date not in scanned[kind]["source_dates"]:
                normalized_status = "source_date_absent"
            known = raw_value is not None
            match = normalized_status == status and ((not known and pd.isna(value)) or
                    (known and pd.notna(value) and math.isclose(raw_value, value, rel_tol=0, abs_tol=1e-12)))
            checks.append({"date": row.date, "route": row.route, "segment": row.segment, "metric": metric,
                           "hour": row.hour, "raw_status": raw_status, "matched": match})
    checks = pd.DataFrame(checks)
    if not checks.matched.all():
        raise ValueError(f"독립 원본·계산 입력 불일치 {int((~checks.matched).sum())}건")
    summary = checks.groupby(["date", "route", "segment", "metric"]).agg(
        hours_checked=("hour", "size"), matched_hours=("matched", "sum"),
        positive_hours=("raw_status", lambda x: x.eq("positive").sum()),
        blank_hours=("raw_status", lambda x: x.eq("blank").sum()),
        absent_hours=("raw_status", lambda x: x.eq("row_absent").sum()),
        quarantined_hours=("raw_status", lambda x: x.eq("multiple_records_quarantined").sum())).reset_index()
    summary.to_csv(OUT / "raw_retirement_spotcheck.csv", index=False)
    write_json(OUT / "raw_retirement_audit.json", {"completed_at": utcnow(), "configuration": cfg,
        "sources": scanned, "scalar_checks": len(checks), "mismatches": 0,
        "inputs": {name: sha256(CASE / name) for name in ["deepening_raw_check_config.yaml",
                   "gangnam/deepening_raw_check.py", cfg["cohort_audit"], cfg["source_manifest"], cfg["route_selection"]]},
        "output_sha256": sha256(OUT / "raw_retirement_spotcheck.csv")})
    print(f"독립 원본·계산 입력 대조 {len(checks):,}건 통과", flush=True)
