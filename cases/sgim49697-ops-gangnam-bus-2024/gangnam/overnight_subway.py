"""주변 8개 역의 일별·월 시간대 승하차를 대조하고 고정 기간의 수요 맥락을 비교한다."""

import csv
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .directional import holiday_set
from .overnight_persistence import periods
from .overnight_sensitivity import describe_comparison
from .overnight_subway_data import MANIFEST, OUT, RAW, normalized_row, verify

FLOWS = ["boardings", "alightings"]


def base_name(name):
    """끝의 괄호 부역명 한 개만 제거하며 중간 괄호·문자·호선은 추정하지 않는다."""
    return re.sub(r"\([^()]*\)$", "", name.strip()).strip()


def count(value):
    if value == "":
        return np.nan
    if not re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)", value):
        raise ValueError("지하철 승하차 값이 비음수 정수가 아닙니다")
    return int(value.replace(",", ""))


def selected_rows(path, validation, kind, stations):
    """호선·기본역명이 유일한 행만 선택하며 같은 키의 별칭·중복은 합산하지 않는다."""
    lookup = {(s["line"], s["base_name"]): s["key"] for s in stations}
    if len(lookup) != len(stations) or len({s["key"] for s in stations}) != len(stations):
        raise ValueError("지하철 선택 역의 호선·이름·식별자 중복")
    records, names, seen = [], {}, set()
    spec = validation["columns"]
    with path.open(encoding=validation["encoding"], newline="") as stream:
        reader = csv.reader(stream)
        header = next(reader)
        if header != validation["header"]:
            raise ValueError("지하철 검증 이후 헤더 변경")
        for raw in reader:
            row = dict(zip(header, normalized_row(raw, header)[0], strict=True))
            line, name = row[spec["line"]], row[spec["station_name"]]
            station = lookup.get((line, base_name(name)))
            if station is None:
                continue
            period = row[spec["period"]]
            key = period, station
            if key in seen:
                raise ValueError("동일 날짜/월·호선·기본역명의 지하철 행 중복")
            seen.add(key)
            month = period[:4] + "-" + period[4:6]
            names.setdefault((month, station), set()).add(name)
            labels = {"month": month, "station": station, "source_name": name, "row_present": True}
            if kind == "daily":
                date = month + "-" + period[6:8]
                records.extend({**labels, "date": date, "flow": flow, "value": count(row[spec[flow]])} for flow in FLOWS)
            else:
                for field, column in spec["hours"].items():
                    hour, flow = field.split("_", 1)
                    records.append({**labels, "hour": int(hour), "flow": flow, "value": count(row[column])})
    identity = [{"month": month, "station": station, "source_names": " | ".join(sorted(values)), "kind": kind}
                for (month, station), values in names.items()]
    return pd.DataFrame(records), pd.DataFrame(identity)


def complete_grid(records, stations, months, kind):
    """예정 날짜·시간과 모든 역을 분모에 남기고 관측 0과 행 부재·빈 값을 구분한다."""
    if kind == "daily":
        dates = [str(day.date()) for month in months for day in pd.date_range(month + "-01", periods=pd.Period(month).days_in_month)]
        keys, values = ["date", "station", "flow"], [dates, stations, FLOWS]
    else:
        keys, values = ["month", "station", "hour", "flow"], [months, stations, list(range(24)), FLOWS]
    if records.duplicated(keys).any():
        raise ValueError("지하철 선택 기록 키 중복")
    grid = pd.MultiIndex.from_product(values, names=keys)
    result = records.set_index(keys).reindex(grid).reset_index()
    result["row_present"] = result.row_present.eq(True)
    if kind == "daily":
        result["month"] = result.date.str[:7]
        result["index"] = result.value
        result["coverage"] = result.value.notna().astype(float)
        result["unit_coverage"] = result.coverage
    result["record_status"] = np.select([~result.row_present, result.value.isna(), result.value.eq(0)],
                                         ["row_absent", "blank", "zero"], default="positive")
    return result


