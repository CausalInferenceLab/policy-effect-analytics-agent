"""사전 고정 도로 표본과 교통량 지점의 2025년 지속성을 같은 계절 창에서 계산한다."""

import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .overnight_persistence import periods
from .overnight_road_context import speed_daily, volume_entry
from .overnight_road_persistence_data import MANIFEST, RAW
from .overnight_sensitivity import describe_comparison

OUT = CASE / "results/overnight/road_persistence"
META = ["road", "시점명", "종점명", "direction", "length"]


def metadata_check(expected, observed, months):
    """변경·누락 링크를 대체하지 않고 원래 선택 분모의 메타데이터 판정을 반환한다."""
    if expected.link_id.duplicated().any() or observed.duplicated(["link_id", "month"]).any():
        raise ValueError("도로 메타데이터 키 중복")
    grid = expected.merge(pd.DataFrame({"month": months}), how="cross")
    merged = grid.merge(observed[["link_id", "month", *META]], on=["link_id", "month"], how="left",
                        suffixes=("_original", "_observed"), validate="one_to_one", indicator=True)
    merged["metadata_present"] = merged["_merge"].eq("both")
    for field in META:
        merged[field + "_agrees"] = merged[field + "_original"].eq(merged[field + "_observed"])
    merged["metadata_pass"] = merged.metadata_present & merged[[field + "_agrees" for field in META]].all(axis=1)
    return merged.drop(columns="_merge")


def read_speed(cfg):
    selected_path = CASE / cfg["original_selection"]
    original_audit_path = CASE / cfg["original_selection_audit"]
    original = json.loads(original_audit_path.read_text())
    link_path = selected_path.parent / "stable_links.csv"
    for path in [selected_path, link_path]:
        if sha256(path) != original["outputs"][path.name]:
            raise ValueError("원래 도로 선택·메타데이터 해시 변경")
    selected = pd.read_csv(selected_path, dtype={"link_id": str})
    expected = pd.read_csv(link_path, dtype={"link_id": str})
    sources = []
    for name in cfg["speed_manifests"]:
        sources.extend(e for e in json.loads((CASE / name).read_text()) if e["month"] in cfg["months"])
    if len(sources) != len(cfg["months"]) or {e["month"] for e in sources} != set(cfg["months"]):
        raise ValueError("도로 캐시의 월 범위 누락·중복")
    frames, metadata = [], []
    for entry in sources:
        if pd.Period(entry["month"]).year >= cfg["locked_year"]:
            raise ValueError("잠금 연도 속도값 접근 금지")
        path = CASE / entry["path"]
        if not path.resolve().is_relative_to((CASE / "data/overnight/forecast/roads/processed").resolve()):
            raise ValueError("도로 캐시가 지정 경로 밖입니다")
        if sha256(path) != entry["sha256"]:
            raise ValueError("도로 캐시 해시 불일치")
        data = pd.read_parquet(path)
        if set(data.interval_start_kst.dt.strftime("%Y-%m")) != {entry["month"]}:
            raise ValueError("도로 캐시의 날짜 범위 불일치")
        data["date"] = data.interval_start_kst.dt.strftime("%Y-%m-%d")
        data["hour"] = data.interval_start_kst.dt.hour
        data["speed_kmh"] = data.speed_kmh.where(data.is_valid & data.speed_kmh.gt(0))
        frames.append(data[data.link_id.isin(expected.link_id)][["date", "hour", "link_id", "speed_kmh"]])
        metadata.extend({**row, "month": entry["month"]} for row in entry["metadata"])
    data = pd.concat(frames, ignore_index=True)
    if data.duplicated(["date", "hour", "link_id"]).any():
        raise ValueError("도로 링크·시간 중복")
    meta = pd.DataFrame(metadata).rename(columns={"링크아이디": "link_id", "도로명": "road", "방향": "direction", "거리": "length"})
    meta["length"] = pd.to_numeric(meta.length, errors="raise")
    if meta.length.le(0).any():
        raise ValueError("도로 링크 길이는 양수여야 합니다")
    checked = metadata_check(expected, meta, cfg["months"])
    return data, selected, checked, [{k: entry[k] for k in ["month", "path", "sha256", "source_sha256"]} for entry in sources]


