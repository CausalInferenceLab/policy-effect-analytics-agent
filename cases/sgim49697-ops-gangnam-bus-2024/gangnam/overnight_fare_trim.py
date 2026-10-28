"""이미 고정한 버스 셀·지수를 보존하면서 2023년 요금 변경 이후 날짜를 제외한다."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .directional import period_dates
from .overnight_sensitivity import describe_comparison

SOURCE = CASE / "results/overnight/bus"
OUT = CASE / "results/overnight/fare_trim"


def trim_periods(base, window, source_days):
    cfg = deepcopy(base)
    for year in [2023, 2024]:
        original_start, original_end = cfg["periods"][f"post{year}"]
        end = window[f"post{year}_end"]
        if not original_start <= end <= original_end:
            raise ValueError("요금 민감도 창은 기존 사후 기간을 줄이는 범위여야 합니다")
        cfg["periods"][f"post{year}"] = [original_start, end]
    return period_dates(cfg, source_days)


def verified_csv(name, audit_name):
    path = SOURCE / name
    audit = json.loads((SOURCE / audit_name).read_text())
    if sha256(path) != audit["outputs"][name]:
        raise ValueError(f"요금 민감도의 기존 집계 해시가 다릅니다: {name}")
    return pd.read_csv(path)


def run():
    cfg = read_yaml("overnight_fare_trim_config.yaml")
    base = read_yaml(cfg["base_config"])
    base.update(minimum_days=cfg["minimum_days"], maximum_coverage_gap=cfg["maximum_coverage_gap"])
    panel_audit = json.loads((SOURCE / "panel_audit.json").read_text())
    all_daily = verified_csv("daily_indices_primary.csv", "sensitivity_audit.json")
    all_daily = all_daily[all_daily.cohort.eq(cfg["cohort"]) & all_daily.aggregation.eq(cfg["aggregation"])
                          & all_daily.daily_threshold.eq(cfg["minimum_daily_coverage"])].copy()
    other_daily = verified_csv("route_group_daily.csv", "route_group_audit.json")
    other_daily = other_daily[other_daily.cohort.eq(cfg["cohort"])
                              & other_daily.group.str.endswith("|other_or_unclassified")].copy()
    other_daily["group"] = other_daily.group.str.split("|", regex=False).str[0]
    data = pd.concat([all_daily.assign(subset="all_preselected"),
                      other_daily.assign(subset="other_or_unclassified")], ignore_index=True)
    if data.duplicated(["band", "subset", "group", "date"]).any():
        raise ValueError("기존 버스 집계의 날짜 키가 중복됩니다")
    source_days = set(panel_audit["source_available_dates"])
    rows, windows = [], {}
    for name, rule in cfg["windows"].items():
        periods = trim_periods(base, rule, source_days)
        windows[name] = periods
        for (band, subset, group), daily in data.groupby(["band", "subset", "group"]):
            if subset not in cfg["subsets"]:
                continue
            for year in [2023, 2024]:
                result = describe_comparison(daily, periods[f"pre{year}"], periods[f"post{year}"], base,
                                             interval=band == "evening")
                rows.append({"window": name, "band": band, "subset": subset, "group": group, "year": year, **result})
    out = pd.DataFrame(rows)
    keys = ["window", "band", "subset", "group"]
    contrasts = out[out.year.eq(2024)].merge(out[out.year.eq(2023)], on=keys, suffixes=("_2024", "_2023"), validate="one_to_one")
    contrasts["change_difference_percentage_points"] = contrasts.change_pct_2024 - contrasts.change_pct_2023
    contrasts["both_quality_pass"] = contrasts.quality_pass_2024 & contrasts.quality_pass_2023
    OUT.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT / "comparisons.csv", index=False)
    contrasts.to_csv(OUT / "year_contrasts.csv", index=False)
    files = ["daily_indices_primary.csv", "route_group_daily.csv", "selected_cells.csv", "panel_audit.json",
             "sensitivity_audit.json", "route_group_audit.json"]
    write_json(OUT / "audit.json", {"completed_at": utcnow(), "config_sha256": sha256(CASE / "overnight_fare_trim_config.yaml"),
                                   "code_sha256": sha256(Path(__file__)), "inputs": {f: sha256(SOURCE / f) for f in files},
                                   "windows": windows, "outputs": {p.name: sha256(p) for p in OUT.glob("*.csv")},
                                   "scope": cfg["interpretation"], "selection": "기존 셀·기준 평균·일별 지수 재사용; 사후 창에 따른 재선택 없음"})
    print(f"요금 시점 기간 민감도 {len(out)}개, 관측 조건 통과 {int(out.quality_pass.sum())}개", flush=True)
