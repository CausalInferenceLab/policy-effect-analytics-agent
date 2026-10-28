"""재차인원 기록의 통행시간 결합 범위와 사전 고정 가중치 사용 가능성을 점검한다."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, write_json
from .directional import CELL, period_dates
from .overnight_bus import OUT as BUS_OUT
from .overnight_bus import make_time_panel, read_panel
from .overnight_bus_extract import load_wide
from .overnight_sensitivity import describe_comparison, normalized

OUT = CASE / "results/overnight/passengers"


def fixed_weights(joined, selected, before, minimum):
    """가중치는 사전 날짜의 비음수 기록만 이용하며 공란을 0으로 바꾸지 않는다."""
    observed = joined[joined.date.isin(before)].copy()
    observed["passenger"] = observed.passenger.where(observed.passenger.ge(0))
    estimates = observed.groupby(CELL, observed=True).passenger.agg(["mean", "count"])
    estimates["weight"] = estimates["mean"].where(estimates["count"].ge(len(before) * minimum))
    return selected.merge(estimates[["weight", "count"]].reset_index(), on=CELL, how="left", validate="one_to_one")


def weighted_daily(joined, weights, dates, minimum):
    d = joined.merge(weights[CELL + ["weight"]], on=CELL, how="inner", validate="many_to_one")
    d["available_weight"] = d.weight.where(d["index"].notna(), 0.)
    d["weighted_index"] = d["index"] * d.weight
    totals = weights.groupby("group", observed=True).agg(total_weight=("weight", "sum"),
        selected_cells=("weight", "size"), weight_cells=("weight", "count"))
    daily = d.groupby(["group", "date"], observed=True).agg(
        weighted_index=("weighted_index", lambda x: x.sum(min_count=1)),
        available_weight=("available_weight", "sum"), observed=("index", "count"))
    expected = pd.MultiIndex.from_product([totals.index, dates], names=["group", "date"])
    daily = daily.reindex(expected).join(totals, on="group")
    daily["coverage"] = daily.available_weight.fillna(0) / daily.total_weight.replace(0, np.nan)
    daily["cell_coverage"] = daily.observed.fillna(0) / daily.selected_cells
    daily["unit_coverage"] = daily.cell_coverage
    daily["weight_cell_fraction"] = daily.weight_cells / daily.selected_cells
    daily["index"] = daily.weighted_index / daily.available_weight.replace(0, np.nan)
    valid = daily.coverage.ge(minimum) & daily.cell_coverage.ge(minimum) & daily.weight_cell_fraction.ge(minimum)
    daily.loc[~valid, "index"] = np.nan
    return daily.reset_index()


def run():
    cfg = read_yaml("overnight_config.yaml")
    base = read_yaml(cfg["bus_exploration"]["base_config"])
    months = [f"2024-{m:02}" for m in range(4, 9)]
    wide, audit = load_wide("passengers", "bus_passengers", months)
    hours = [f"h{h:02}" for h in range(24)]
    complete = wide[hours].notna().all(axis=1)
    # 일부 시간 합계와 일합계는 서로 같은 지표라고 먼저 가정하지 않는다.
    sums = wide[hours].sum(axis=1, min_count=1)
    audit.update(daily_total_comparison={"complete_24h_rows": int(complete.sum()),
        "complete_rows_matching_daily_total": int((complete & np.isclose(sums, wide.daily_total, equal_nan=False)).sum()),
        "all_rows_known_hour_sum_exceeding_daily_total": int((sums > wide.daily_total + 1e-9).sum()),
        "all_rows_known_hour_sum_matching_daily_total": int(np.isclose(sums, wide.daily_total, equal_nan=False).sum()),
        "note": "공란 시간대를 0으로 확인한 것이 아님. 관측된 시간 합계와 일합계의 일치만 점검."})
    stations = pd.read_csv(CASE / "results/directional/station_registry.csv", dtype={"stop": str, "ars": str})
    panel, repeated = make_time_panel(wide, stations, {**base, "hours": list(range(24))})
    panel = panel.rename(columns={"raw_value": "passenger", "record_status": "passenger_status"})
    bus, bus_audit = read_panel()
    bus = bus[bus.date.str[:7].isin(months)]
    joined = bus.merge(panel[["date", *CELL, "passenger", "passenger_status"]], on=["date", *CELL], how="left", validate="one_to_one")
    joined["passenger_status"] = joined.passenger_status.fillna("row_absent")
    bands = {h: name for name, hh in cfg["bus_exploration"]["bands"].items() for h in hh}
    joined["band"] = joined.hour.map(bands).fillna("between_bands")
    coverage = joined.groupby(["date", "group", "policy_group", "band", "record_status", "passenger_status"], observed=True).size().rename("cells").reset_index()
    coverage.to_csv(OUT / "join_coverage_daily.csv", index=False)
    periods = period_dates(base, set(bus_audit["source_available_dates"]))
    # 원본이 없는 날짜를 가중치 분모에서 제외하지 않는다. 버스 기준 사전 날짜를 공통 분모로 유지한다.
    selected_all = pd.read_csv(BUS_OUT / "selected_cells.csv", dtype={c: str for c in ["route", "stop", "arrival"]})
    selected_all = selected_all[selected_all.cohort.eq("common_pre_source_days")]
    dates = sorted(bus.date.unique())
    records, weight_records, daily_records = [], [], []
    for band, band_hours in cfg["bus_exploration"]["bands"].items():
        s = selected_all[selected_all.band.eq(band)]
        part = normalized(joined[joined.hour.isin(band_hours)], s)
        for cohort in ["all_preselected", "other_or_unclassified"]:
            data = part if cohort == "all_preselected" else part[part.policy_group.eq(cohort)]
            selected = s.merge(data[CELL].drop_duplicates(), on=CELL, how="inner", validate="one_to_one")
            weights = fixed_weights(data, selected, periods["pre2024"], .8)
            daily = weighted_daily(data, weights, dates, .8)
            weight_records.append(weights.assign(band=band, subset=cohort))
            daily_records.append(daily.assign(band=band, subset=cohort))
            for group, group_data in daily.groupby("group"):
                chosen = weights[weights.group.eq(group)]
                result = describe_comparison(group_data, periods["pre2024"], periods["post2024"], base)
                records.append({"band": band, "subset": cohort, "group": group,
                    "selected_cells": len(chosen), "eligible_weight_cells": int(chosen.weight.notna().sum()),
                    "weight_cell_fraction": float(chosen.weight.notna().mean()),
                    "total_pre_weight": float(chosen.weight.sum()), **result})
    pd.DataFrame(records).to_csv(OUT / "fixed_weight_comparisons.csv", index=False)
    pd.concat(weight_records, ignore_index=True).to_csv(OUT / "fixed_pre_weights.csv", index=False)
    pd.concat(daily_records, ignore_index=True).to_csv(OUT / "fixed_weight_daily.csv", index=False)
    audit.update(panel_rows=len(panel), excluded_revisit_rows=repeated,
        join_rows=len(joined), positive_time_rows=int(joined.value.notna().sum()),
        matched_passenger_rows=int(joined.passenger_status.ne("row_absent").sum()),
        recorded_nonnegative_passenger_rows=int(joined.passenger.ge(0).sum()),
        code_sha256=sha256(Path(__file__)), bus_panel_sha256=bus_audit["panel_sha256"],
        outputs={name: sha256(OUT / name) for name in ["join_coverage_daily.csv", "fixed_weight_comparisons.csv", "fixed_pre_weights.csv", "fixed_weight_daily.csv"]},
        interpretation="구간별 재차인원합의 상대적 사전 가중치 가능성 점검. 고유 승객 수·혼잡도·승객 분·차내 평균 탑승인원으로 해석하지 않음.")
    write_json(OUT / "passenger_audit.json", audit)
    print(f"재차인원 결합: {len(joined):,}개 시간 셀, 가중 비교 {len(records)}개", flush=True)