def run():
    cfg = read_yaml("overnight_road_persistence_config.yaml")
    calendar_cfg = read_yaml(cfg["calendar_from"])
    calendar = periods(calendar_cfg)
    dates = sorted({date for values in calendar.values() for date in values})
    speed, selected, checked, sources = read_speed(cfg)
    entries = json.loads(MANIFEST.read_text())["files"]
    if len(entries) != len(cfg["months"]) or {entry["month"] for entry in entries} != set(cfg["months"]):
        raise ValueError("교통량 명세의 월 범위 불일치")
    workers = cfg["resources"]["parser_workers"]
    if workers not in {1, 2}:
        raise ValueError("교통량 동시 파서는 최대 2개")
    with ProcessPoolExecutor(max_workers=workers) as pool:
        parsed = list(pool.map(volume_entry, [(entry, cfg) for entry in entries]))
    volume = pd.concat([part for part, _ in parsed], ignore_index=True)
    if volume.duplicated(["date", "point", "direction", "hour"]).any():
        raise ValueError("교통량 지점·방향·시각 중복")
    volume["month"] = volume.date.str[:7]
    volume_meta = volume[["month", "point", "point_name", "direction", "description"]].drop_duplicates()
    rows, dailies = [], []
    link_pass = checked.groupby("link_id").metadata_pass.all()

    def compare(daily, labels, valid_meta, interval):
        dailies.append(daily.assign(**labels, metadata_pass=valid_meta))
        for name, (before, after) in cfg["comparisons"].items():
            result = describe_comparison(daily, calendar[before], calendar[after], cfg, interval=interval)
            rows.append({**labels, "comparison": name, **result, "metadata_pass": valid_meta,
                         "quality_pass": bool(result["quality_pass"] and valid_meta)})

    for (band, scope, group), cells in selected.groupby(["band", "scope", "group"]):
        if cells.duplicated(["link_id", "hour"]).any():
            raise ValueError("원래 선택 셀의 중복")
        valid_meta = bool(link_pass.reindex(cells.link_id.unique()).eq(True).all())
        for method in cfg["speed_aggregations"]:
            daily = speed_daily(speed, cells, dates, method, cfg["minimum_daily_coverage"])
            labels = {"metric": "speed_kmh", "band": band, "scope": scope, "group": group, "method": method,
                      "selected_cells": len(cells), "selected_links": cells.link_id.nunique()}
            compare(daily, labels, valid_meta, band == "evening" and method == "fixed_length_arithmetic")
    for band, hours in calendar_cfg["bands"].items():
        for (point, direction), frame in volume.groupby(["point", "direction"]):
            meta = volume_meta[volume_meta.point.eq(point) & volume_meta.direction.eq(direction)]
            valid_meta = bool(len(meta[["point_name", "description"]].drop_duplicates()) == 1
                              and len(meta) == len(cfg["months"]) and set(meta.month) == set(cfg["months"]))
            part = frame[frame.hour.isin(hours)]
            daily = part.groupby("date").agg(index=("value", "mean"), observed=("value", "count")).reindex(dates)
            daily["coverage"] = daily.observed.fillna(0) / len(hours)
            daily["unit_coverage"] = daily.coverage
            daily.loc[daily.coverage.lt(cfg["minimum_daily_coverage"]), "index"] = np.nan
            labels = {"metric": "vehicles_per_hour", "band": band, "scope": "point", "group": point + "|" + direction,
                      "method": "mean_recorded_hours", "selected_cells": len(hours), "selected_links": 0}
            compare(daily.rename_axis("date").reset_index(), labels, valid_meta, band == "evening")
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    daily = pd.concat(dailies, ignore_index=True)
    cache = RAW / "daily_all.parquet"
    daily.to_parquet(cache, index=False)
    quality = volume.groupby(["month", "point", "direction"]).value.agg(recorded_hours="size", known_hours="count",
                    missing_hours=lambda values: int(values.isna().sum()), zero_hours=lambda values: int(values.eq(0).sum())).reset_index()
    quality["expected_hours"] = quality.month.map(lambda month: pd.Period(month).days_in_month * 24)
    outputs = {"comparisons.csv": pd.DataFrame(rows), "metadata_check.csv": checked, "volume_metadata.csv": volume_meta,
               "volume_quality.csv": quality, "daily_evening.csv": daily[daily.band.eq("evening") & ~daily.method.eq("equal_cells")]}
    for name, frame in outputs.items():
        frame.to_csv(OUT / name, index=False)
    inputs = ["overnight_road_persistence_config.yaml", cfg["calendar_from"], cfg["original_selection"], cfg["original_selection_audit"],
              "gangnam/overnight_road_context.py", "gangnam/overnight_road_context_data.py", "gangnam/overnight_persistence.py",
              "gangnam/overnight_sensitivity.py", "gangnam/directional.py", *cfg["speed_manifests"]]
    write_json(OUT / "audit.json", {"completed_at": utcnow(), "configuration": cfg, "calendar": calendar,
                "code_sha256": sha256(Path(__file__)), "inputs": {name: sha256(CASE / name) for name in inputs},
                "speed_sources": sources, "volume_sources_sha256": sha256(MANIFEST), "volume_parsing": [item for _, item in parsed],
                "daily_all_path": str(cache.relative_to(CASE)), "daily_all_sha256": sha256(cache),
                "comparisons": len(rows), "quality_pass": int(outputs["comparisons.csv"].quality_pass.sum()),
                "outputs": {name: sha256(OUT / name) for name in outputs}})
    print(f"도로·교통량 연장 {len(rows)}개 비교, {outputs['comparisons.csv'].quality_pass.sum()}개 조건 통과", flush=True)
