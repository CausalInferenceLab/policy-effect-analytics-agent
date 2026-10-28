"""지역 시간별 날씨로 지수 비교의 공통 표본·시간 정렬·관측소 민감도를 점검한다."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .common import read_yaml, sha256, write_json
from .directional import period_dates, standardize_weather
from .overnight_bus import OUT as BUS_OUT
from .overnight_weather import OUT

SCHEMES = {"weekday": ["weekday"], "rain": ["rain_known"],
           "rain_temperature": ["rain_known", "temperature_bin"],
           "rain_temperature_weekday": ["rain_known", "temperature_bin", "weekday"]}


def comparison(frame, before, after, strata, cfg):
    """보존율의 분모를 기상 결측으로 줄이지 않는다."""
    result, cells = standardize_weather(frame, before, after, strata, cfg["minimum_days_per_stratum"])
    before_bus = int(frame[frame.date.isin(before)]["index"].notna().sum())
    after_bus = int(frame[frame.date.isin(after)]["index"].notna().sum())
    result.update(before_bus_valid_days=before_bus, after_bus_valid_days=after_bus,
                  before_retained_of_bus=result["before_used"] / before_bus if before_bus else 0.,
                  after_retained_of_bus=result["after_used"] / after_bus if after_bus else 0.)
    result["support_pass"] = (result["before_used"] >= cfg["minimum_common_days"]
                              and result["after_used"] >= cfg["minimum_common_days"]
                              and result["before_retained_of_bus"] >= cfg["minimum_retained_fraction"]
                              and result["after_retained_of_bus"] >= cfg["minimum_retained_fraction"])
    return result, cells


def run():
    cfg = read_yaml("overnight_config.yaml")
    w = cfg["weather"]
    base = read_yaml(cfg["bus_exploration"]["base_config"])
    weather_audit = json.loads((OUT / "audit.json").read_text())
    if sha256(OUT / "daily_bands.csv") != weather_audit["bands_sha256"]:
        raise ValueError("시간별 기상 밴드 결과 해시 변경")
    weather = pd.read_csv(OUT / "daily_bands.csv")
    if weather.duplicated(["station", "date", "band", "alignment_offset"]).any():
        raise ValueError("시간별 기상 결합 키 중복")
    weather["rain_known"] = weather.rain_group.replace("unknown", np.nan)
    weather["temperature_bin"] = pd.cut(weather.temperature_c, [-np.inf, *w["temperature_edges_c"], np.inf], right=False)
    bus_audit = json.loads((BUS_OUT / "panel_audit.json").read_text())
    calendar = period_dates(base)
    source = period_dates(base, set(bus_audit["source_available_dates"]))
    daily = pd.read_csv(BUS_OUT / "daily_indices_primary.csv")
    daily = daily[daily.aggregation.eq("equal_cells") & daily.daily_threshold.eq(cfg["bus_exploration"]["primary_coverage"])]
    daily["weekday"] = pd.to_datetime(daily.date).dt.dayofweek
    quality = pd.read_csv(BUS_OUT / "aggregation_comparisons.csv")
    quality = quality[quality.aggregation.eq("equal_cells") & quality.daily_threshold.eq(cfg["bus_exploration"]["primary_coverage"])]
    quality = quality.set_index(["band", "cohort", "group", "comparison"]).quality_pass
    results, common, periods_weather = [], [], []
    for (station, offset), met in weather.groupby(["station", "alignment_offset"]):
        joined = daily.merge(met, on=["date", "band"], how="left", validate="many_to_one")
        for (band, cohort, group), frame in joined.groupby(["band", "cohort", "group"]):
            periods = calendar if cohort == "2024_pre_calendar" else source
            contrasts = [("summer2024", "pre2024", "post2024"), ("autumn2024", "pre2024", "autumn2024")]
            if cohort != "2024_pre_calendar":
                contrasts.insert(0, ("summer2023", "pre2023", "post2023"))
            for label, before, after in contrasts:
                for scheme in w["schemes"]:
                    stats, cells = comparison(frame, periods[before], periods[after], SCHEMES[scheme], w)
                    index_pass = bool(quality.loc[(band, cohort, group, label)])
                    tags = {"station": station, "alignment_offset": offset, "band": band, "cohort": cohort,
                            "group": group, "comparison": label, "scheme": scheme}
                    results.append({**tags, **stats, "index_quality_pass": index_pass,
                                    "usable_comparison": index_pass and stats["support_pass"]})
                    if not cells.empty:
                        common.append(cells.assign(**tags))
        for period, dates in source.items():
            for band, met_band in met[met.date.isin(dates)].groupby("band"):
                periods_weather.append({"station": station, "alignment_offset": offset, "period": period, "band": band,
                    "days": len(met_band), "rain_observed_days": int(met_band.precipitation_mm.notna().sum()),
                    "rain_ge1mm_days": int(met_band.precipitation_mm.ge(1).sum()), "rain_mm_sum": met_band.precipitation_mm.sum(min_count=1),
                    "temperature_observed_days": int(met_band.temperature_c.notna().sum()), "temperature_mean_c": met_band.temperature_c.mean()})
        print(f"기상 공통 표본: 관측소 {station}, 시간 정렬 {offset:+d} 완료", flush=True)
    result = pd.DataFrame(results)
    result.to_csv(OUT / "comparisons.csv", index=False)
    pd.concat(common, ignore_index=True).to_csv(OUT / "common_strata.csv", index=False)
    pd.DataFrame(periods_weather).to_csv(OUT / "period_weather.csv", index=False)
    write_json(OUT / "comparison_audit.json", {"rows": len(result), "usable_rows": int(result.usable_comparison.sum()),
        "configuration": w, "code_sha256": sha256(Path(__file__)), "weather_bands_sha256": sha256(OUT / "daily_bands.csv"),
        "bus_daily_sha256": sha256(BUS_OUT / "daily_indices_primary.csv"),
        "collection_complete": weather_audit["collection_complete"], "failed_requests": weather_audit["failed_requests"],
        "outputs": {name: sha256(OUT / name) for name in ["comparisons.csv", "common_strata.csv", "period_weather.csv"]},
        "note": "기상 분포 표준화는 기술 비교. 관측한 날씨가 정책 외 모든 교란을 제거하지 않음. 실패한 표본 조건도 모두 출력."})
