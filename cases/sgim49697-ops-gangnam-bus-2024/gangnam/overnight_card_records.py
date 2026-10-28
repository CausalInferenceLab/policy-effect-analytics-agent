"""정류장 전체 합계의 교차 자료 검증을 통과한 서울 면허 버스 승하차 기록을 분석한다."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .directional import period_dates
from .overnight_card import hour_columns
from .overnight_daily_card_analysis import complete_sum, known_numeric, select_rows
from .overnight_sensitivity import describe_comparison

OUT = CASE / "results/overnight/card_records"
RAW = CASE / "data/overnight/card_records"
FLOWS = {"승차총승객수": "boardings", "하차총승객수": "alightings"}


def station_reconciliation(route):
    """공개 표기를 전역 치환하지 않고 각 자료에 실제 있는 모든 노선 기록을 합친다."""
    keys = ["month", "stop", "flow"]
    totals = []
    for source, absent in [("daily", "right_only"), ("monthly", "left_only")]:
        part = route[route.source_membership.ne(absent)]
        result = part.groupby(keys).agg(
            record_sum=(f"record_sum_{source}", complete_sum),
            route_labels=("route_label", "nunique"),
            exact_duplicate_rows=(f"exact_duplicate_rows_{source}", "sum"),
            source_month_complete=("daily_source_month_complete", "all"))
        totals.append(result.add_suffix("_" + source))
    result = totals[0].join(totals[1], how="outer").reset_index()
    result["difference"] = result.record_sum_daily - result.record_sum_monthly
    result["both_known"] = result.record_sum_daily.notna() & result.record_sum_monthly.notna()
    result["exact_agreement"] = result.both_known & result.difference.eq(0)
    result["quality_pass"] = (result.exact_agreement & result.exact_duplicate_rows_daily.eq(0)
                              & result.exact_duplicate_rows_monthly.eq(0) & result.source_month_complete_daily.eq(True))
    return result


def daily_station_records(selected, reconciliation, stations, months):
    frame = selected[["date", "month", "stop", *FLOWS]].copy()
    frame[list(FLOWS)] = known_numeric(frame[list(FLOWS)])
    frame["date"] = pd.to_datetime(frame.date, format="%Y%m%d", errors="raise").dt.strftime("%Y-%m-%d")
    d = frame.melt(id_vars=["date", "month", "stop"], value_vars=list(FLOWS), var_name="flow", value_name="value")
    d["flow"] = d.flow.map(FLOWS)
    d = d.groupby(["date", "month", "stop", "flow"]).agg(recorded_sum=("value", complete_sum),
                                                            raw_rows=("value", "size"), known_rows=("value", "count")).reset_index()
    dates = [str(x.date()) for month in months for x in pd.date_range(month + "-01", periods=pd.Period(month).days_in_month)]
    grid = pd.MultiIndex.from_product([dates, stations.stop, list(FLOWS.values())], names=["date", "stop", "flow"]).to_frame(index=False)
    grid["month"] = grid.date.str[:7]
    grid = grid.merge(d, on=["date", "month", "stop", "flow"], how="left", validate="one_to_one")
    grid = grid.merge(reconciliation[["month", "stop", "flow", "quality_pass"]], on=["month", "stop", "flow"], how="left", validate="many_to_one")
    grid = grid.merge(stations[["stop", "ars", "group", "name"]], on="stop", validate="many_to_one")
    grid["value"] = grid.recorded_sum.where(grid.quality_pass.eq(True))
    grid["coverage"] = grid.value.notna().astype(float)
    grid["unit_coverage"] = grid.coverage
    grid["index"] = grid.value
    return grid


def group_records(daily, stations, groups):
    expected = stations[stations.group.isin(groups)].groupby("group").size()
    d = daily[daily.group.isin(groups)]
    result = d.groupby(["date", "group", "flow"]).agg(
        observed_stops=("value", "count"), recorded_subtotal=("value", lambda x: x.sum(min_count=1))).reset_index()
    result["expected_stops"] = result.group.map(expected)
    result["coverage"] = result.observed_stops / result.expected_stops
    result["unit_coverage"] = result.coverage
    result["index"] = result.recorded_subtotal.where(result.observed_stops.eq(result.expected_stops))
    return result


def monthly_hours(cfg, reconciliation, stations):
    entries = [e for e in json.loads((CASE / cfg["monthly_manifest"]).read_text())["files"] if e["kind"] == "card"]
    months = set(reconciliation.month)
    parts = []
    for entry in entries:
        if entry["month"] not in months:
            continue
        path = CASE / entry["path"]
        if sha256(path) != entry["sha256"]:
            raise ValueError("월 카드 원본 해시 변경")
        frame, audit = select_rows(path, "cp949", entry["month"], False, set(stations.stop))
        if audit["exact_duplicate_extra_rows"]:
            raise ValueError("월 카드에 새 정확 중복이 있습니다")
        columns = hour_columns(frame.columns)
        reverse = {column: (hour, flow) for (hour, flow), column in columns.items()}
        frame[list(reverse)] = known_numeric(frame[list(reverse)])
        d = frame.melt(id_vars=["month", "stop"], value_vars=list(reverse), var_name="column", value_name="value")
        d["hour"] = d.column.map({c: pair[0] for c, pair in reverse.items()})
        d["flow"] = d.column.map({c: pair[1] for c, pair in reverse.items()})
        parts.append(d.groupby(["month", "stop", "hour", "flow"]).value.agg(complete_sum).reset_index())
    data = pd.concat(parts, ignore_index=True)
    data = data.merge(reconciliation[["month", "stop", "flow", "quality_pass"]], on=["month", "stop", "flow"], how="left", validate="many_to_one")
    data["value"] = data.value.where(data.quality_pass.eq(True))
    data = data.merge(stations[["stop", "group"]], on="stop", validate="many_to_one")
    expected = stations[stations.group.isin(cfg["groups"])].groupby("group").size()
    group = data[data.group.isin(cfg["groups"])].groupby(["month", "group", "hour", "flow"]).agg(
        value=("value", complete_sum), observed_stops=("value", "count")).reset_index()
    group["expected_stops"] = group.group.map(expected)
    group["value"] = group.value.where(group.observed_stops.eq(group.expected_stops))
    group["calendar_days"] = group.month.map(lambda m: pd.Period(m).days_in_month)
    group["per_calendar_day"] = group.value / group.calendar_days
    return group


def monthly_comparisons(hourly, cfg):
    specs = cfg["monthly_hours"]
    bands = {"all_day": list(range(24)), **read_yaml(specs["bands_from"])["bus_exploration"]["bands"]}
    summaries, comparisons = [], []
    for band, hours in bands.items():
        d = hourly[hourly.hour.isin(hours)].groupby(["month", "group", "flow"]).agg(
            record_sum=("value", complete_sum), known_hours=("value", "count"), calendar_days=("calendar_days", "first")).reset_index()
        d["record_sum"] = d.record_sum.where(d.known_hours.eq(len(hours)))
        d["per_calendar_day"] = d.record_sum / d.calendar_days
        d["band"] = band
        summaries.append(d)
        for (group, flow), part in d.groupby(["group", "flow"]):
            for year in [2023, 2024]:
                pre = [f"{year}-{m}" for m in specs["reference_months"]]
                for period in ["summer", "autumn"]:
                    post = [f"{year}-{m}" for m in specs[f"{period}_months"]]
                    a, b = part[part.month.isin(pre)], part[part.month.isin(post)]
                    good = len(a) == len(pre) and len(b) == len(post) and a.record_sum.notna().all() and b.record_sum.notna().all()
                    before = a.record_sum.sum() / a.calendar_days.sum() if good else np.nan
                    after = b.record_sum.sum() / b.calendar_days.sum() if good else np.nan
                    comparisons.append({"band": band, "group": group, "flow": flow, "year": year, "comparison": period,
                                        "before_per_calendar_day": before, "after_per_calendar_day": after,
                                        "change_pct": 100 * (after / before - 1) if before > 0 else np.nan,
                                        "quality_pass": bool(good), "before_months": ";".join(pre), "after_months": ";".join(post)})
    return pd.concat(summaries, ignore_index=True), pd.DataFrame(comparisons)


def run():
    cfg = read_yaml("overnight_card_records_config.yaml")
    audit_path = CASE / cfg["source_audit"]
    source = json.loads(audit_path.read_text())
    cache = CASE / source["selected_path"]
    if sha256(cache) != source["selected_sha256"]:
        raise ValueError("일별 카드 선택 캐시 해시 변경")
    route_path = CASE / cfg["route_label_audit"]
    if sha256(route_path) != source["outputs"][route_path.name]:
        raise ValueError("노선 표기 단위 대조 표 해시 변경")
    routes = pd.read_csv(route_path, dtype={"stop": str, "route_label": str})
    reconciled = station_reconciliation(routes)
    stations = pd.read_csv(CASE / cfg["identity"], dtype={"stop": str, "ars": str})
    months = sorted(reconciled.month.unique())
    daily = daily_station_records(pd.read_parquet(cache), reconciled, stations, months)
    groups = group_records(daily, stations, cfg["groups"])
    base = read_yaml(cfg["base_config"])
    base.update(minimum_days=cfg["minimum_days"], maximum_coverage_gap=cfg["maximum_coverage_gap"])
    periods = period_dates(base)
    comparisons = []
    windows = [("summer2023", "pre2023", "post2023"), ("summer2024", "pre2024", "post2024"), ("autumn2024", "pre2024", "autumn2024")]
    for scope, frame, keys in [("direction", groups, ["group", "flow"]), ("station", daily, ["group", "stop", "flow"])]:
        for ids, part in frame.groupby(keys):
            labels = dict(zip(keys, ids, strict=True))
            for name, pre, post in windows:
                result = describe_comparison(part, periods[pre], periods[post], base, interval=scope == "direction")
                comparisons.append({"scope": scope, **labels, "comparison": name, **result})
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    reconciled.merge(stations[["stop", "ars", "group", "name"]], on="stop", validate="many_to_one").to_csv(OUT / "station_month_reconciliation.csv", index=False)
    pd.DataFrame(comparisons).to_csv(OUT / "daily_comparisons.csv", index=False)
    groups.to_csv(OUT / "daily_direction.csv", index=False)
    daily.to_parquet(RAW / "daily_station.parquet", index=False)
    hourly = monthly_hours(cfg, reconciled, stations)
    hourly.to_csv(OUT / "monthly_hourly.csv", index=False)
    monthly, month_comparisons = monthly_comparisons(hourly, cfg)
    monthly.to_csv(OUT / "monthly_bands.csv", index=False)
    month_comparisons.to_csv(OUT / "monthly_comparisons.csv", index=False)
    write_json(OUT / "audit.json", {"completed_at": utcnow(), "code_sha256": sha256(Path(__file__)),
                                   "config_sha256": sha256(CASE / "overnight_card_records_config.yaml"),
                                   "source_audit_sha256": sha256(audit_path), "source_selected_sha256": source["selected_sha256"],
                                   "route_reconciliation_sha256": sha256(route_path),
                                   "monthly_manifest_sha256": sha256(CASE / cfg["monthly_manifest"]),
                                   "identity_sha256": sha256(CASE / cfg["identity"]), "period_dates": periods,
                                   "station_month_flow_keys": len(reconciled), "exact_station_agreement": int(reconciled.exact_agreement.sum()),
                                   "station_quality_pass": int(reconciled.quality_pass.sum()),
                                   "daily_station_path": str((RAW / "daily_station.parquet").relative_to(CASE)),
                                   "daily_station_sha256": sha256(RAW / "daily_station.parquet"),
                                   "outputs": {p.name: sha256(p) for p in OUT.glob("*.csv")}, "interpretation": cfg["interpretation"]})
    print(f"정류장·월·승하차 {len(reconciled)}개 중 정확 일치 {int(reconciled.exact_agreement.sum())}개", flush=True)