def reconciliation(daily, hourly):
    keys = ["month", "station", "flow"]
    a = daily.groupby(keys).agg(daily_sum=("value", lambda s: s.sum(min_count=1)), daily_known_days=("value", "count"),
                                expected_days=("date", "size"))
    b = hourly.groupby(keys).agg(hourly_sum=("value", lambda s: s.sum(min_count=1)), hourly_known_hours=("value", "count"))
    result = a.join(b, how="outer", validate="one_to_one").reset_index()
    result["complete"] = result.daily_known_days.eq(result.expected_days) & result.hourly_known_hours.eq(24)
    result["difference"] = (result.hourly_sum - result.daily_sum).where(result.complete)
    result["quality_pass"] = result.complete & result.difference.eq(0)
    result["status"] = np.select([~result.complete, result.difference.ne(0)], ["incomplete", "different"], default="exact")
    return result


def calendar(cfg):
    original = periods(read_yaml("overnight_persistence_config.yaml"))
    closed = holiday_set(read_yaml("directional_config.yaml"))
    result = {}
    for year in cfg["years"]:
        for label, (start, end) in cfg["daily_periods"].items():
            name = f"{label}{year}"
            if year in [2024, 2025]:
                # 동일 창의 기존 공휴일 대조를 재사용하며 원본 날짜 부재를 분모에서 제외하지 않는다.
                expected = (f"{year}-{start}", f"{year}-{end}")
                if tuple(read_yaml("overnight_persistence_config.yaml")["periods"][name]) != expected:
                    raise ValueError("지하철 창과 기존 버스 지속성 창이 다릅니다")
                result[name] = original[name]
            else:
                result[name] = [str(d.date()) for d in pd.date_range(f"{year}-{start}", f"{year}-{end}")
                                if d.dayofweek < 5 and str(d.date()) not in closed]
    return result


def daily_comparisons(daily, dates, cfg):
    results = []
    for (station, flow), frame in daily.groupby(["station", "flow"]):
        for name, (before, after) in cfg["daily_comparisons"].items():
            row = describe_comparison(frame, dates[before], dates[after], cfg, interval=True)
            row["quality_pass"] = bool(row["quality_pass"] and row["before_coverage"] >= cfg["minimum_daily_coverage"]
                                       and row["after_coverage"] >= cfg["minimum_daily_coverage"])
            results.append({"station": station, "flow": flow, "comparison": name, **row})
    return pd.DataFrame(results)


def monthly_changes(hourly, cfg):
    results = []
    for band, hours in {"all_day": list(range(24)), **cfg["monthly_bands"]}.items():
        expected_hours = len(hours)
        grouped = hourly[hourly.hour.isin(hours)].groupby(["station", "flow", "month"]).agg(
            total=("value", lambda s, n=expected_hours: s.sum(min_count=n)), known_hours=("value", "count"))
        for (station, flow), frame in grouped.groupby(level=["station", "flow"]):
            frame = frame.droplevel(["station", "flow"])
            for year in cfg["years"][1:]:
                for month in cfg["months_of_year"]:
                    before, after = f"{year - 1}-{month:02}", f"{year}-{month:02}"
                    a, b = frame.loc[before], frame.loc[after]
                    av, bv = a.total / pd.Period(before).days_in_month, b.total / pd.Period(after).days_in_month
                    passed = bool(a.known_hours == len(hours) and b.known_hours == len(hours))
                    results.append({"station": station, "flow": flow, "band": band, "before_month": before, "after_month": after,
                                    "before_per_calendar_day": av, "after_per_calendar_day": bv,
                                    "change_pct": 100 * (bv / av - 1) if av > 0 else np.nan, "quality_pass": passed})
    return pd.DataFrame(results)


