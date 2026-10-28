"""공개 AWS 화면의 과거 시간자료를 시각·지점 검증 후 수집하고 기상 비교 입력을 만든다."""

from __future__ import annotations

import json
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .topis import session

RAW = CASE / "data/overnight/weather"
OUT = CASE / "results/overnight/weather"
MANIFEST = CASE / "overnight-weather-sources.json"
FIELDS = {"awsTmp": ("temperature_c", -70, 60), "awsPcpHr1": ("precipitation_1h_mm", 0, 500),
          "awsReh": ("humidity_pct", 0, 100), "awsWs10": ("wind_speed_ms", 0, 100)}


def number(value, low, high):
    """문자 결측·범위 밖 값과 숫자 0을 구분하고 원본 문자열은 호출자에서 보존한다."""
    if value is None or str(value).strip() in {"", "-"}:
        return np.nan, "blank"
    if str(value).strip() == ".":
        # 공개 응답에서 확인한 비수치 자리표시자. 무강수 또는 정상 QC로 해석하지 않는다.
        return np.nan, "non_numeric_placeholder"
    try:
        result = float(str(value).replace(",", ""))
    except ValueError as exc:
        raise ValueError(f"예상하지 못한 기상 수치 표기: {value!r}") from exc
    if not math.isfinite(result) or not low <= result <= high:
        return np.nan, "outside_range"
    return result, "numeric"


def parse_response(data, station, endpoint, hours=60):
    endpoint = pd.Timestamp(endpoint).as_unit("ns")
    expected = endpoint.strftime("%Y%m%d%H%M")
    if data.get("dataTm") != expected or str(data.get("stnId")) != str(station) or data.get("db") != "MINDB_60M":
        raise ValueError("기상 응답의 시각·지점·간격이 요청과 다릅니다")
    items = data.get("items")
    if not isinstance(items, list) or len(items) > hours:
        raise ValueError("기상 시간자료 응답 구조 변경")
    rows, seen = [], set()
    for item in items:
        stamp = pd.to_datetime(item["tm"], format="%Y%m%d%H%M", errors="raise").as_unit("ns")
        if (str(item["awsStnId"]) != str(station) or stamp.minute != 0 or stamp in seen
                or not endpoint - timedelta(hours=hours - 1) <= stamp <= endpoint):
            raise ValueError("기상 행의 날짜·지점·중복 오류")
        seen.add(stamp)
        row = {"station": int(station), "datetime_local": str(stamp), "date": str(stamp.date()), "hour": stamp.hour,
               "station_name": item.get("awsStnName"), "service_fault_raw": item.get("awsTroblKnd"),
               "precipitation_sensor_raw": item.get("awsPty"), "daily_precipitation_raw": item.get("awsPcpDay"),
               "response_latitude": item.get("lat"), "response_longitude": item.get("lon")}
        issue = item.get("awsTroblKnd") in {"장애", "비장애중단"}
        row["service_known_issue"] = issue
        for raw, (name, low, high) in FIELDS.items():
            if raw not in item:
                raise ValueError(f"기상 필드 누락: {raw}")
            value, status = number(item[raw], low, high)
            row[name + "_raw"], row[name + "_status"] = item[raw], status
            row[name] = np.nan if issue else value
        rows.append(row)
    return pd.DataFrame(rows)


def request_endpoints(months, stride=48):
    endpoints = set()
    for month in months:
        start = pd.Timestamp(month + "-01").as_unit("ns")
        end = start + pd.offsets.MonthEnd() + timedelta(hours=23)
        endpoints.update(pd.date_range(start + timedelta(hours=stride - 1), end, freq=f"{stride}h"))
        endpoints.add(end)
    return sorted(endpoints)


