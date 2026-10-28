"""기존 고정 셀의 2024·2025년 비교를 관측소·시각 정렬별 공통 날씨 분포로 점검한다."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .overnight_persistence_weather_data import configuration
from .overnight_weather_analysis import SCHEMES, comparison


def run():
    cfg, _, _ = configuration()
    out = CASE / cfg["outputs"]
    source = CASE / "results/overnight/persistence"
    bus_audit = json.loads((source / "audit.json").read_text())
    for name in ["daily_equal_cells.csv", "comparisons.csv"]:
        if sha256(source / name) != bus_audit["outputs"][name]:
            raise ValueError("연장 버스 결과 해시 불일치")
    daily = pd.read_csv(source / "daily_equal_cells.csv")
    daily = daily[daily.cohort.eq(cfg["bus_cohort"]) & daily.subset.isin(cfg["bus_subsets"]) & daily.aggregation.eq(cfg["aggregation"])].copy()
    daily["weekday"] = pd.to_datetime(daily.date).dt.dayofweek
    quality = pd.read_csv(source / "comparisons.csv")
    quality = quality[quality.cohort.eq(cfg["bus_cohort"]) & quality.aggregation.eq(cfg["aggregation"])]
    quality = quality.set_index(["band", "subset", "group", "comparison"]).quality_pass
    old_path = CASE / "results/overnight/weather/daily_bands.csv"
    old_audit = json.loads((old_path.parent / "audit.json").read_text())
    if sha256(old_path) != old_audit["bands_sha256"]:
        raise ValueError("기존 기상 결과 해시 불일치")
    new_path = out / "daily_bands_2025.csv"
    new_audit = json.loads((out / "preparation_audit.json").read_text())
    if sha256(new_path) != new_audit["outputs"][new_path.name]:
        raise ValueError("추가 기상 결과 해시 불일치")
    old = pd.read_csv(old_path)
    weather = pd.concat([old[old.date.str.startswith("2024")], pd.read_csv(new_path)], ignore_index=True)
    if weather.duplicated(["station", "date", "band", "alignment_offset"]).any():
        raise ValueError("기상 결합 키 중복")
    weather["rain_known"] = weather.rain_group.replace("unknown", np.nan)
    weather["temperature_bin"] = pd.cut(weather.temperature_c, [-np.inf, *cfg["temperature_edges_c"], np.inf], right=False)
    calendar = bus_audit["calendar"]
    definitions = read_yaml(cfg["periods_from"])["comparisons"]
    rows, strata, period_rows = [], [], []
    for (station, offset), met in weather.groupby(["station", "alignment_offset"]):
        joined = daily.merge(met, on=["date", "band"], how="left", validate="many_to_one")
        for (band, subset, group), frame in joined.groupby(["band", "subset", "group"]):
            for label, (before, after) in definitions.items():
                for scheme in cfg["schemes"]:
                    stats, cells = comparison(frame, calendar[before], calendar[after], SCHEMES[scheme], cfg)
                    passed = bool(quality.loc[(band, subset, group, label)])
                    tags = {"station": station, "alignment_offset": offset, "band": band, "subset": subset,
                            "group": group, "comparison": label, "scheme": scheme}
                    rows.append({**tags, **stats, "index_quality_pass": passed, "usable_comparison": passed and stats["support_pass"]})
                    if not cells.empty:
                        strata.append(cells.assign(**tags))
        for period, dates in calendar.items():
            for band, band_data in met[met.date.isin(dates)].groupby("band"):
                period_rows.append({"station": station, "alignment_offset": offset, "period": period, "band": band,
                    "expected_days": len(dates), "observed_rain_days": int(band_data.precipitation_mm.notna().sum()),
                    "rain_ge1mm_days": int(band_data.precipitation_mm.ge(1).sum()),
                    "rain_mm_sum": band_data.precipitation_mm.sum(min_count=1),
                    "temperature_observed_days": int(band_data.temperature_c.notna().sum()), "temperature_mean_c": band_data.temperature_c.mean()})
        print(f"2025 연장 기상 비교: {station}, 정렬 {offset:+d}", flush=True)
    result = pd.DataFrame(rows)
    result.to_csv(out / "comparisons.csv", index=False)
    pd.concat(strata, ignore_index=True).to_csv(out / "common_strata.csv", index=False)
    pd.DataFrame(period_rows).to_csv(out / "period_weather.csv", index=False)
    paths = [source / "audit.json", source / "daily_equal_cells.csv", source / "comparisons.csv", old_path, new_path,
             out / "preparation_audit.json", CASE / "gangnam/overnight_weather_analysis.py", CASE / "gangnam/directional.py"]
    write_json(out / "comparison_audit.json", {"completed_at": utcnow(), "configuration": cfg,
                "code_sha256": sha256(Path(__file__)), "comparisons": len(result), "usable": int(result.usable_comparison.sum()),
                "inputs": {str(path.relative_to(CASE)): sha256(path) for path in paths},
                "outputs": {name: sha256(out / name) for name in ["comparisons.csv", "common_strata.csv", "period_weather.csv"]},
                "collection_complete": new_audit["collection_complete"],
                "interpretation": "같은 관측 날씨 층의 기술적 표준화. 관측소·시각·층 선택의 실패도 보고하며 인과 조정을 주장하지 않음."})
