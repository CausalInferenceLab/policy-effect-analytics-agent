"""시간대·표본·집계·관측률에 따른 버스 지수의 기술 비교와 결측 분해를 실행한다."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .common import read_yaml, sha256, write_json
from .directional import CELL, compare, expected_dates, period_dates, select_cells
from .overnight_bus import OLD, OUT, RAW, candidate_routes, read_panel


def normalized(panel, selected):
    d = panel.merge(selected[CELL + ["baseline_2023", "baseline_2024"]], on=CELL, validate="many_to_one")
    baseline = d.baseline_2024.where(d.date.str.startswith("2024"), d.baseline_2023)
    d["index"] = 100 * d.value / baseline
    return d


def aggregate_daily(d, selected, dates, method, threshold):
    """고정 셀의 집계와 계층별 관측률을 모두 공개한다. 결측 노선은 0이 아니다."""
    if selected.empty:
        return pd.DataFrame(columns=["group", "date", "index", "coverage", "unit_coverage", "observed", "selected_cells"])
    counts = selected.groupby("group").size().rename("selected_cells")
    grid = pd.MultiIndex.from_product([counts.index, dates], names=["group", "date"])
    daily = d.groupby(["group", "date"]).agg(observed=("index", "count"), index=("index", "mean"))
    daily = daily.reindex(grid).join(counts, on="group")
    daily["coverage"] = daily.observed.fillna(0) / daily.selected_cells
    daily["unit_coverage"] = daily.coverage
    if method == "median_cells":
        daily["index"] = d.groupby(["group", "date"])["index"].median()
    elif method in {"equal_routes", "equal_segments"}:
        unit = ["route"] if method == "equal_routes" else ["stop", "arrival"]
        units = selected.groupby(["group", *unit]).size().rename("unit_cells")
        per = d.groupby(["group", *unit, "date"]).agg(index=("index", "mean"), observed=("index", "count"))
        per = per.join(units, on=["group", *unit])
        per.loc[per.observed / per.unit_cells < threshold, "index"] = np.nan
        total_units = units.groupby("group").size()
        grouped = per.reset_index().groupby(["group", "date"])["index"].agg(["mean", "count"])
        daily["index"] = grouped["mean"]
        daily["unit_coverage"] = grouped["count"].reindex(grid).fillna(0) / daily.index.get_level_values("group").map(total_units)
    elif method != "equal_cells":
        raise ValueError(f"알 수 없는 집계법: {method}")
    daily.loc[(daily.coverage < threshold) | (daily.unit_coverage < threshold), "index"] = np.nan
    return daily.reset_index()


def describe_comparison(daily, before, after, cfg, interval=False):
    a, b = daily[daily.date.isin(before)], daily[daily.date.isin(after)]
    av, bv = a["index"].dropna(), b["index"].dropna()
    ac, bc = a.coverage.mean(), b.coverage.mean()
    au, bu = a.unit_coverage.mean(), b.unit_coverage.mean()
    passed = (len(av) >= cfg["minimum_days"] and len(bv) >= cfg["minimum_days"]
              and pd.notna(ac) and pd.notna(bc) and abs(ac - bc) <= cfg["maximum_coverage_gap"]
              and pd.notna(au) and pd.notna(bu) and abs(au - bu) <= cfg["maximum_coverage_gap"])
    result = {"before_mean": av.mean(), "after_mean": bv.mean(),
              "change_pct": 100 * (bv.mean() / av.mean() - 1) if len(av) and len(bv) and av.mean() > 0 else np.nan,
              "before_days": len(av), "after_days": len(bv), "before_expected_days": len(before), "after_expected_days": len(after),
              "before_coverage": ac, "after_coverage": bc, "before_unit_coverage": au, "after_unit_coverage": bu,
              "quality_pass": bool(passed), "week_bootstrap_low": np.nan, "week_bootstrap_high": np.nan}
    if interval and len(av) and len(bv):
        interval_result = compare(daily, before, after, cfg)
        result.update({k: interval_result[k] for k in ("week_bootstrap_low", "week_bootstrap_high")})
    return result


def decomposition(panel, selected, periods, source_dates, band, cohort):
    """원본 날짜 부재와 셀 행 부재, 공란, 0을 고정 분모에서 분리한다."""
    if selected.empty:
        return pd.DataFrame()
    all_dates = sorted(set().union(*periods.values()))
    grid = selected[CELL].merge(pd.DataFrame({"date": all_dates}), how="cross")
    grid = grid.merge(panel[["date", *CELL, "record_status"]], on=["date", *CELL], how="left", validate="one_to_one")
    grid["record_status"] = grid.record_status.fillna("row_absent")
    grid.loc[~grid.date.isin(source_dates), "record_status"] = "source_date_absent"
    frames = []
    for period, dates in periods.items():
        part = grid[grid.date.isin(dates)]
        summary = part.groupby(["group", "route", "stop", "arrival", "record_status"]).size().unstack(fill_value=0)
        summary = summary.reindex(columns=["positive", "zero", "blank", "negative", "row_absent", "source_date_absent"], fill_value=0)
        summary["expected_cells"] = summary.sum(axis=1)
        summary["positive_fraction"] = summary.positive / summary.expected_cells
        summary["period"] = period
        frames.append(summary.reset_index())
    result = pd.concat(frames, ignore_index=True)
    result = result.merge(candidate_routes(), on="route", how="left", validate="many_to_one")
    result["policy_group"] = result.policy_group.fillna("other_or_unclassified")
    return result.assign(band=band, cohort=cohort)


def weekend_periods(cfg, source_dates):
    return {name: [str(d.date()) for d in pd.date_range(start, end)
                   if d.dayofweek >= 5 and str(d.date()) in source_dates]
            for name, (start, end) in cfg["periods"].items()}


def run():
    cfg = read_yaml("overnight_config.yaml")
    exp = cfg["bus_exploration"]
    base = read_yaml(exp["base_config"])
    base.update(minimum_coverage=exp["primary_coverage"], minimum_days=exp["minimum_days"], maximum_coverage_gap=exp["maximum_coverage_gap"])
    panel, audit = read_panel()
    calendar = period_dates(base)
    source = period_dates(base, set(audit["source_available_dates"]))
    dates = expected_dates(base)
    comparisons, all_daily, saved_daily, selections, lost = [], [], [], [], []
    for band, hours in exp["bands"].items():
        part = panel[panel.hour.isin(hours)]
        for cohort in exp["cohorts"]:
            periods = calendar if cohort == "2024_pre_calendar" else source
            selected = select_cells(part, periods, exp["primary_coverage"], cohort)
            selected["band"], selected["cohort"] = band, cohort
            selections.append(selected)
            normalized_part = normalized(part, selected)
            if cohort != "summer_survivors_source_days":
                lost.append(decomposition(part, selected, calendar, set(audit["source_available_dates"]), band, cohort))
            contrasts = [("summer2024", "pre2024", "post2024"), ("autumn2024", "pre2024", "autumn2024")]
            if cohort != "2024_pre_calendar":
                contrasts.insert(0, ("summer2023", "pre2023", "post2023"))
            for threshold in [exp["primary_coverage"], *exp["coverage_sensitivity"]]:
                for method in exp["aggregations"]:
                    daily = aggregate_daily(normalized_part, selected, dates, method, threshold)
                    tagged = daily.assign(band=band, cohort=cohort, aggregation=method, daily_threshold=threshold)
                    all_daily.append(tagged)
                    if threshold == exp["primary_coverage"] and method == "equal_cells":
                        saved_daily.append(tagged)
                    for label, before, after in contrasts:
                        for group, group_data in daily.groupby("group"):
                            result = describe_comparison(group_data, periods[before], periods[after], base,
                                                         interval=threshold == exp["primary_coverage"] and method == "equal_cells")
                            comparisons.append({"band": band, "cohort": cohort, "aggregation": method, "daily_threshold": threshold,
                                                "day_type": "weekday", "group": group, "comparison": label,
                                                "selected_cells": int(selected.group.eq(group).sum()), **result})
            # 주말은 별도 사전 평균·셀을 사용한다. 20일 요건을 임의로 낮추지 않는다.
        weekend = weekend_periods(base, set(audit["source_available_dates"]))
        selected = select_cells(part, weekend, exp["primary_coverage"], "2024_pre_calendar")
        daily = aggregate_daily(normalized(part, selected), selected, dates, "equal_cells", exp["primary_coverage"])
        for label, before, after in [("summer2024", "pre2024", "post2024"), ("autumn2024", "pre2024", "autumn2024")]:
            for group, group_data in daily.groupby("group"):
                comparisons.append({"band": band, "cohort": "weekend_2024_pre_source", "aggregation": "equal_cells",
                                    "daily_threshold": exp["primary_coverage"], "day_type": "weekend", "group": group, "comparison": label,
                                    "selected_cells": int(selected.group.eq(group).sum()),
                                    **describe_comparison(group_data, weekend[before], weekend[after], base)})
        print(f"버스 집계 민감도: {band} 완료", flush=True)
    results = pd.DataFrame(comparisons)
    results.to_csv(OUT / "aggregation_comparisons.csv", index=False)
    pd.concat(saved_daily, ignore_index=True).to_csv(OUT / "daily_indices_primary.csv", index=False)
    pd.concat(all_daily, ignore_index=True).to_parquet(RAW / "daily_indices_all.parquet", index=False)
    pd.concat(selections, ignore_index=True).to_csv(OUT / "selected_cells.csv", index=False)
    pd.concat(lost, ignore_index=True).to_csv(OUT / "missingness_by_route_segment.csv", index=False)
    info = {"mode": "exploratory", "comparisons": len(results), "quality_pass": int(results.quality_pass.sum()),
            "configuration": exp, "normalization_periods": base["periods"], "input_panel_sha256": audit["panel_sha256"],
            "code_sha256": sha256(Path(__file__)), "source_manifest_sha256": sha256(OLD / "extraction_audit.json"),
            "selection": "관측률 0.80에서 셀 고정 후 일별 판정만 0.75/0.80/0.85/0.90 변화. 사후 생존 표본은 별도 민감도.",
            "interval": "주 단위 기술적 변동 구간이며 다중 탐색을 보정한 인과 검정이 아님",
            "all_daily_path": str((RAW / "daily_indices_all.parquet").relative_to(RAW.parents[2])),
            "all_daily_sha256": sha256(RAW / "daily_indices_all.parquet"),
            "outputs": {p.name: sha256(p) for p in OUT.glob("*.csv")}}
    write_json(OUT / "sensitivity_audit.json", info)
    print(json.dumps({"comparisons": len(results), "quality_pass": int(results.quality_pass.sum())}), flush=True)
