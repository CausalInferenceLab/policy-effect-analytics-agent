"""고정 일반도로 링크·시간과 교통량 지점에서 다년·가을의 기술적 변화를 계산한다."""

from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .directional import period_dates
from .overnight_road_context_data import MANIFEST, RAW, verify
from .overnight_sensitivity import describe_comparison

OUT = CASE / "results/overnight/road_context"
LINK_KEYS = ["link_id", "hour"]
META = ["링크아이디", "도로명", "시점명", "종점명", "방향", "거리"]


def speed_panel(cfg):
    entries = json.loads((CASE / cfg["speed_cache_manifest"]).read_text())
    entries = [e for e in entries if e["month"] in cfg["months"]]
    if {e["month"] for e in entries} != set(cfg["months"]) or len(entries) != len(cfg["months"]):
        raise ValueError("주변 도로 캐시의 월 범위가 다릅니다")
    frames, metadata = [], []
    for entry in entries:
        if pd.Period(entry["month"]).year >= cfg["locked_year"]:
            raise ValueError("잠금 연도 도로 접근 금지")
        path = CASE / entry["path"]
        if not path.resolve().is_relative_to((CASE / "data/overnight/forecast/roads/processed").resolve()):
            raise ValueError("도로 캐시 경로가 지정 범위 밖입니다")
        if sha256(path) != entry["sha256"]:
            raise ValueError("도로 캐시 해시 불일치")
        d = pd.read_parquet(path)
        if set(d.interval_start_kst.dt.strftime("%Y-%m")) != {entry["month"]}:
            raise ValueError("도로 캐시에 다른 월이 있습니다")
        d["date"] = d.interval_start_kst.dt.strftime("%Y-%m-%d")
        d["hour"] = d.interval_start_kst.dt.hour
        d["speed_kmh"] = d.speed_kmh.where(d.is_valid & d.speed_kmh.gt(0))
        frames.append(d[["date", "hour", "link_id", "speed_kmh"]])
        metadata.extend({**x, "month": entry["month"]} for x in entry["metadata"])
    meta = pd.DataFrame(metadata)
    meta["거리"] = pd.to_numeric(meta["거리"], errors="raise")
    if meta["거리"].le(0).any():
        raise ValueError("도로 길이는 양수여야 합니다")
    variants = meta[META].drop_duplicates()
    changed = set(variants.loc[variants.duplicated("링크아이디", keep=False), "링크아이디"])
    stable = variants[~variants["링크아이디"].isin(changed)].rename(columns={
        "링크아이디": "link_id", "도로명": "road", "방향": "direction", "거리": "length"})
    data = pd.concat(frames, ignore_index=True)
    if data.duplicated(["date", "hour", "link_id"]).any():
        raise ValueError("도로 링크·시각 중복")
    return data.merge(stable, on="link_id", validate="many_to_one"), stable, meta, {
        "excluded_changed_links": sorted(changed), "stable_links": len(stable),
        "sources": [{k: e[k] for k in ["month", "path", "sha256", "source_sha256"]} for e in entries]}


def select_speed(part, periods, minimum):
    selected = None
    for year in [2023, 2024]:
        dates = periods[f"pre{year}"]
        coverage = part[part.date.isin(dates)].groupby(LINK_KEYS).speed_kmh.count() / len(dates)
        keep = coverage[coverage.ge(minimum)].rename(f"pre_coverage_{year}").reset_index()
        selected = keep if selected is None else selected.merge(keep, on=LINK_KEYS, validate="one_to_one")
    lengths = part[[*LINK_KEYS, "length"]].drop_duplicates()
    return selected.merge(lengths, on=LINK_KEYS, validate="one_to_one")


def speed_daily(part, selected, dates, method, minimum):
    if method not in {"fixed_length_arithmetic", "equal_cells"}:
        raise ValueError("알 수 없는 도로 집계법")
    selected = selected.copy()
    selected["weight"] = selected.length if method == "fixed_length_arithmetic" else 1.0
    denominator = selected.weight.sum()
    d = part.merge(selected[[*LINK_KEYS, "weight"]], on=LINK_KEYS, validate="many_to_one")
    d["weighted"] = d.speed_kmh * d.weight
    d["observed_weight"] = d.weight.where(d.speed_kmh.notna(), 0)
    daily = d.groupby("date").agg(total=("weighted", lambda x: x.sum(min_count=1)),
                                  observed_weight=("observed_weight", "sum"), observed=("speed_kmh", "count"))
    daily = daily.reindex(dates)
    daily["coverage"] = daily.observed_weight.fillna(0) / denominator if denominator else 0.0
    daily["unit_coverage"] = daily.coverage
    daily["index"] = (daily.total / daily.observed_weight.replace(0, np.nan)).where(daily.coverage.ge(minimum))
    return daily.rename_axis("date").reset_index()