def run():
    cfg = read_yaml("overnight_subway_config.yaml")
    months = [f"{year}-{month:02}" for year in cfg["years"] for month in cfg["months_of_year"]]
    if cfg["locked_year"] != 2026 or cfg["years"] != [2023, 2024, 2025] or len(set(months)) != len(months):
        raise ValueError("지하철 분석의 연도·월 범위 오류")
    manifest = json.loads(MANIFEST.read_text())
    if manifest["config_sha256"] != sha256(CASE / "overnight_subway_config.yaml"):
        raise ValueError("지하철 수집 이후 설정 변경")
    entries = manifest["files"]
    expected = {(kind, month) for kind in cfg["datasets"] for month in months}
    if len(entries) != len(expected) or {(e["kind"], e["month"]) for e in entries} != expected:
        raise ValueError("지하철 분석의 필수 월·종류 누락 또는 중복")
    frames, identities = {"daily": [], "hourly_month": []}, []
    for entry in entries:
        path = verify(entry)
        selected, identity = selected_rows(path, entry["validation"], entry["kind"], cfg["stations"])
        if selected.empty:
            raise ValueError("지하철 파일에 선택 역의 기록이 없습니다")
        frames[entry["kind"]].append(selected)
        identities.append(identity)
    stations = [s["key"] for s in cfg["stations"]]
    daily = complete_grid(pd.concat(frames["daily"], ignore_index=True), stations, months, "daily")
    hourly = complete_grid(pd.concat(frames["hourly_month"], ignore_index=True), stations, months, "hourly_month")
    identity = pd.concat(identities, ignore_index=True).set_index(["kind", "month", "station"]).reindex(
        pd.MultiIndex.from_product([cfg["datasets"], months, stations], names=["kind", "month", "station"])).reset_index()
    identity["observed"] = identity.source_names.notna()
    dates = calendar(cfg)
    reconciled = reconciliation(daily, hourly)
    comparisons = daily_comparisons(daily, dates, cfg)
    monthly = monthly_changes(hourly, cfg)
    states = pd.concat([daily.assign(kind="daily"), hourly.assign(kind="hourly_month")], ignore_index=True).groupby(
        ["kind", "month", "station", "flow", "record_status"]).size().rename("rows").reset_index()
    OUT.mkdir(parents=True, exist_ok=True)
    tables = {"identity.csv": identity, "reconciliation.csv": reconciled, "daily_comparisons.csv": comparisons,
              "monthly_changes.csv": monthly, "record_states.csv": states, "monthly_hourly.csv": hourly}
    for name, frame in tables.items():
        frame.to_csv(OUT / name, index=False)
    daily.to_parquet(RAW / "daily_selected.parquet", index=False)
    inputs = [MANIFEST, CASE / "overnight_subway_config.yaml", CASE / "overnight_persistence_config.yaml",
              CASE / "directional_config.yaml", CASE / "data_contract.yaml", CASE / "gangnam/overnight_subway_data.py",
              CASE / "gangnam/overnight_persistence.py", CASE / "gangnam/directional.py", CASE / "gangnam/overnight_sensitivity.py"]
    write_json(OUT / "audit.json", {"completed_at": utcnow(), "configuration": cfg, "calendar": dates,
                                   "code_sha256": sha256(Path(__file__)), "inputs": {str(p.relative_to(CASE)): sha256(p) for p in inputs},
                                   "raw_files": len(entries), "raw_bytes": sum(e["bytes"] for e in entries),
                                   "raw_rows": {kind: sum(e["validation"]["rows"] for e in entries if e["kind"] == kind) for kind in frames},
                                   "observed_lines": {kind: sorted(set().union(*(e["validation"]["observed_lines"] for e in entries if e["kind"] == kind))) for kind in frames},
                                   "source_names_observed": int(identity.observed.sum()), "expected_identity_pairs": len(identity),
                                   "reconciliation_status": reconciled.status.value_counts().to_dict(),
                                   "daily_comparisons": len(comparisons), "daily_quality_pass": int(comparisons.quality_pass.sum()),
                                   "monthly_comparisons": len(monthly), "monthly_quality_pass": int(monthly.quality_pass.sum()),
                                   "daily_selected_path": str((RAW / "daily_selected.parquet").relative_to(CASE)),
                                   "daily_selected_sha256": sha256(RAW / "daily_selected.parquet"),
                                   "outputs": {name: sha256(OUT / name) for name in tables},
                                   "interval": "주 재표집 기술적 변동 구간. 다중 탐색 보정·인과 효과·공식 불확실성 보장이 아님",
                                   "interpretation": cfg["interpretation"]})
    print(f"지하철 맥락: 합계 대조 {reconciled.status.value_counts().to_dict()}, 일별 {len(comparisons)}개·월별 {len(monthly)}개 비교", flush=True)