def fetch_one(job):
    station, endpoint, cfg = job
    key = f"{station}_{endpoint.strftime('%Y%m%d%H%M')}"
    path = RAW / f"{key}.json"
    meta_path = RAW / f"{key}.source.json"
    if path.exists():
        if not meta_path.exists():
            raise ValueError(f"출처 없는 기상 캐시: {key}")
        entry = json.loads(meta_path.read_text())
        if sha256(path) != entry["sha256"]:
            raise ValueError(f"기상 원본 해시 변경: {key}")
        parse_response(json.loads(path.read_text()), station, endpoint, cfg["response_hours"])
        return entry
    params = {"db": "MINDB_60M", "tm": endpoint.strftime("%Y.%m.%d %H:%M"), "stnId": str(station),
              "sidoCode": "1100000000", "sort": "0", "config": ""}
    with session() as client:
        client.headers["Referer"] = cfg["source"]
        response = client.get(cfg["endpoint"], params=params, timeout=(15, 60))
        response.raise_for_status()
        if len(response.content) > 2 * 1024**2:
            raise ValueError("기상 응답이 2 MiB 한도를 넘습니다")
        data = response.json()
        frame = parse_response(data, station, endpoint, cfg["response_hours"])
        entry = {"station": station, "endpoint": str(endpoint), "source": cfg["source"], "url": response.url,
                 "request": params, "path": str(path.relative_to(CASE)), "bytes": len(response.content),
                 "rows": len(frame), "retrieved_at": utcnow(), "station_metadata_from_response": data.get("stnInfo")}
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(response.content)
        entry["sha256"] = sha256(temporary)
        temporary.replace(path)
        write_json(meta_path, entry)
    time.sleep(cfg["endpoint_delay_seconds"])
    return entry


def collect():
    cfg = read_yaml("overnight_config.yaml")
    w = cfg["weather"]
    months = read_yaml(w["months_from"])["months"]
    RAW.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [(s, end, w) for s in w["stations"] for end in request_endpoints(months, w["request_stride_hours"])]
    entries, failures = {}, []
    if MANIFEST.exists():
        entries = {(x["station"], x["endpoint"]): x for x in json.loads(MANIFEST.read_text())["files"]}
    def save():
        write_json(MANIFEST, {"description": "공개 날씨누리 AWS 화면의 과거 60분 간격 응답. 공식 QC 확정 자료와 구분.",
                              "files": sorted(entries.values(), key=lambda x: (x["station"], x["endpoint"])), "failures": failures})
    with ThreadPoolExecutor(max_workers=cfg["resources"]["download_workers"]) as pool:
        futures = {pool.submit(fetch_one, job): job for job in jobs}
        for i, future in enumerate(as_completed(futures), 1):
            station, endpoint, _ = futures[future]
            try:
                entry = future.result()
                entries[(station, str(endpoint))] = entry
            except Exception as exc:
                failures.append({"station": station, "endpoint": str(endpoint), "error": f"{type(exc).__name__}: {str(exc)[:250]}"})
            save()
            if i % 20 == 0 or i == len(jobs):
                print(f"시간 기상: {i}/{len(jobs)} 응답, 실패 {len(failures)}", flush=True)
    if failures:
        raise ValueError(f"기상 수집 {len(failures)}건 실패. 명세를 확인하고 재개하세요")


def deduplicate(frame):
    keys = ["station", "datetime_local"]
    cols = [*FIELDS_VALUES, "service_known_issue"]
    repeated = frame.duplicated(keys, keep=False)
    duplicates = frame.loc[repeated]
    conflicts = duplicates.groupby(keys)[cols].nunique(dropna=False).gt(1).any(axis=1)
    bad = set(conflicts[conflicts].index)
    mask = [key in bad for key in zip(frame.station, frame.datetime_local, strict=True)]
    clean = frame.loc[~np.asarray(mask)].drop_duplicates(keys)
    return clean, {"overlap_rows": int(repeated.sum()), "conflicting_keys_quarantined": len(bad)}


FIELDS_VALUES = [x[0] for x in FIELDS.values()]


