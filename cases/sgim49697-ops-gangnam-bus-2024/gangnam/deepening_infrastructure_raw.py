"""2025년 개통 경계의 정류소별 운행횟수 원본을 별도 스트리밍으로 확인한다."""

import csv
import io
import json
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from zipfile import ZipFile

import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .deepening_infrastructure import OUT, verify, verify_committed
from .deepening_raw_check import expected_header, numeric, value_status

CONFIG = "deepening_infrastructure_raw_config.yaml"


def scan(job):
    entry, wanted, routes, nodes = job
    path = CASE / entry["path"]
    if not path.resolve().is_relative_to((CASE / "data").resolve()) or sha256(path) != entry["sha256"]:
        raise ValueError("정류소 운행 원본 경로·해시 변경")
    selected, observed, members = defaultdict(set), set(), []
    selected_rows = 0
    with ZipFile(path) as archive:
        files = sorted(name for name in archive.namelist() if name.lower().endswith(".csv"))
        if not files:
            raise ValueError("운행 원본 ZIP에 CSV가 없습니다")
        for name in files:
            rows = 0
            with archive.open(name) as binary:
                reader = csv.reader(io.TextIOWrapper(binary, encoding="cp949"), strict=True)
                header = next(reader, [])
                if header != expected_header("bus_trips"):
                    raise ValueError("운행 원본 헤더 변경: " + name)
                for row in reader:
                    rows += 1
                    if len(row) != len(header):
                        raise ValueError(f"운행 원본 행 너비 오류: {name}, {rows}")
                    day, route, node = row[:3]
                    if len(day) != 8 or not day.isascii() or not day.isdigit() or int(day[:4]) not in [2024, 2025]:
                        raise ValueError("운행 원본 날짜·잠금 오류")
                    observed.add(day)
                    if day in wanted and route in routes and node in nodes:
                        # 일 합계와 24시간, 순서도 함께 비교해 상충 값을 숨기지 않는다.
                        values = tuple(numeric(value) for value in row[3:28])
                        selected[(day, route, node)].add((row[28], values))
                        selected_rows += 1
            members.append(dict(name=name, rows=rows))
            print(f"운행 경계 원본 {entry['month']} {name}: {rows:,}행", flush=True)
    for day in observed:
        datetime.strptime(day, "%Y%m%d")
    return selected, dict(path=entry["path"], sha256=entry["sha256"], month=entry["month"], members=members,
                          rows_scanned=sum(row["rows"] for row in members), selected_rows=selected_rows, source_dates=sorted(observed))


def summarize(records, source_present):
    if not source_present:
        return dict(record_state="source_date_absent", positive_hours=0, zero_hours=0, blank_hours=0,
                    negative_hours=0, unavailable_hours=24, daily_value=None, daily_hour_sum_equal=None)
    if len(records) != 1:
        return dict(record_state="row_absent" if not records else "multiple_records_quarantined",
                    positive_hours=0, zero_hours=0, blank_hours=0, negative_hours=0, unavailable_hours=24,
                    daily_value=None, daily_hour_sum_equal=None)
    _, values = next(iter(records))
    counts = Counter(value_status(value) for value in values[1:])
    if len(values) != 25:
        raise ValueError("일 합계와 24개 시간값이 필요합니다")
    complete = all(value is not None and value >= 0 for value in values)
    return dict(record_state="unique_record", **{key + "_hours": counts[key] for key in ["positive", "zero", "blank", "negative"]},
                unavailable_hours=0, daily_value=values[0], daily_hour_sum_equal=(abs(values[0] - sum(values[1:])) < 1e-8) if complete else None)


