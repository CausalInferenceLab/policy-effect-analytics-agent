"""고정 중앙 정류장의 일별·월별 카드 합계를 검증한 뒤 2025년 지속성을 비교한다."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .overnight_card_records import (
    daily_station_records,
    group_records,
    monthly_hours,
    station_reconciliation,
)
from .overnight_daily_card_analysis import complete_sum, select_rows
from .overnight_persistence import periods
from .overnight_sensitivity import describe_comparison

OUT = CASE / "results/overnight/card_persistence"
RAW = CASE / "data/overnight/card_persistence"


def identity_rows(frame, stations, months, source):
    """예정된 모든 정류장·월의 실제 ID·ARS를 검사하며 부재도 통과시키지 않는다."""
    observed = frame.groupby(["month", "stop"]).ars.agg(lambda s: tuple(sorted(set(s)))).rename("observed_ars")
    expected = pd.MultiIndex.from_product([months, stations.stop], names=["month", "stop"])
    result = observed.reindex(expected).reset_index().merge(stations[["stop", "ars"]], on="stop", validate="many_to_one")
    result["quality_pass"] = [isinstance(found, tuple) and found == (expected_ars,)
                              for found, expected_ars in zip(result.observed_ars, result.ars, strict=True)]
    result["source"] = source
    return result


def monthly_year_changes(hourly, cfg):
    bands = {"all_day": list(range(24)), **read_yaml(cfg["monthly_hours"]["bands_from"])["bus_exploration"]["bands"]}
    results = []
    for band, hours in bands.items():
        data = hourly[hourly.hour.isin(hours)].groupby(["month", "group", "flow"]).agg(
            value=("value", complete_sum), observed_hours=("value", "count"), calendar_days=("calendar_days", "first")).reset_index()
        for (group, flow), rows in data.groupby(["group", "flow"]):
            indexed = rows.set_index("month")
            for before, after in cfg["monthly_hours"]["pairs"]:
                a, b = indexed.reindex([before, after]).iloc[0], indexed.reindex([before, after]).iloc[1]
                passed = bool(a.observed_hours == len(hours) and b.observed_hours == len(hours)
                              and pd.notna(a.value) and pd.notna(b.value))
                av, bv = (a.value / a.calendar_days, b.value / b.calendar_days) if passed else (np.nan, np.nan)
                results.append({"band": band, "group": group, "flow": flow, "before_month": before, "after_month": after,
                                "before_per_calendar_day": av, "after_per_calendar_day": bv,
                                "change_pct": 100 * (bv / av - 1) if av > 0 else np.nan, "quality_pass": passed})
    return pd.DataFrame(results)


def run():
    cfg = read_yaml("overnight_card_persistence_config.yaml")
    if cfg["locked_year"] != 2026 or any(month >= "2026-01" for month in cfg["months"]):
        raise ValueError("카드 지속성의 잠금 연도 또는 월 범위 오류")
    audit_path = CASE / "results/overnight/daily_cards_persistence/audit.json"
    source = json.loads(audit_path.read_text())
    cache = CASE / source["selected_path"]
    route_path = audit_path.parent / "monthly_reconciliation.csv"
    if sha256(cache) != source["selected_sha256"] or sha256(route_path) != source["outputs"][route_path.name]:
        raise ValueError("카드 지속성의 선택 캐시·월 대조 결과 해시 변경")
    if sha256(CASE / "overnight_card_persistence_config.yaml") != source["config_sha256"]:
        raise ValueError("카드 대조 이후 지속성 규칙이 변경됐습니다")
    if sha256(CASE / cfg["monthly_reference"]) != source["monthly_manifest_sha256"]:
        raise ValueError("카드 월 원본의 출처 명세가 변경됐습니다")
    stations = pd.read_csv(CASE / cfg["identity"], dtype={"stop": str, "ars": str})
    stations = stations[stations.group.isin(cfg["groups"])].copy()
    selected = pd.read_parquet(cache)
    identity = [identity_rows(selected, stations, cfg["months"], "daily")]
    monthly = []
    for entry in json.loads((CASE / cfg["monthly_reference"]).read_text())["files"]:
        if entry["kind"] != "card" or entry["month"] not in cfg["months"]:
            continue
        path = CASE / entry["path"]
        if sha256(path) != entry["sha256"]:
            raise ValueError("카드 월 원본 해시 변경")
        frame, _ = select_rows(path, "cp949", entry["month"], False, set(stations.stop))
        monthly.append(frame[["month", "stop", "ars"]])
    identity.append(identity_rows(pd.concat(monthly, ignore_index=True), stations, cfg["months"], "monthly"))
    identity = pd.concat(identity, ignore_index=True)
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    identity.to_csv(OUT / "identity.csv", index=False)
    if not identity.quality_pass.all():
        raise ValueError("선택된 정류장의 월·일 원본 ID·ARS가 다릅니다. identity.csv를 확인하세요")
    routes = pd.read_csv(route_path, dtype={"stop": str, "route_label": str})
    reconciled = station_reconciliation(routes)
    daily = daily_station_records(selected, reconciled, stations, cfg["months"])
    groups = group_records(daily, stations, cfg["groups"])
    calendar = periods(read_yaml(cfg["calendar_from"]))
    comparisons = []
    for scope, frame, keys in [("direction", groups, ["group", "flow"]), ("station", daily, ["group", "stop", "flow"])]:
        for ids, part in frame.groupby(keys):
            labels = dict(zip(keys, ids, strict=True))
            for name, (before, after) in cfg["comparisons"].items():
                result = describe_comparison(part, calendar[before], calendar[after], cfg, interval=scope == "direction")
                comparisons.append({"scope": scope, **labels, "comparison": name, **result})
    hourly = monthly_hours({**cfg, "monthly_manifest": cfg["monthly_reference"]}, reconciled, stations)
    tables = {"station_month_reconciliation.csv": reconciled, "daily_comparisons.csv": pd.DataFrame(comparisons),
              "daily_direction.csv": groups, "monthly_hourly.csv": hourly,
              "monthly_year_changes.csv": monthly_year_changes(hourly, cfg)}
    for name, table in tables.items():
        table.to_csv(OUT / name, index=False)
    daily.to_parquet(RAW / "daily_station.parquet", index=False)
    inputs = [audit_path, route_path, CASE / cfg["identity"], CASE / cfg["calendar_from"], CASE / cfg["monthly_reference"],
              CASE / "overnight_card_persistence_config.yaml", CASE / "gangnam/overnight_card_records.py",
              CASE / "gangnam/overnight_daily_card_analysis.py", CASE / "gangnam/overnight_daily_card_data.py",
              CASE / "gangnam/overnight_persistence.py", CASE / "gangnam/overnight_sensitivity.py"]
    write_json(OUT / "audit.json", {"completed_at": utcnow(), "configuration": cfg, "calendar": calendar,
                                   "code_sha256": sha256(Path(__file__)),
                                   "inputs": {str(p.relative_to(CASE)): sha256(p) for p in inputs},
                                   "source_selected_sha256": source["selected_sha256"], "identity_pairs": len(identity),
                                   "station_month_flows": len(reconciled), "station_month_flows_pass": int(reconciled.quality_pass.sum()),
                                   "comparisons": len(comparisons), "quality_pass": sum(x["quality_pass"] for x in comparisons),
                                   "daily_station_sha256": sha256(RAW / "daily_station.parquet"),
                                   "outputs": {p.name: sha256(p) for p in OUT.glob("*.csv")}, "interpretation": cfg["interpretation"]})
    print(f"카드 지속성: 정류장·월·승하차 {len(reconciled)}개, 통과 {int(reconciled.quality_pass.sum())}개", flush=True)