def prepare():
    cfg = read_yaml("overnight_config.yaml")
    manifest = json.loads(MANIFEST.read_text())
    w, entries = cfg["weather"], manifest["files"]
    months = read_yaml(w["months_from"])["months"]
    frames = []
    for entry in entries:
        path = CASE / entry["path"]
        if not path.resolve().is_relative_to(RAW.resolve()) or sha256(path) != entry["sha256"]:
            raise ValueError("시간 기상 원본 경로·해시 불일치")
        frames.append(parse_response(json.loads(path.read_text()), entry["station"], entry["endpoint"], w["response_hours"]))
    if not frames or all(frame.empty for frame in frames):
        raise ValueError("분석할 시간 기상자료가 없습니다")
    d, audit = deduplicate(pd.concat(frames, ignore_index=True))
    d = d[d.date.str[:7].isin(months)].copy()
    expected_hours = [str(t) for month in months for t in pd.date_range(month + "-01", periods=pd.Period(month).days_in_month * 24, freq="h")]
    expected = pd.MultiIndex.from_product([w["stations"], expected_hours], names=["station", "datetime_local"])
    d = d.set_index(["station", "datetime_local"]).reindex(expected).reset_index()
    stamps = pd.to_datetime(d.datetime_local)
    d["date"], d["hour"], d["month"] = stamps.dt.strftime("%Y-%m-%d"), stamps.dt.hour, stamps.dt.strftime("%Y-%m")
    target = RAW / "hourly.parquet"
    d.to_parquet(target, index=False)
    quality = d.groupby(["station", "month"]).agg(expected_hours=("hour", "size"),
        temperature_observed=("temperature_c", "count"), precipitation_observed=("precipitation_1h_mm", "count"),
        humidity_observed=("humidity_pct", "count"), wind_observed=("wind_speed_ms", "count"))
    quality.to_csv(OUT / "hourly_quality.csv")
    statuses = []
    for name in FIELDS_VALUES:
        count = d.groupby(["station", "month", name + "_status"], dropna=False).size()
        statuses.extend({"station": s, "month": m, "field": name, "status": status, "hours": int(n)}
                        for (s, m, status), n in count.items())
    pd.DataFrame(statuses).to_csv(OUT / "field_status_counts.csv", index=False)
    rows = []
    for station, station_data in d.groupby("station"):
        for band, hours in cfg["bus_exploration"]["bands"].items():
            for offset in w["alignment_offsets_hours"]:
                part = station_data[station_data.hour.isin([h + offset for h in hours])]
                for date, day in part.groupby("date"):
                    rain = day.precipitation_1h_mm
                    complete = len(day) == len(hours) and rain.notna().all()
                    total = float(rain.sum()) if complete else np.nan
                    rows.append({"station": int(station), "date": date, "band": band, "alignment_offset": offset,
                        "expected_hours": len(hours), "precipitation_observed": int(rain.notna().sum()), "precipitation_mm": total,
                        "rain_group": "unknown" if not complete else ("ge1mm" if total >= 1 else "lt1mm"),
                        "temperature_observed": int(day.temperature_c.notna().sum()),
                        "temperature_c": day.temperature_c.mean() if day.temperature_c.notna().sum() == len(hours) else np.nan,
                        "humidity_pct": day.humidity_pct.mean(), "wind_speed_ms": day.wind_speed_ms.mean()})
    bands = pd.DataFrame(rows)
    bands.to_csv(OUT / "daily_bands.csv", index=False)
    audit.update(raw_responses=len(entries), failed_requests=manifest.get("failures", []),
                 collection_complete=not manifest.get("failures"), expected_hourly_rows=len(d), months=months, stations=w["stations"],
                 configuration={"weather": w, "bands": cfg["bus_exploration"]["bands"], "months": months},
                 source_manifest_sha256=sha256(MANIFEST), code_sha256=sha256(Path(__file__)), config_sha256=sha256(CASE / "overnight_config.yaml"),
                 hourly_path=str(target.relative_to(CASE)), hourly_sha256=sha256(target),
                 band_rows=len(bands), bands_sha256=sha256(OUT / "daily_bands.csv"),
                 note="웹 참조 관측자료. 공개 화면의 과거 시각을 검증했으나 공식 역사적 QC 파일은 미확보. 좌표는 별도 이력 확인 전 현재 응답 메타데이터로만 취급.")
    write_json(OUT / "audit.json", audit)
    print(f"시간 기상 준비: {len(d):,}행, 기상 비교 밴드 {len(bands):,}행", flush=True)
