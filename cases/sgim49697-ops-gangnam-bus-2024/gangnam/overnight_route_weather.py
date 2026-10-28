"""사전 관측으로 고정한 노선군별 지수를 지역 날씨의 공통 표본에서 다시 비교한다."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, write_json
from .directional import period_dates
from .overnight_bus import OUT as BUS_OUT
from .overnight_weather import OUT as WEATHER_OUT
from .overnight_weather_analysis import SCHEMES, comparison


def run():
    cfg = read_yaml("overnight_config.yaml")
    w = cfg["weather"]
    base = read_yaml(cfg["bus_exploration"]["base_config"])
    daily = pd.read_csv(BUS_OUT / "route_group_daily.csv")
    daily = daily[daily.cohort.eq("common_pre_source_days")].copy()
    daily["weekday"] = pd.to_datetime(daily.date).dt.dayofweek
    quality = pd.read_csv(BUS_OUT / "route_group_comparisons.csv")
    quality = quality[quality.cohort.eq("common_pre_source_days") & quality.aggregation.eq("equal_cells")].copy()
    quality["group"] = quality.direction + "|" + quality.policy_group
    quality = quality.set_index(["band", "group", "comparison"]).quality_pass
    route_audit = json.loads((BUS_OUT / "route_group_audit.json").read_text())
    for name in ["route_group_daily.csv", "route_group_comparisons.csv"]:
        if sha256(BUS_OUT / name) != route_audit["outputs"][name]:
            raise ValueError("노선군 결과 해시 불일치")
    weather_audit = json.loads((WEATHER_OUT / "audit.json").read_text())
    if sha256(WEATHER_OUT / "daily_bands.csv") != weather_audit["bands_sha256"]:
        raise ValueError("기상 밴드 결과 해시 불일치")
    weather = pd.read_csv(WEATHER_OUT / "daily_bands.csv")
    weather["rain_known"] = weather.rain_group.replace("unknown", np.nan)
    weather["temperature_bin"] = pd.cut(weather.temperature_c, [-np.inf, *w["temperature_edges_c"], np.inf], right=False)
    bus_audit = json.loads((BUS_OUT / "panel_audit.json").read_text())
    periods = period_dates(base, set(bus_audit["source_available_dates"]))
    rows, common = [], []
    for (station, offset), met in weather.groupby(["station", "alignment_offset"]):
        joined = daily.merge(met, on=["date", "band"], how="left", validate="many_to_one")
        for (band, group), frame in joined.groupby(["band", "group"]):
            direction, policy_group = group.split("|")
            for label, before, after in [("summer2023", "pre2023", "post2023"), ("summer2024", "pre2024", "post2024"), ("autumn2024", "pre2024", "autumn2024")]:
                for scheme in w["schemes"]:
                    stats, cells = comparison(frame, periods[before], periods[after], SCHEMES[scheme], w)
                    passed = bool(quality.loc[(band, group, label)])
                    tags = {"station": station, "alignment_offset": offset, "band": band, "direction": direction,
                            "policy_group": policy_group, "comparison": label, "scheme": scheme}
                    rows.append({**tags, **stats, "index_quality_pass": passed,
                                 "usable_comparison": passed and stats["support_pass"]})
                    if not cells.empty:
                        common.append(cells.assign(**tags))
        print(f"노선군 기상 비교: {station}, {offset:+d}", flush=True)
    pd.DataFrame(rows).to_csv(BUS_OUT / "route_group_weather.csv", index=False)
    pd.concat(common, ignore_index=True).to_csv(BUS_OUT / "route_group_weather_strata.csv", index=False)
    write_json(BUS_OUT / "route_group_weather_audit.json", {"configuration": w, "code_sha256": sha256(Path(__file__)),
        "cohort": "common_pre_source_days", "comparisons": len(rows),
        "inputs": {str(p.relative_to(CASE)): sha256(p) for p in [BUS_OUT / "route_group_daily.csv", BUS_OUT / "route_group_comparisons.csv", WEATHER_OUT / "daily_bands.csv"]},
        "outputs": {name: sha256(BUS_OUT / name) for name in ["route_group_weather.csv", "route_group_weather_strata.csv"]}})
