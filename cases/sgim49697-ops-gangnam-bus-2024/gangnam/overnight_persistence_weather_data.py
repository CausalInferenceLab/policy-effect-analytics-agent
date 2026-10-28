"""기존 기상 원본과 결과를 보존하며 2025년 AWS 시간 응답을 수집·검증한다."""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .overnight_weather import (
    FIELDS_VALUES,
    RAW,
    deduplicate,
    fetch_one,
    parse_response,
    request_endpoints,
)

MANIFEST = CASE / "overnight-persistence-weather-sources.json"


def configuration():
    cfg = read_yaml("overnight_persistence_weather_config.yaml")
    if cfg["locked_year"] != 2026 or not cfg["months"] or any(not month.startswith("2025-") for month in cfg["months"]):
        raise ValueError("추가 기상은 지정된 2025년 범위만 허용합니다")
    parent = read_yaml(cfg["weather_base_config"])
    return cfg, parent["weather"], parent["bus_exploration"]["bands"]


def collect():
    cfg, weather, _ = configuration()
    RAW.mkdir(parents=True, exist_ok=True)
    jobs = [(station, stamp, weather) for station in cfg["stations"]
            for stamp in request_endpoints(cfg["months"], weather["request_stride_hours"])]
    entries, failures = {}, []
    wanted = {(station, str(stamp)) for station, stamp, _ in jobs}
    if MANIFEST.exists():
        old = json.loads(MANIFEST.read_text())
        if old["months"] != cfg["months"] or old["stations"] != cfg["stations"]:
            raise ValueError("추가 기상 명세의 월·지점 설정 변경")
    with ThreadPoolExecutor(max_workers=cfg["download_workers"]) as pool:
        futures = {pool.submit(fetch_one, job): job for job in jobs}
        for i, future in enumerate(as_completed(futures), 1):
            station, endpoint, _ = futures[future]
            try:
                entry = future.result()
                key = (entry["station"], entry["endpoint"])
                if key not in wanted or entry["bytes"] > cfg["maximum_response_bytes"]:
                    raise ValueError("요청 범위 또는 응답 크기 불일치")
                entries[key] = entry
            except Exception as exc:
                failures.append({"station": station, "endpoint": str(endpoint), "error": f"{type(exc).__name__}: {str(exc)[:250]}"})
            write_json(MANIFEST, {"description": "2025년 연장 분석용 AWS 참조 응답; 이전 기상 명세·결과를 보존함.",
                                  "months": cfg["months"], "stations": cfg["stations"], "expected_requests": len(jobs),
                                  "files": sorted(entries.values(), key=lambda x: (x["station"], x["endpoint"])),
                                  "failures": failures, "updated_at": utcnow()})
            if i % 20 == 0 or i == len(jobs):
                print(f"2025 기상 수집 {i}/{len(jobs)}, 검증 실패 {len(failures)}", flush=True)
    if not entries:
        raise ValueError("검증된 2025년 기상 응답이 없습니다")
    if failures:
        print("실패 응답은 사용하지 않으며 예정 시간의 결측으로 남깁니다.", flush=True)


def daily_bands(data, bands, offsets):
    rows = []
    for station, station_data in data.groupby("station"):
        for band, hours in bands.items():
            for offset in offsets:
                part = station_data[station_data.hour.isin([hour + offset for hour in hours])]
                for date, day in part.groupby("date"):
                    rain = day.precipitation_1h_mm
                    complete = len(day) == len(hours) and rain.notna().all()
                    total = float(rain.sum()) if complete else np.nan
                    rows.append({"station": int(station), "date": date, "band": band, "alignment_offset": offset,
                                 "expected_hours": len(hours), "precipitation_observed": int(rain.notna().sum()),
                                 "precipitation_mm": total, "rain_group": "unknown" if not complete else ("ge1mm" if total >= 1 else "lt1mm"),
                                 "temperature_observed": int(day.temperature_c.notna().sum()),
                                 "temperature_c": day.temperature_c.mean() if len(day) == len(hours) and day.temperature_c.notna().all() else np.nan})
    return pd.DataFrame(rows)


def prepare():
    cfg, weather, bands = configuration()
    manifest = json.loads(MANIFEST.read_text())
    if manifest["months"] != cfg["months"] or manifest["stations"] != cfg["stations"]:
        raise ValueError("수집 기상 설정과 분석 설정 불일치")
    expected_keys = {(s, str(t)) for s in cfg["stations"] for t in request_endpoints(cfg["months"], weather["request_stride_hours"])}
    frames, used = [], set()
    for entry in manifest["files"]:
        key = (entry["station"], entry["endpoint"])
        path = CASE / entry["path"]
        if key not in expected_keys or key in used or not path.resolve().is_relative_to(RAW.resolve()) or sha256(path) != entry["sha256"]:
            raise ValueError("2025 기상 응답 키·원본 경로·해시 오류")
        used.add(key)
        frames.append(parse_response(json.loads(path.read_text()), entry["station"], entry["endpoint"], weather["response_hours"]))
    if not frames:
        raise ValueError("사용할 추가 기상 응답이 없습니다")
    data, audit = deduplicate(pd.concat(frames, ignore_index=True))
    data = data[data.date.str[:7].isin(cfg["months"])]
    hours = [str(t) for month in cfg["months"] for t in pd.date_range(month + "-01", periods=pd.Period(month).days_in_month * 24, freq="h")]
    grid = pd.MultiIndex.from_product([cfg["stations"], hours], names=["station", "datetime_local"])
    data = data.set_index(["station", "datetime_local"]).reindex(grid).reset_index()
    stamps = pd.to_datetime(data.datetime_local)
    data["date"], data["hour"], data["month"] = stamps.dt.strftime("%Y-%m-%d"), stamps.dt.hour, stamps.dt.strftime("%Y-%m")
    path = CASE / cfg["raw_hourly"]
    path.parent.mkdir(parents=True, exist_ok=True)
    data.to_parquet(path, index=False)
    out = CASE / cfg["outputs"]
    out.mkdir(parents=True, exist_ok=True)
    daily_bands(data, bands, cfg["alignment_offsets_hours"]).to_csv(out / "daily_bands_2025.csv", index=False)
    quality = data.groupby(["station", "month"]).agg(expected_hours=("hour", "size"),
                   temperature_observed=("temperature_c", "count"), precipitation_observed=("precipitation_1h_mm", "count"))
    quality.to_csv(out / "hourly_quality.csv")
    states = []
    for field in FIELDS_VALUES:
        counts = data.groupby(["station", "month", field + "_status"], dropna=False).size()
        states.extend({"station": s, "month": m, "field": field, "status": status, "hours": int(count)}
                      for (s, m, status), count in counts.items())
    pd.DataFrame(states).to_csv(out / "field_status_counts.csv", index=False)
    write_json(out / "preparation_audit.json", {**audit, "completed_at": utcnow(), "configuration": cfg,
                    "expected_requests": len(expected_keys), "accepted_requests": len(used),
                    "missing_request_keys": [list(key) for key in sorted(expected_keys - used)], "failures": manifest["failures"],
                    "collection_complete": len(used) == len(expected_keys), "hourly_rows": len(data),
                    "hourly_path": str(path.relative_to(CASE)), "hourly_sha256": sha256(path),
                    "source_manifest_sha256": sha256(MANIFEST), "code_sha256": sha256(Path(__file__)),
                    "parser_sha256": sha256(CASE / "gangnam/overnight_weather.py"),
                    "outputs": {name: sha256(out / name) for name in ["daily_bands_2025.csv", "hourly_quality.csv", "field_status_counts.csv"]}})
