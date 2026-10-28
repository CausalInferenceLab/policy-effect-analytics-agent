"""공통 버스 셀·날짜에서 운행시간·운행횟수·승차 지수를 함께 비교한다."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .directional import CELL, expected_dates, period_dates, select_cells
from .overnight_bus import candidate_routes, load_wide, read_panel
from .overnight_sensitivity import aggregate_daily, describe_comparison

OUT = CASE / "results/overnight/mechanism"
METRICS = ["time", "trips", "boardings"]


def count_panel(wide, hours, name, stops):
    d = wide[wide.stop.isin(stops)].copy()
    repeated = d.duplicated(["date", "route", "stop"], keep=False)
    d = d.loc[~repeated]
    d = d.melt(id_vars=["date", "route", "stop"], value_vars=[f"h{h:02}" for h in hours], var_name="hour", value_name=name)
    d["hour"] = d.hour.str[1:].astype(int)
    d[name] = d[name].where(d[name].ge(0))
    if d.duplicated(["date", "route", "stop", "hour"]).any():
        raise ValueError("정류장 횟수의 일자·노선·정류장·시간 키가 중복됩니다")
    return d.rename(columns={"stop": "count_stop"}), int(repeated.sum())


def select_joint(grid, selected, periods, coverage):
    result = selected.copy()
    for metric in ["trips", "boardings"]:
        for year in [2023, 2024]:
            dates = periods[f"pre{year}"]
            pre = grid[grid.date.isin(dates)].groupby(CELL)[metric].agg(["mean", "count"])
            pre = pre[pre["count"].ge(len(dates) * coverage) & pre["mean"].gt(0)]
            pre = pre.rename(columns={"mean": f"{metric}_baseline_{year}", "count": f"{metric}_pre_count_{year}"})
            result = result.merge(pre.reset_index(), on=CELL, validate="one_to_one")
    return result


def joint_grid(panel, selected, counts, dates, endpoint):
    grid = selected[CELL].merge(pd.DataFrame({"date": dates}), how="cross")
    time = panel[["date", *CELL, "value"]].rename(columns={"value": "time"})
    grid = grid.merge(time, on=["date", *CELL], how="left", validate="one_to_one")
    grid["count_stop"] = grid.arrival if endpoint == "arrival" else grid.stop
    for data in counts.values():
        grid = grid.merge(data, on=["date", "route", "count_stop", "hour"], how="left", validate="many_to_one")
    return grid.drop(columns="count_stop")


def indexes(grid, selected):
    d = grid.merge(selected, on=CELL, how="inner", validate="many_to_one")
    d["joint_known"] = d[METRICS].notna().all(axis=1)
    for metric in METRICS:
        prefix = "baseline" if metric == "time" else metric + "_baseline"
        baseline = d[f"{prefix}_2024"].where(d.date.str.startswith("2024"), d[f"{prefix}_2023"])
        d[f"{metric}_index"] = (100 * d[metric] / baseline).where(d.joint_known)
    return d


def run():
    cfg = read_yaml("overnight_mechanism_config.yaml")
    base = read_yaml(cfg["base_config"])
    explore = read_yaml("overnight_config.yaml")["bus_exploration"]
    base["hours"] = explore["hours"]
    for key in ["minimum_days", "maximum_coverage_gap"]:
        base[key] = cfg[key]
    OUT.mkdir(parents=True, exist_ok=True)
    stations = pd.read_csv(CASE / "results/directional/station_registry.csv", dtype={"stop": str})
    info = stations.set_index("stop")
    stops = set(stations[stations.group.isin(cfg["groups"])].stop)
    panel, time_audit = read_panel()
    adjacent = panel.arrival.map(info.order).eq(panel.stop.map(info.order) + 1)
    panel = panel[panel.group.isin(cfg["groups"]) & adjacent].copy()
    counts, audits = {}, {"time": time_audit}
    for kind, metric in [("bus_trips", "trips"), ("bus_boardings", "boardings")]:
        wide, audit = load_wide(kind, base)
        counts[metric], repeated = count_panel(wide, base["hours"], metric, stops)
        audits[metric] = {**audit, "excluded_revisit_rows": repeated}
        del wide
    source_dates = sorted(set.intersection(*(set(a["source_available_dates"]) for a in audits.values())))
    periods = period_dates(base, source_dates)
    candidates = set(candidate_routes().route)
    comparisons, daily_rows, eligibility, chosen = [], [], [], []
    windows = [("summer2023", "pre2023", "post2023"), ("summer2024", "pre2024", "post2024"),
               ("autumn2024", "pre2024", "autumn2024")]
    for band, hours in explore["bands"].items():
        part = panel[panel.hour.isin(hours)]
        original = select_cells(part, periods, cfg["minimum_cell_pre_coverage"], "common_pre_source_days")
        for endpoint in cfg["endpoint_alignments"]:
            grid = joint_grid(part, original, counts, source_dates, endpoint)
            selected = select_joint(grid, original, periods, cfg["minimum_cell_pre_coverage"])
            chosen.append(selected.assign(band=band, endpoint=endpoint))
            normalized = indexes(grid, selected)
            for subset in cfg["subsets"]:
                keep = selected if subset == "all_preselected" else selected[~selected.route.isin(candidates)]
                denominator = original if subset == "all_preselected" else original[~original.route.isin(candidates)]
                sub = normalized.merge(keep[CELL], on=CELL, validate="many_to_one")
                for group in cfg["groups"]:
                    before_count, count = int(denominator.group.eq(group).sum()), int(keep.group.eq(group).sum())
                    eligibility.append({"band": band, "endpoint": endpoint, "subset": subset, "group": group,
                                        "time_preselected_cells": before_count, "joint_selected_cells": count,
                                        "joint_cell_fraction": count / before_count if before_count else np.nan})
                for scope in ["direction", "segment"]:
                    keys, values = keep.copy(), sub.copy()
                    if scope == "segment":
                        for d in [keys, values]:
                            d["group"] = d.group + "|" + d.stop + "|" + d.arrival
                    for metric in METRICS:
                        d = values.assign(index=values[f"{metric}_index"])
                        daily = aggregate_daily(d, keys, source_dates, "equal_cells", cfg["minimum_daily_coverage"])
                        labels = {"band": band, "endpoint": endpoint, "subset": subset, "scope": scope, "metric": metric}
                        daily_rows.append(daily.assign(**labels))
                        for group, group_daily in daily.groupby("group"):
                            for name, before, after in windows:
                                interval = band == "evening" and endpoint == "arrival" and scope == "direction" and subset == "other_or_unclassified"
                                result = describe_comparison(group_daily, periods[before], periods[after], base, interval=interval)
                                comparisons.append({**labels, "group": group, "comparison": name, **result})
            print(f"공통 운영 지수: {band} {endpoint} 시간 셀 {len(original):,} / 공동 셀 {len(selected):,}", flush=True)
    pd.DataFrame(comparisons).to_csv(OUT / "comparisons.csv", index=False)
    daily = pd.concat(daily_rows, ignore_index=True)
    cache = CASE / "data/overnight/mechanism/daily_all.parquet"
    cache.parent.mkdir(parents=True, exist_ok=True)
    daily.to_parquet(cache, index=False)
    daily[daily.scope.eq("direction")].to_csv(OUT / "daily_direction.csv", index=False)
    pd.DataFrame(eligibility).to_csv(OUT / "eligibility.csv", index=False)
    pd.concat(chosen, ignore_index=True).to_csv(OUT / "selected_cells.csv", index=False)
    write_json(OUT / "audit.json", {"completed_at": utcnow(), "config_sha256": sha256(CASE / "overnight_mechanism_config.yaml"),
                                   "code_sha256": sha256(Path(__file__)), "input_audits": audits, "period_dates": periods,
                                   "joint_source_dates": source_dates, "joint_missing_dates": sorted(set(expected_dates(base)) - set(source_dates)),
                                   "daily_all_path": str(cache.relative_to(CASE)), "daily_all_sha256": sha256(cache),
                                   "outputs": {p.name: sha256(p) for p in OUT.glob("*.csv")},
                                   "scope": "과거 ID·ARS가 확인된 인접 중앙 구간의 제한 공통 표본. 기록 시간·운행·승차 지수의 동시 기술 비교이며 인과·개별 차량 매칭이 아님."})