def run():
    _, _ = verify()
    cfg = read_yaml(CONFIG)
    verify_committed(CASE / CONFIG)
    if cfg["locked_year"] != 2026 or cfg["months"] != ["2025-01", "2025-02"] or cfg["workers"] not in [1, 2]:
        raise ValueError("운행 경계 원본 범위·작업자 설정 변경")
    if cfg["window"] != ["2025-01-01", "2025-02-07"]:
        raise ValueError("결과 확인 전에 고정한 운행 경계 변경")
    for path in [OUT / "route_groups.csv", OUT / "stop_history.csv", OUT / "history_audit.json"]:
        verify_committed(path)
    history_audit = json.loads((OUT / "history_audit.json").read_text())
    if sha256(CASE / cfg["stop_history"]) != history_audit["outputs"]["stop_history.csv"]:
        raise ValueError("운행 경계 정류소 키의 역사 목록 변경")
    history = pd.read_csv(CASE / cfg["stop_history"], dtype=str, keep_default_na=False)
    matched = history[history.match_status.eq("matched") & history.target_ars.isin(cfg["historical_stop_ars"])]
    if set(matched.target_ars) != set(cfg["historical_stop_ars"]) or matched.groupby("target_ars").node.nunique().ne(1).any():
        raise ValueError("목표 ARS와 역사 ID의 누락·복수 대응")
    nodes = matched[["target_ars", "node"]].drop_duplicates().sort_values("target_ars")
    memberships = pd.read_csv(CASE / cfg["route_selection"], dtype=str)
    manifest = json.loads((CASE / cfg["source_manifest"]).read_text())["files"]
    sources = [row for row in manifest if row.get("kind") == cfg["kind"] and row.get("month") in cfg["months"]]
    if len(sources) != 2 or {row["month"] for row in sources} != set(cfg["months"]):
        raise ValueError("운행 경계 원본 출처 누락·중복")
    dates = pd.date_range(*cfg["window"]).strftime("%Y%m%d").tolist()
    jobs = [(entry, set(dates), set(memberships.route), set(nodes.node)) for entry in sources]
    with ProcessPoolExecutor(max_workers=cfg["workers"]) as pool:
        results = list(pool.map(scan, jobs))
    combined, observed = defaultdict(set), set()
    for records, source in results:
        observed.update(source["source_dates"])
        for key, values in records.items():
            combined[key].update(values)
    output = []
    for day in dates:
        for route in memberships.itertuples(index=False):
            for node in nodes.itertuples(index=False):
                state = summarize(combined.get((day, route.route, node.node), set()), day in observed)
                output.append(dict(date=datetime.strptime(day, "%Y%m%d").date().isoformat(), route=route.route,
                    route_name=route.route_name, group=route.group, ars=node.target_ars, node=node.node, **state))
    daily = pd.DataFrame(output)
    daily.to_csv(OUT / "trip_support_daily.csv", index=False, lineterminator="\n")
    summaries = []
    for (route, name, group, ars, node), part in daily.groupby(["route", "route_name", "group", "ars", "node"]):
        positive = part[part.positive_hours.gt(0)]
        summaries.append(dict(route=route, route_name=name, group=group, ars=ars, node=node,
            expected_days=len(part), unique_record_days=int(part.record_state.eq("unique_record").sum()),
            positive_record_days=len(positive), first_positive_date=positive.date.min() if len(positive) else "",
            last_positive_date=positive.date.max() if len(positive) else "",
            source_absent_days=int(part.record_state.eq("source_date_absent").sum()),
            quarantined_days=int(part.record_state.eq("multiple_records_quarantined").sum())))
    pd.DataFrame(summaries).to_csv(OUT / "trip_support_summary.csv", index=False, lineterminator="\n")
    write_json(OUT / "trip_support_audit.json", dict(completed_at=utcnow(), configuration=cfg, code_sha256=sha256(__file__),
        inputs={name: sha256(CASE / name) for name in [CONFIG, cfg["source_manifest"], cfg["route_selection"], cfg["stop_history"], "gangnam/deepening_raw_check.py"]},
        sources=[source for _, source in results], expected_route_stop_days=len(daily),
        complete_sum_checks=int(daily.daily_hour_sum_equal.notna().sum()), failed_sum_checks=int(daily.daily_hour_sum_equal.eq(False).sum()),
        record_states=daily.record_state.value_counts().to_dict(),
        selected_input_rows=sum(source["selected_rows"] for _, source in results),
        unique_selected_records=sum(len(values) for values in combined.values()),
        outputs={name: sha256(OUT / name) for name in ["trip_support_daily.csv", "trip_support_summary.csv"]}))
    print(f"개통 경계 운행 기록 {len(daily):,}개 노선·정류소·날짜 확인", flush=True)
