"""모델 동결 뒤에만 버스 시험 원본을 열고 학습기에 고정한 셀로 지연 특징을 연장한다."""

from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

from .common import CASE, read_yaml, sha256, write_json
from .directional import CELL
from .overnight_bus import make_time_panel
from .overnight_bus_data import collect_requests
from .overnight_bus_extract import extract, load_wide
from .overnight_forecast_bus import group_features
from .overnight_forecast_data import BASE, OUT, allowed_months

MANIFEST = CASE / "overnight-forecast-bus-test-sources.json"
SCOPE = "forecast_bus_test"


def collect():
    months = allowed_months("test", read_yaml("overnight_forecast_config.yaml"))
    wanted = {(kind, month) for kind in ["bus_time", "bus_trips"] for month in months}
    collect_requests(wanted, MANIFEST, BASE / "bus_test_raw",
                     "모델·보정기·경보 기준을 동결한 뒤 수집한 2025년 5~8월 버스 시험 특징 원본.")


def prepare():
    cfg = read_yaml("overnight_forecast_config.yaml")
    months = allowed_months("test", cfg)
    entries = json.loads(MANIFEST.read_text())["files"]
    expected = {(kind, month) for kind in ["bus_time", "bus_trips"] for month in months}
    if {(x["kind"], x["month"]) for x in entries} != expected:
        raise ValueError("시험 버스 원본 월 구성이 다릅니다")
    stations = pd.read_csv(CASE / "results/directional/station_registry.csv", dtype={"stop": str, "ars": str})
    hours = read_yaml("overnight_multiyear_config.yaml")["parse_hours"]
    with ProcessPoolExecutor(max_workers=2) as pool:
        audits = list(pool.map(extract, [(e, sorted(stations.stop), hours, SCOPE) for e in entries]))
    # 4월 ZIP의 5월 경계 날짜도 동결 이후에만 시험 특징 결합에 사용한다.
    development = json.loads((CASE / "results/overnight/multiyear/extraction_audit.json").read_text())
    audits.extend(x for x in development if x["month"] == "2025-04")
    write_json(CASE / f"results/overnight/{SCOPE}/extraction_audit.json", audits)
    base = read_yaml("directional_config.yaml")
    base["hours"] = hours
    outputs, quality = [], {}
    for kind in ["bus_time", "bus_trips"]:
        wide, audit = load_wide(SCOPE, kind, ["2025-04", *months])
        if kind == "bus_time":
            panel, repeated = make_time_panel(wide, stations, base)
            keys, prefix = CELL, "recorded_time"
        else:
            mask = wide.duplicated(["date", "route", "stop"], keep=False)
            repeated = int(mask.sum())
            wide = wide[~mask].copy()
            wide["group"] = wide.stop.map(stations.set_index("stop").group)
            wide = wide[wide.group.isin(base["primary_groups"] + base["secondary_groups"])]
            panel = wide.melt(id_vars=["date", "route", "stop", "group"], value_vars=[f"h{h:02}" for h in hours],
                              var_name="hour", value_name="raw_value")
            panel["hour"] = panel.hour.str[1:].astype(int)
            keys, prefix = ["group", "route", "stop", "hour"], "recorded_trips"
        chosen_path = OUT / f"bus_selected_cells_{kind}.csv"
        chosen = pd.read_csv(chosen_path, dtype={c: str for c in keys if c != "hour"})
        values, _, daily = group_features(panel, keys, audit["source_available_dates"], cfg["splits"]["train"][1],
                                         "raw_value", prefix, kind == "bus_trips", selected=chosen)
        outputs.append(values)
        daily.to_csv(OUT / f"bus_test_coverage_{kind}.csv", index=False)
        audit.update(excluded_revisit_rows=repeated, selected_cells=len(chosen), chosen_sha256=sha256(chosen_path))
        quality[kind] = audit
    test = pd.concat(outputs, axis=1).sort_index()
    # 동결된 개발 특징과 4월 겹침을 검사한다. 같은 원본의 값을 시험 자료로 바꾸지 않는다.
    original = BASE / "bus_hourly_features.parquet"
    info = json.loads(original.with_suffix(".json").read_text())
    if sha256(original) != info["sha256"]:
        raise ValueError("개발 버스 특징 해시 불일치")
    prior = pd.read_parquet(original).set_index("interval_start_kst")
    overlap = prior.index.intersection(test.index)
    pd.testing.assert_frame_equal(prior.loc[overlap].sort_index(axis=1), test.loc[overlap].sort_index(axis=1),
                                  check_freq=False, check_dtype=False, atol=1e-10, rtol=1e-10)
    future = test.loc[test.index > prior.index.max()]
    combined = pd.concat([prior, future]).sort_index()
    if combined.index.duplicated().any():
        raise ValueError("시험 버스 특징 시각 중복")
    path = BASE / "bus_hourly_test_features.parquet"
    combined.rename_axis("interval_start_kst").reset_index().to_parquet(path, index=False)
    write_json(path.with_suffix(".json"), {"sha256": sha256(path), "code_sha256": sha256(Path(__file__)),
        "path": str(path.relative_to(CASE)), "rows": len(combined), "development_sha256": info["sha256"]})
    write_json(OUT / "bus_test_feature_audit.json", {"kinds": quality, "feature_sha256": sha256(path),
        "code_sha256": sha256(Path(__file__)), "overlapping_development_hours_verified": len(overlap)})