def validate_volume_header(header):
    ordinary = ["일자", "요일", "지점명", "지점번호", "방향", "구분"]
    extra_weekday = ["일자", "요일", "요일(2)", "지점명", "지점번호", "방향", "구분"]
    hours = [f"{h}시" for h in range(24)]
    if list(header) not in [ordinary + hours, extra_weekday + hours]:
        raise ValueError("교통량 식별·시간 헤더 변경")


def volume_entry(job):
    from openpyxl import load_workbook

    entry, cfg = job
    workbook = load_workbook(verify(entry, cfg), read_only=True, data_only=True)
    try:
        month = entry["month"]
        values = workbook[f"{month[:4]}년 {month[-2:]}월"].values
        header = next(values)
        validate_volume_header(header)
        full = pd.DataFrame(values, columns=header)
        if not {"일자", "지점번호", "지점명", "방향", "구분"}.issubset(full.columns):
            raise ValueError("교통량 식별 열이 없습니다")
        d = full[full["지점번호"].isin(cfg["volume"]["points"])].rename(columns={
            "일자": "date", "지점번호": "point", "지점명": "point_name", "방향": "direction", "구분": "description"})
        d = d.melt(id_vars=["date", "point", "point_name", "direction", "description"],
                   value_vars=[f"{h}시" for h in range(24)], var_name="hour", value_name="value")
        d["date"] = pd.to_datetime(d.date.astype(str), format="%Y%m%d", errors="raise").dt.strftime("%Y-%m-%d")
        if set(d.date.str[:7]) != {month}:
            raise ValueError("교통량 파일에 다른 월 또는 빈 지점 자료")
        d["hour"] = d.hour.str.removesuffix("시").astype(int)
        d["value"] = pd.to_numeric(d.value, errors="raise")
        if d.value.lt(0).any() or np.isinf(d.value).any():
            raise ValueError("교통량 값이 음수·무한대입니다")
        return d, {"month": month, "header": list(header), "rows_scanned": len(full), "selected_hours": len(d),
                   "missing_hours": int(d.value.isna().sum()), "zero_hours": int(d.value.eq(0).sum()),
                   "source_sha256": entry["sha256"], "path": entry["path"]}
    finally:
        workbook.close()


def volume_panel(cfg):
    entries = json.loads(MANIFEST.read_text())["files"]
    if {e["month"] for e in entries} != set(cfg["months"]) or len(entries) != len(cfg["months"]):
        raise ValueError("교통량 수집 범위가 다릅니다")
    with ProcessPoolExecutor(max_workers=cfg["resources"]["parser_workers"]) as pool:
        parts = list(pool.map(volume_entry, [(e, cfg) for e in entries]))
    data = pd.concat([d for d, _ in parts], ignore_index=True)
    if data.duplicated(["date", "point", "direction", "hour"]).any():
        raise ValueError("교통량 지점·방향·시간 키 중복")
    return data, [audit for _, audit in parts]


