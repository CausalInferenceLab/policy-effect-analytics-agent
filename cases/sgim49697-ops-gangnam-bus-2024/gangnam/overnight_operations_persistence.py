"""원래 공통 셀의 시간·운행·승차 지수를 2025년까지 같은 2024년 기준으로 연장한다."""

import json
from pathlib import Path

import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .directional import CELL
from .overnight_bus import candidate_routes, load_wide, make_time_panel, read_panel
from .overnight_bus_extract import load_wide as load_new_wide
from .overnight_mechanism import METRICS, count_panel, joint_grid
from .overnight_operations_persistence_data import OUT, RAW
from .overnight_persistence import periods
from .overnight_sensitivity import aggregate_daily, describe_comparison


def normalize_fixed(grid, selected):
    if selected.duplicated(CELL).any():
        raise ValueError("공통 셀의 사전 선택 키 중복")
    data = grid.merge(selected, on=CELL, validate="many_to_one")
    data["joint_known"] = data[METRICS].notna().all(axis=1)
    data["zero_trips_positive_boardings"] = data.joint_known & data.trips.eq(0) & data.boardings.gt(0)
    for metric in METRICS:
        baseline = "baseline_2024" if metric == "time" else metric + "_baseline_2024"
        if data[baseline].isna().any() or data[baseline].le(0).any():
            raise ValueError("공통 셀의 2024년 기준 평균 누락·비양수")
        data[metric + "_index"] = (100 * data[metric] / data[baseline]).where(data.joint_known)
    return data


def daily_ratio(data, selected, dates, before, minimum):
    work = data.assign(numerator=data.boardings.where(data.joint_known), denominator=data.trips.where(data.joint_known))
    groups = selected.groupby("group").size().rename("selected_cells")
    grid = pd.MultiIndex.from_product([groups.index, dates], names=["group", "date"])
    result = work.groupby(["group", "date"]).agg(numerator=("numerator", lambda x: x.sum(min_count=1)),
                denominator=("denominator", lambda x: x.sum(min_count=1)), observed=("joint_known", "sum"),
                zero_trips_positive_boardings=("zero_trips_positive_boardings", "sum")).reindex(grid)
    result = result.join(groups, on="group")
    result["coverage"] = result.observed.fillna(0) / result.selected_cells
    result["unit_coverage"] = result.coverage
    result["raw_ratio"] = result.numerator / result.denominator.where(result.denominator.gt(0))
    passed = result.coverage.ge(minimum) & result.zero_trips_positive_boardings.eq(0)
    result["raw_ratio"] = result.raw_ratio.where(passed)
    baseline = result[result.index.get_level_values("date").isin(before)].groupby("group").raw_ratio.mean()
    result["ratio_baseline_2024"] = result.index.get_level_values("group").map(baseline)
    result["index"] = 100 * result.raw_ratio / result.ratio_baseline_2024.where(result.ratio_baseline_2024.gt(0))
    return result.reset_index()


