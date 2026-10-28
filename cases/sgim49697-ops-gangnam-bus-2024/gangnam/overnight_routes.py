"""노선군별 조건부 변화와 개별 시간·기준 날짜의 민감도를 비교한다."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pandas as pd

from .common import read_yaml, sha256, write_json
from .directional import expected_dates, period_dates, select_cells
from .overnight_bus import OUT, candidate_routes, read_panel
from .overnight_sensitivity import aggregate_daily, describe_comparison, normalized


def split_groups(selected, normalized_panel, candidates):
    mapping = candidates.set_index("route").policy_group
    s, d = selected.copy(), normalized_panel.copy()
    for frame in (s, d):
        frame["direction"] = frame.group
        frame["policy_group"] = frame.route.map(mapping).fillna("other_or_unclassified")
        frame["group"] = frame.direction + "|" + frame.policy_group
    return s, d


def timing_scan(daily, source_days, base, cfg):
    """동일 패널의 날짜 민감도이며 독립 위약 실험·처치일 탐색으로 해석하지 않는다."""
    rows = []
    source_days = set(source_days)
    for year in cfg["years"]:
        candidates = list(pd.date_range(f"{year}-{cfg['candidate_start_mmdd']}", f"{year}-{cfg['candidate_end_mmdd']}",
                                        freq=f"{cfg['date_stride_days']}D"))
        candidates.extend(pd.Timestamp(x) for x in cfg["reference_dates"] if x.startswith(str(year)))
        for stamp in sorted(set(candidates)):
            before = [str(x.date()) for x in pd.date_range(stamp - timedelta(days=cfg["window_calendar_days"]), stamp - timedelta(days=1))
                      if x.dayofweek < 5 and str(x.date()) in source_days]
            after = [str(x.date()) for x in pd.date_range(stamp + timedelta(days=1), stamp + timedelta(days=cfg["window_calendar_days"]))
                     if x.dayofweek < 5 and str(x.date()) in source_days]
            for (band, group), part in daily.groupby(["band", "group"]):
                result = describe_comparison(part, before, after, base)
                rows.append({"year": year, "cut_date": str(stamp.date()), "band": band, "group": group,
                             "reference_date": str(stamp.date()) in cfg["reference_dates"], **result})
    result = pd.DataFrame(rows)
    result["absolute_change"] = result.change_pct.abs().where(result.quality_pass)
    result["rank_among_eligible_dates"] = result.groupby(["year", "band", "group"]).absolute_change.rank(ascending=False, method="min")
    return result


def run():
    cfg = read_yaml("overnight_route_config.yaml")
    parent = read_yaml("overnight_config.yaml")
    base = read_yaml(parent["bus_exploration"]["base_config"])
    base.update(minimum_days=cfg["minimum_days"], minimum_coverage=cfg["primary_coverage"], maximum_coverage_gap=cfg["maximum_coverage_gap"])
    panel, audit = read_panel()
    calendar = period_dates(base)
    source = period_dates(base, set(audit["source_available_dates"]))
    dates = expected_dates(base)
    selected_all = pd.read_csv(OUT / "selected_cells.csv", dtype={c: str for c in ["route", "stop", "arrival"]})
    candidates = candidate_routes()
    rows, daily_records = [], []
    for band, hours in parent["bus_exploration"]["bands"].items():
        part = panel[panel.hour.isin(hours)]
        for cohort in cfg["cohorts"]:
            periods = calendar if cohort == "2024_pre_calendar" else source
            selected = selected_all[selected_all.band.eq(band) & selected_all.cohort.eq(cohort)]
            s, d = split_groups(selected, normalized(part, selected), candidates)
            contrasts = [("summer2024", "pre2024", "post2024"), ("autumn2024", "pre2024", "autumn2024")]
            if cohort != "2024_pre_calendar":
                contrasts.insert(0, ("summer2023", "pre2023", "post2023"))
            for method in cfg["aggregations"]:
                daily = aggregate_daily(d, s, dates, method, cfg["primary_coverage"])
                if method == "equal_cells":
                    daily_records.append(daily.assign(band=band, cohort=cohort))
                for label, pre, post in contrasts:
                    for group, group_data in daily.groupby("group"):
                        direction, policy_group = group.split("|")
                        chosen = s[s.group.eq(group)]
                        rows.append({"band": band, "cohort": cohort, "aggregation": method, "direction": direction,
                                     "policy_group": policy_group, "comparison": label, "selected_cells": len(chosen),
                                     "selected_routes": chosen.route.nunique(),
                                     **describe_comparison(group_data, periods[pre], periods[post], base, interval=method == "equal_cells")})
        print(f"노선군 비교: {band}", flush=True)
    pd.DataFrame(rows).to_csv(OUT / "route_group_comparisons.csv", index=False)
    pd.concat(daily_records, ignore_index=True).to_csv(OUT / "route_group_daily.csv", index=False)
    hourly = []
    for hour in cfg["hour_profile"]["hours"]:
        part = panel[panel.hour.eq(hour)]
        selected = select_cells(part, source, cfg["primary_coverage"], cfg["hour_profile"]["cohort"])
        daily = aggregate_daily(normalized(part, selected), selected, dates, "equal_cells", cfg["primary_coverage"])
        for label, pre, post in [("summer2023", "pre2023", "post2023"), ("summer2024", "pre2024", "post2024"), ("autumn2024", "pre2024", "autumn2024")]:
            for group, group_data in daily.groupby("group"):
                hourly.append({"hour": hour, "group": group, "comparison": label, "selected_cells": int(selected.group.eq(group).sum()),
                               **describe_comparison(group_data, source[pre], source[post], base)})
    pd.DataFrame(hourly).to_csv(OUT / "hourly_comparisons.csv", index=False)
    # 실제 공휴일은 원래 기준과 동일하게 제외하되 원본 누락은 보간하지 않는다.
    from .directional import holiday_set

    legal_days = set(audit["source_available_dates"]) - holiday_set(base)
    daily = pd.read_csv(OUT / "daily_indices_primary.csv")
    daily = daily[daily.cohort.eq(cfg["timing_scan"]["cohort"])]
    scan = timing_scan(daily, legal_days, base, cfg["timing_scan"])
    scan.to_csv(OUT / "timing_sensitivity.csv", index=False)
    write_json(OUT / "route_group_audit.json", {"configuration": cfg, "code_sha256": sha256(Path(__file__)),
        "panel_sha256": audit["panel_sha256"], "selected_cells_sha256": sha256(OUT / "selected_cells.csv"),
        "comparisons": len(rows), "timing_comparisons": len(scan),
        "outputs": {name: sha256(OUT / name) for name in ["route_group_comparisons.csv", "route_group_daily.csv", "hourly_comparisons.csv", "timing_sensitivity.csv"]}})