def run():
    cfg = read_yaml("overnight_road_context_config.yaml")
    base = read_yaml(cfg["base_config"])
    base.update(minimum_days=cfg["minimum_days"], maximum_coverage_gap=cfg["maximum_coverage_gap"])
    periods = period_dates(base)
    bands = read_yaml(cfg["bands_from"])["bus_exploration"]["bands"]
    dates = sorted(str(d.date()) for m in cfg["months"] for d in pd.date_range(m + "-01", periods=pd.Period(m).days_in_month))
    OUT.mkdir(parents=True, exist_ok=True)
    speed, links, meta, speed_audit = speed_panel(cfg)
    links.to_csv(OUT / "stable_links.csv", index=False)
    meta.to_csv(OUT / "metadata_by_month.csv", index=False)
    candidates = meta[["도로명", "방향", "링크아이디"]].drop_duplicates()
    retention = candidates.groupby(["도로명", "방향"])["링크아이디"].nunique().rename("candidate_links").reset_index()
    retention = retention.rename(columns={"도로명": "road", "방향": "direction"})
    retention = retention.merge(links.groupby(["road", "direction"]).link_id.nunique().rename("stable_links").reset_index(),
                                on=["road", "direction"], how="left", validate="one_to_one")
    retention["stable_link_fraction"] = retention.stable_links.fillna(0) / retention.candidate_links
    retention.to_csv(OUT / "metadata_retention.csv", index=False)
    volume, volume_audit = volume_panel(cfg)
    volume[["point", "point_name", "direction", "description"]].drop_duplicates().to_csv(OUT / "volume_metadata.csv", index=False)
    quality = volume.groupby([volume.date.str[:7].rename("month"), "point", "direction"]).value.agg(
        recorded_hours="size", known_hours="count", minimum="min", maximum="max", zero_hours=lambda x: int(x.eq(0).sum())).reset_index()
    quality["expected_hours"] = quality.month.map(lambda m: pd.Period(m).days_in_month * 24)
    quality.to_csv(OUT / "volume_quality.csv", index=False)
    comparisons, daily_rows, chosen = [], [], []
    windows = [("summer2023", "pre2023", "post2023"), ("summer2024", "pre2024", "post2024"), ("autumn2024", "pre2024", "autumn2024")]

    def save_comparisons(daily, labels, interval):
        daily_rows.append(daily.assign(**labels))
        for name, pre, post in windows:
            result = describe_comparison(daily, periods[pre], periods[post], base, interval=interval)
            comparisons.append({**labels, "comparison": name, **result})

    groups = [("road_stable_subset", road + "|" + direction, part) for (road, direction), part in speed.groupby(["road", "direction"])]
    groups.extend(("core", direction, speed[speed.link_id.isin(ids)]) for direction, ids in cfg["core"].items())
    for band, hours in bands.items():
        for scope, group, frame in groups:
            part = frame[frame.hour.isin(hours)]
            selected = select_speed(part, periods, cfg["minimum_pre_coverage"])
            chosen.append(selected.assign(band=band, scope=scope, group=group))
            for method in cfg["speed_aggregations"]:
                daily = speed_daily(part, selected, dates, method, cfg["minimum_daily_coverage"])
                labels = {"metric": "speed_kmh", "band": band, "scope": scope, "group": group, "method": method,
                          "selected_cells": len(selected), "selected_links": selected.link_id.nunique()}
                save_comparisons(daily, labels, band == "evening" and method == "fixed_length_arithmetic")
        for (point, direction), part in volume[volume.hour.isin(hours)].groupby(["point", "direction"]):
            daily = part.groupby("date").agg(index=("value", "mean"), observed=("value", "count")).reindex(dates)
            daily["coverage"] = daily.observed.fillna(0) / len(hours)
            daily["unit_coverage"] = daily.coverage
            daily.loc[daily.coverage.lt(cfg["minimum_daily_coverage"]), "index"] = np.nan
            labels = {"metric": "vehicles_per_hour", "band": band, "scope": "point", "group": point + "|" + direction,
                      "method": "mean_recorded_hours", "selected_cells": len(hours), "selected_links": 0}
            save_comparisons(daily.rename_axis("date").reset_index(), labels, band == "evening")
        print(f"주변 교통 비교: {band}", flush=True)
    pd.DataFrame(comparisons).to_csv(OUT / "comparisons.csv", index=False)
    pd.concat(chosen, ignore_index=True).to_csv(OUT / "selected_cells.csv", index=False)
    daily = pd.concat(daily_rows, ignore_index=True)
    daily.to_parquet(RAW / "daily_all.parquet", index=False)
    daily[daily.band.eq("evening") & ~daily.method.eq("equal_cells")].to_csv(OUT / "daily_evening.csv", index=False)
    write_json(OUT / "audit.json", {"completed_at": utcnow(), "config_sha256": sha256(CASE / "overnight_road_context_config.yaml"),
                                   "code_sha256": sha256(Path(__file__)), "speed": speed_audit, "volume": volume_audit,
                                   "source_manifest_sha256": sha256(MANIFEST), "period_dates": periods,
                                   "daily_all_path": str((RAW / "daily_all.parquet").relative_to(CASE)),
                                   "daily_all_sha256": sha256(RAW / "daily_all.parquet"),
                                   "outputs": {p.name: sha256(p) for p in OUT.glob("*.csv")}, "interpretation": cfg["interpretation"]})
