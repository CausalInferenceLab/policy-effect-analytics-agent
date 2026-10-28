"""일별·월별 카드의 명시적 기록 합계와 이름 변형을 같은 노선표기·정류장에서 대조한다."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .overnight_card import IDS, REGISTRY, RENAMES, hour_columns
from .overnight_daily_card_data import HEADERS, locations, verify


def select_rows(path, encoding, month, daily, stops):
    days = {d.strftime("%Y%m%d") for d in pd.date_range(month + "-01", periods=pd.Period(month).days_in_month)}
    expected_dates = days if daily else {month.replace("-", "")}
    selected, dates, rows = [], Counter(), 0
    with path.open(encoding=encoding, newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        if (daily and header != HEADERS) or (not daily and header[:6] != IDS):
            raise ValueError("일별·월별 카드의 식별 열이 다릅니다")
        if not daily:
            hour_columns(header)
        for row in reader:
            rows += 1
            if len(row) != len(header) or row[0] not in expected_dates:
                raise ValueError(f"카드 행 너비·날짜 오류: {month} {rows}")
            dates[row[0]] += 1
            if row[3] in stops:
                selected.append(row)
    frame = pd.DataFrame(selected, columns=header)
    exact = frame.duplicated(keep=False)
    extra = int(frame.duplicated().sum())
    frame = frame.rename(columns={**RENAMES, "사용일자": "date"})
    frame["month"] = month
    frame["exact_duplicate"] = exact
    return frame, {"month": month, "source_type": "daily" if daily else "monthly", "rows_scanned": rows,
                   "selected_rows": len(frame), "exact_duplicate_extra_rows": extra,
                   "source_dates": sorted(dates), "source_missing_dates": sorted(expected_dates - set(dates)),
                   "source_date_rows": dict(sorted(dates.items()))}


def known_numeric(frame):
    values = frame.replace("", np.nan).apply(pd.to_numeric, errors="raise")
    if np.isinf(values.to_numpy()).any() or values.stack().mod(1).ne(0).any():
        raise ValueError("카드 인원에 비유한 값·소수가 있습니다")
    return values.where(values.ge(0))


def complete_sum(values):
    return values.sum(min_count=1) if len(values) and values.notna().all() else np.nan


def record_totals(frame, daily):
    parts = []
    hours = hour_columns(frame.columns) if not daily else None
    key = ["month", "route_label", "stop"]
    repeated_key = ["date", "route_label", "stop"] if daily else key
    ambiguous = frame.duplicated(repeated_key, keep=False)
    for flow, label in [("boardings", "승차총승객수"), ("alightings", "하차총승객수")]:
        columns = [label] if daily else [hours[(h, flow)] for h in range(24)]
        values = known_numeric(frame[columns])
        row_total = values.sum(axis=1, min_count=len(columns))
        part = frame[[*key, "route_name", "stop_name", "exact_duplicate"]].copy()
        part["value"] = row_total
        part["ambiguous_key"] = ambiguous
        part["date"] = frame.date if daily else frame.month
        part["flow"] = flow
        parts.append(part)
    d = pd.concat(parts, ignore_index=True)
    result = d.groupby([*key, "flow"]).agg(record_sum=("value", complete_sum),
                                           observed_subtotal=("value", lambda x: x.sum(min_count=1)),
                                           rows=("value", "size"), known_rows=("value", "count"),
                                           observed_dates=("date", "nunique"), exact_duplicate_rows=("exact_duplicate", "sum"),
                                           ambiguous_key_rows=("ambiguous_key", "sum"),
                                           route_name_variants=("route_name", "nunique"), stop_name_variants=("stop_name", "nunique")).reset_index()
    return result


def match_totals(daily, monthly):
    keys = ["month", "route_label", "stop", "flow"]
    result = daily.merge(monthly, on=keys, how="outer", suffixes=("_daily", "_monthly"), indicator=True, validate="one_to_one")
    result["difference_daily_minus_monthly"] = result.record_sum_daily - result.record_sum_monthly
    result["absolute_difference"] = result.difference_daily_minus_monthly.abs()
    result["relative_difference_pct"] = 100 * result.difference_daily_minus_monthly / result.record_sum_monthly.replace(0, np.nan)
    result["both_known"] = result.record_sum_daily.notna() & result.record_sum_monthly.notna()
    result["exact_agreement"] = result.both_known & result.difference_daily_minus_monthly.eq(0)
    result["both_without_exact_duplicates"] = result.exact_duplicate_rows_daily.eq(0) & result.exact_duplicate_rows_monthly.eq(0)
    return result.rename(columns={"_merge": "source_membership"})


def run(phase="probe"):
    config_name, manifest, raw, out = locations(phase)
    cfg = read_yaml(config_name)
    sources = json.loads(manifest.read_text())["files"]
    if {e["month"] for e in sources} != set(cfg["months"]):
        raise ValueError("일별 카드 수집 범위가 설정과 다릅니다")
    monthly = {x["month"]: x for x in json.loads((CASE / cfg["monthly_reference"]).read_text())["files"] if x["kind"] == "card"}
    stations = pd.read_csv(REGISTRY, dtype={"stop": str, "ars": str})
    stops = set(stations.stop)
    out.mkdir(parents=True, exist_ok=True)
    raw.mkdir(parents=True, exist_ok=True)
    selected, audits, comparisons, variants = [], [], [], []
    for entry in sources:
        month = entry["month"]
        daily_path = verify(entry)
        old = monthly[month]
        monthly_path = CASE / old["path"]
        if sha256(monthly_path) != old["sha256"]:
            raise ValueError("월별 카드 원본 해시 불일치")
        daily_frame, daily_audit = select_rows(daily_path, entry["encoding"], month, True, stops)
        monthly_frame, monthly_audit = select_rows(monthly_path, "cp949", month, False, stops)
        for frame, audit, e, is_daily in [(daily_frame, daily_audit, entry, True), (monthly_frame, monthly_audit, old, False)]:
            audit.update(source_path=e["path"], source_sha256=e["sha256"])
            audits.append(audit)
            names = frame.groupby(["month", "route_label", "stop", "route_name", "stop_name"]).size().rename("records").reset_index()
            variants.append(names.assign(source_type="daily" if is_daily else "monthly"))
        compared = match_totals(record_totals(daily_frame, True), record_totals(monthly_frame, False))
        compared["daily_source_month_complete"] = not daily_audit["source_missing_dates"]
        comparisons.append(compared)
        selected.append(daily_frame)
        print(f"일별·월별 카드 대조: {month} {len(daily_frame):,}행 / 월별 {len(monthly_frame):,}행", flush=True)
    cache = raw / "selected_daily.parquet"
    pd.concat(selected, ignore_index=True).to_parquet(cache, index=False)
    data = pd.concat(comparisons, ignore_index=True).merge(stations[["stop", "ars", "group"]], on="stop", validate="many_to_one")
    data.to_csv(out / "monthly_reconciliation.csv", index=False)
    pd.concat(variants, ignore_index=True).to_csv(out / "name_variants.csv", index=False)
    summary = data.groupby(["month", "group", "flow"]).agg(keys=("route_label", "size"), both_known=("both_known", "sum"),
                                                            exact_agreement=("exact_agreement", "sum"),
                                                            daily_record_sum=("record_sum_daily", complete_sum),
                                                            monthly_record_sum=("record_sum_monthly", complete_sum),
                                                            total_absolute_difference=("absolute_difference", complete_sum)).reset_index()
    summary.to_csv(out / "reconciliation_summary.csv", index=False)
    write_json(out / "audit.json", {"completed_at": utcnow(), "phase": phase, "code_sha256": sha256(Path(__file__)),
                                   "source_manifest_sha256": sha256(manifest),
                                   "monthly_manifest_sha256": sha256(CASE / cfg["monthly_reference"]),
                                   "config_sha256": sha256(CASE / config_name),
                                   "files": audits, "selected_path": str(cache.relative_to(CASE)), "selected_sha256": sha256(cache),
                                   "outputs": {p.name: sha256(p) for p in out.glob("*.csv")},
                                   "scope": "명시적 기록 합계 대조이며 승객의 고유성·월중 이름 변형의 배타성을 단독으로 입증하지 않음. 중복 키를 지우지 않고 별도 표시."})