def run():
    cfg = read_yaml("overnight_operations_persistence_config.yaml")
    if cfg["locked_year"] != 2026 or any(month >= "2026-01" for month in cfg["months"]):
        raise ValueError("운영 지속성 잠금 연도 접근 금지")
    calendar_cfg = read_yaml(cfg["calendar_from"])
    calendar = periods(calendar_cfg)
    dates = sorted({date for values in calendar.values() for date in values})
    selection_path, audit_path = CASE / cfg["selection_path"], CASE / cfg["selection_audit"]
    selection_audit = json.loads(audit_path.read_text())
    if sha256(selection_path) != selection_audit["outputs"][selection_path.name]:
        raise ValueError("원래 공통 셀 선택 해시 불일치")
    selected = pd.read_csv(selection_path, dtype={key: str for key in CELL if key != "hour"})
    candidates = set(candidate_routes().route)
    selected = selected[~selected.route.isin(candidates) & selected.group.isin(cfg["groups"])].copy()
    stations = pd.read_csv(CASE / "results/directional/station_registry.csv", dtype={"stop": str})
    identity_audit = json.loads((CASE / "results/overnight/persistence/audit.json").read_text())
    for name in ["results/directional/station_registry.csv", "results/overnight/cards/station_identity.csv"]:
        if sha256(CASE / name) != identity_audit["inputs"][name]:
            raise ValueError("2025년 정류장 식별자 검증 입력의 해시 변경")
    if identity_audit["historical_id_pairs_verified"] != 64 or identity_audit["configuration"]["months"] != cfg["months"]:
        raise ValueError("2025년 중앙 정류장 식별자 검증 범위 불일치")
    stops = set(stations[stations.group.isin(cfg["groups"])].stop)
    base = read_yaml("directional_config.yaml")
    base["hours"] = sorted({hour for band in calendar_cfg["bands"].values() for hour in band})
    old_time, old_time_audit = read_panel()
    new_time_wide, new_time_audit = load_new_wide(cfg["time_and_trips_scope"], "bus_time", cfg["months"])
    new_time, new_time_repeated = make_time_panel(new_time_wide, stations, base)
    panel = pd.concat([old_time[old_time.date.str.startswith("2024")], new_time], ignore_index=True)
    panel = panel[panel.date.isin(dates)]
    counts, audits = {}, {"time_old": old_time_audit, "time_new": new_time_audit}
    for kind, metric in [("bus_trips", "trips"), ("bus_boardings", "boardings")]:
        old, old_audit = load_wide(kind, base)
        scope = cfg["time_and_trips_scope"] if metric == "trips" else cfg["source_scope"]
        new, new_audit = load_new_wide(scope, kind, cfg["months"])
        wide = pd.concat([old[old.date.str.startswith("2024")], new], ignore_index=True)
        wide = wide[wide.date.isin(dates)]
        counts[metric], repeated = count_panel(wide, base["hours"], metric, stops)
        audits[metric] = {"old": old_audit, "new": new_audit, "excluded_revisit_rows": repeated}
    rows, dailies, states = [], [], []
    for (band, endpoint), cells in selected.groupby(["band", "endpoint"]):
        if endpoint not in cfg["endpoint_alignments"]:
            continue
        count_stop = cells.arrival if endpoint == "arrival" else cells.stop
        keys = cells[["route", "hour"]].assign(count_stop=count_stop)
        if keys.duplicated().any():
            raise ValueError("같은 정류장 횟수가 여러 선택 셀에 중복 배정됩니다")
        data = normalize_fixed(joint_grid(panel, cells, counts, dates, endpoint), cells)
        for period, period_dates in calendar.items():
            for group, part in data[data.date.isin(period_dates)].groupby("group"):
                states.append({"band": band, "endpoint": endpoint, "group": group, "period": period,
                               "selected_cells": int(cells.group.eq(group).sum()), "expected_cell_days": len(part),
                               "joint_observed": int(part.joint_known.sum()),
                               **{metric + "_observed": int(part[metric].notna().sum()) for metric in METRICS},
                               "zero_trips_positive_boardings": int(part.zero_trips_positive_boardings.sum())})
        daily_metrics = {metric: aggregate_daily(data.assign(index=data[metric + "_index"]), cells, dates,
                                                 "equal_cells", cfg["minimum_daily_coverage"]) for metric in METRICS}
        daily_metrics["boardings_per_recorded_trip"] = daily_ratio(data, cells, dates, calendar["pre2024"], cfg["minimum_daily_coverage"])
        for metric, daily in daily_metrics.items():
            dailies.append(daily.assign(band=band, endpoint=endpoint, metric=metric))
            for group, part in daily.groupby("group"):
                for name, (before, after) in cfg["comparisons"].items():
                    result = describe_comparison(part, calendar[before], calendar[after], cfg,
                                                interval=band == "evening" and endpoint == cfg["primary_endpoint"])
                    rows.append({"band": band, "endpoint": endpoint, "group": group, "metric": metric,
                                 "comparison": name, "selected_cells": int(cells.group.eq(group).sum()), **result})
        print(f"공통 운영 연장: {band}, {endpoint}, {len(cells)}개 사전 셀", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    daily = pd.concat(dailies, ignore_index=True)
    cache = RAW / "daily_all.parquet"
    daily.to_parquet(cache, index=False)
    outputs = {"comparisons.csv": pd.DataFrame(rows), "observation_states.csv": pd.DataFrame(states),
               "daily_evening.csv": daily[daily.band.eq("evening")], "selected_cells.csv": selected}
    for name, frame in outputs.items():
        frame.to_csv(OUT / name, index=False)
    inputs = ["overnight_operations_persistence_config.yaml", cfg["calendar_from"], cfg["selection_path"], cfg["selection_audit"],
              "results/overnight/persistence/audit.json", "results/overnight/operations_persistence/preparation_audit.json",
              "results/overnight/operations_persistence/extraction_audit.json", "results/overnight/forecast_bus_test/extraction_audit.json",
              "results/directional/station_registry.csv", "gangnam/overnight_mechanism.py", "gangnam/overnight_sensitivity.py",
              "gangnam/overnight_bus.py", "gangnam/overnight_bus_extract.py", "gangnam/overnight_persistence.py"]
    write_json(OUT / "analysis_audit.json", {"completed_at": utcnow(), "configuration": cfg, "calendar": calendar,
               "code_sha256": sha256(Path(__file__)), "inputs": {name: sha256(CASE / name) for name in inputs},
               "source_audits": audits, "new_time_excluded_revisit_rows": new_time_repeated,
               "comparisons": len(rows), "quality_pass": int(outputs["comparisons.csv"].quality_pass.sum()),
               "daily_all_path": str(cache.relative_to(CASE)), "daily_all_sha256": sha256(cache),
               "outputs": {name: sha256(OUT / name) for name in outputs}, "interpretation": cfg["interpretation"]})
