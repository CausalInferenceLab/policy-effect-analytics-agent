"""월별 카드 기록을 관측 범위와 사전 고정 노선표기 표본으로 나누어 기술 비교한다."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .overnight_card import OUT, REGISTRY


def fixed_labels(panel, pre_months, months):
    """4·5월의 네 파일 모두에서 48시간·승하차 셀이 유효한 카드 노선표기×정류장만 선택한다."""
    keys = ["route_label", "stop"]
    pre = panel[panel.month.isin(pre_months)].groupby([*keys, "month"]).value.agg(["count", "size"])
    good = pre[pre["count"].eq(48) & pre["size"].eq(48)].reset_index().groupby(keys).month.nunique()
    selected = good[good.eq(len(pre_months))].reset_index()[keys]
    grid = selected.merge(pd.DataFrame({"month": months}), how="cross")
    grid = grid.merge(pd.DataFrame({"hour": range(24)}), how="cross")
    grid = grid.merge(pd.DataFrame({"flow": ["boardings", "alightings"]}), how="cross")
    actual = panel[panel.eligible_row].drop(columns=["ars", "eligible_row"])
    result = grid.merge(actual, on=[*keys, "month", "hour", "flow"], how="left", validate="one_to_one")
    result["status"] = result.status.fillna("row_absent")
    return result, selected


def station_monthly(panel, stations, months, bands, cohort):
    outputs = []
    for band, hours in bands.items():
        d = panel[panel.hour.isin(hours)]
        result = d.groupby(["month", "stop", "flow"]).agg(
            observed_subtotal=("value", lambda x: x.sum(min_count=1)),
            observed_cells=("value", "count"), expected_cells=("value", "size"),
            route_label_count=("route_label", "nunique"))
        grid = pd.MultiIndex.from_product([months, stations.stop, ["boardings", "alightings"]], names=["month", "stop", "flow"])
        result = result.reindex(grid)
        for col in ["observed_cells", "expected_cells", "route_label_count"]:
            result[col] = result[col].fillna(0).astype(int)
        result["known_fraction"] = result.observed_cells / result.expected_cells.replace(0, np.nan)
        result["quality_complete"] = result.expected_cells.gt(0) & result.observed_cells.eq(result.expected_cells)
        result["total"] = result.observed_subtotal.where(result.quality_complete)
        result = result.reset_index().merge(stations[["stop", "ars", "group", "order"]], on="stop", validate="many_to_one")
        result["calendar_days"] = result.month.map(lambda x: pd.Period(x).days_in_month)
        result["per_calendar_day"] = result.total / result.calendar_days
        outputs.append(result.assign(band=band, cohort=cohort))
    return pd.concat(outputs, ignore_index=True)


def group_monthly(station, stations):
    keys = ["cohort", "month", "group", "band", "flow"]
    result = station.groupby(keys).agg(observed_subtotal=("observed_subtotal", lambda x: x.sum(min_count=1)),
                                       total=("total", lambda x: x.sum(min_count=1)),
                                       complete_stations=("quality_complete", "sum"),
                                       observed_cells=("observed_cells", "sum"), expected_cells=("expected_cells", "sum"),
                                       calendar_days=("calendar_days", "first")).reset_index()
    result["expected_stations"] = result.group.map(stations.groupby("group").size())
    result["quality_complete"] = result.complete_stations.eq(result.expected_stations)
    result["total"] = result.total.where(result.quality_complete)
    result["per_calendar_day"] = result.total / result.calendar_days
    result["known_fraction"] = result.observed_cells / result.expected_cells.replace(0, np.nan)
    return result


def period_result(frame, months):
    d = frame[frame.month.isin(months)]
    complete = set(d.month) == set(months) and len(d) == len(months) and d.quality_complete.all() and d.total.notna().all()
    return {"mean_per_calendar_day": float(d.total.sum() / d.calendar_days.sum()) if complete else np.nan,
            "complete_months": int(d.quality_complete.sum()), "expected_months": len(months),
            "complete": bool(complete)}


def comparisons(monthly, keys, cfg):
    rows = []
    for key, d in monthly.groupby(keys):
        identity = dict(zip(keys, key if isinstance(key, tuple) else (key,), strict=True))
        for year in [2023, 2024]:
            before_months = [f"{year}-{m:02}" for m in cfg["reference_pre_months"]]
            before = period_result(d, before_months)
            for name, months in [("summer", cfg["reference_post_months"]), ("fall", cfg["reference_fall_months"])]:
                after_months = [f"{year}-{m:02}" for m in months]
                after = period_result(d, after_months)
                valid = before["complete"] and after["complete"] and before["mean_per_calendar_day"] > 0
                rows.append({**identity, "year": year, "period": name, "before_months": "|".join(before_months),
                             "after_months": "|".join(after_months),
                             **{f"before_{k}": v for k, v in before.items()}, **{f"after_{k}": v for k, v in after.items()},
                             "change_pct": 100 * (after["mean_per_calendar_day"] / before["mean_per_calendar_day"] - 1) if valid else np.nan,
                             "quality_complete": bool(valid)})
    return pd.DataFrame(rows)


def run():
    audit = json.loads((OUT / "audit.json").read_text())
    path = CASE / audit["panel_path"]
    if sha256(path) != audit["panel_sha256"]:
        raise ValueError("월별 카드 추출 패널 해시 불일치")
    panel = pd.read_parquet(path)
    cfg = read_yaml("overnight_auxiliary_config.yaml")["card"]
    months = cfg["analysis_months"]
    stations = pd.read_csv(REGISTRY, dtype={"stop": str, "ars": str})
    bands = {**read_yaml("overnight_config.yaml")["bus_exploration"]["bands"], "all_day": list(range(24))}
    pre_months = [f"{y}-{m:02}" for y in [2023, 2024] for m in cfg["reference_pre_months"]]
    fixed, selected = fixed_labels(panel, pre_months, months)
    selected.to_csv(OUT / "selected_pre_labels.csv", index=False)
    station = pd.concat([station_monthly(panel, stations, months, bands, "all_recorded_labels"),
                         station_monthly(fixed, stations, months, bands, "common_pre_labels")], ignore_index=True)
    group = group_monthly(station, stations)
    station.to_csv(OUT / "monthly_station.csv", index=False)
    group.to_csv(OUT / "monthly_group.csv", index=False)
    for scope, frame, keys in [("group", group, ["cohort", "group", "band", "flow"]),
                               ("station", station, ["cohort", "group", "stop", "ars", "band", "flow"])]:
        comparisons(frame, keys, cfg).to_csv(OUT / f"{scope}_comparisons.csv", index=False)
    write_json(OUT / "analysis_audit.json", {"completed_at": utcnow(), "code_sha256": sha256(Path(__file__)),
                                            "prepared_audit_sha256": sha256(OUT / "audit.json"),
                                            "config_sha256": sha256(CASE / "overnight_auxiliary_config.yaml"),
                                            "pre_selection_months": pre_months, "selected_label_station_pairs": len(selected),
                                            "outputs": {p.name: sha256(p) for p in OUT.glob("*.csv")},
                                            "scope": "서울 면허 버스의 월별 기록을 달력 일수로 나눈 기술 비교. 카드 노선표기를 BIS ID와 연결하지 않으며, 공란·반복 방문·부재를 0으로 채우지 않음."})
