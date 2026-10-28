"""끝점 이름 차이를 허용하는 가정적 도로 표본을 엄격 표본과 같은 규칙으로 비교한다."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .directional import period_dates
from .overnight_road_context import select_speed, speed_daily, speed_panel
from .overnight_sensitivity import describe_comparison


def relaxed_metadata(meta, fields):
    columns = ["링크아이디", *fields]
    variants = meta[columns].drop_duplicates()
    changed = set(variants.loc[variants.duplicated("링크아이디", keep=False), "링크아이디"])
    stable = variants[~variants["링크아이디"].isin(changed)].rename(columns={
        "링크아이디": "link_id", "도로명": "road", "방향": "direction", "거리": "length"})
    if stable.length.le(0).any() or stable.link_id.duplicated().any():
        raise ValueError("도시 도로 명칭 민감도의 길이·링크 키 오류")
    return stable, sorted(changed)


def run():
    cfg = read_yaml("overnight_road_names_config.yaml")
    parent = read_yaml(cfg["base_config"])
    base = read_yaml(parent["base_config"])
    base.update(minimum_days=parent["minimum_days"], maximum_coverage_gap=parent["maximum_coverage_gap"])
    periods = period_dates(base)
    strict, strict_links, metadata, audit = speed_panel(parent)
    links, excluded = relaxed_metadata(metadata, cfg["relaxed_fields"])
    additional = set(links.link_id) - set(strict_links.link_id)
    frames = [strict[["date", "hour", "link_id", "speed_kmh"]]]
    for entry in audit["sources"]:
        path = CASE / entry["path"]
        # speed_panel에서 전체 캐시를 확인했어도 추가 읽기 직전 같은 해시를 확인한다.
        if sha256(path) != entry["sha256"]:
            raise ValueError("명칭 민감도 도로 캐시 해시 불일치")
        d = pd.read_parquet(path)
        d = d[d.link_id.isin(additional)].copy()
        d["date"] = d.interval_start_kst.dt.strftime("%Y-%m-%d")
        d["hour"] = d.interval_start_kst.dt.hour
        d["speed_kmh"] = d.speed_kmh.where(d.is_valid & d.speed_kmh.gt(0))
        frames.append(d[["date", "hour", "link_id", "speed_kmh"]])
    data = pd.concat(frames, ignore_index=True).merge(links, on="link_id", validate="many_to_one")
    if data.duplicated(["date", "hour", "link_id"]).any():
        raise ValueError("명칭 민감도 링크·시각 중복")
    dates = sorted(str(d.date()) for m in parent["months"] for d in pd.date_range(m + "-01", periods=pd.Period(m).days_in_month))
    groups = [("road_stable_subset", road + "|" + direction, part) for (road, direction), part in data.groupby(["road", "direction"])]
    groups.extend(("core", direction, data[data.link_id.isin(ids)]) for direction, ids in parent["core"].items())
    windows = [("summer2023", "pre2023", "post2023"), ("summer2024", "pre2024", "post2024"), ("autumn2024", "pre2024", "autumn2024")]
    rows, selections, daily_rows = [], [], []
    for band, hours in read_yaml(parent["bands_from"])["bus_exploration"]["bands"].items():
        for scope, group, frame in groups:
            part = frame[frame.hour.isin(hours)]
            selected = select_speed(part, periods, parent["minimum_pre_coverage"])
            selections.append(selected.assign(band=band, scope=scope, group=group))
            for method in parent["speed_aggregations"]:
                daily = speed_daily(part, selected, dates, method, parent["minimum_daily_coverage"])
                labels = {"metric": "speed_kmh", "band": band, "scope": scope, "group": group, "method": method,
                          "selected_cells": len(selected), "selected_links": selected.link_id.nunique()}
                daily_rows.append(daily.assign(**labels))
                for name, before, after in windows:
                    rows.append({**labels, "comparison": name, **describe_comparison(daily, periods[before], periods[after], base)})
        print(f"끝점 이름 민감도: {band}", flush=True)
    out = CASE / cfg["output"]
    out.mkdir(parents=True, exist_ok=True)
    result = pd.DataFrame(rows)
    prior_path = CASE / "results/overnight/road_context/comparisons.csv"
    prior_audit = json.loads((prior_path.parent / "audit.json").read_text())
    if sha256(prior_path) != prior_audit["outputs"][prior_path.name]:
        raise ValueError("엄격 도로 비교 결과의 해시 불일치")
    prior = pd.read_csv(prior_path)
    prior = prior[prior.metric.eq("speed_kmh")]
    keys = ["metric", "band", "scope", "group", "method", "comparison"]
    compared = result.merge(prior, on=keys, suffixes=("_names_allowed", "_strict"), validate="one_to_one")
    if len(compared) != len(prior) or len(compared) != len(result):
        raise ValueError("엄격·명칭 허용 비교 키의 범위가 다릅니다")
    compared["change_difference_percentage_points"] = compared.change_pct_names_allowed - compared.change_pct_strict
    compared["both_quality_pass"] = compared.quality_pass_names_allowed & compared.quality_pass_strict
    compared["opposite_sign"] = np.sign(compared.change_pct_names_allowed) != np.sign(compared.change_pct_strict)
    links.to_csv(out / "links_names_allowed.csv", index=False)
    result.to_csv(out / "comparisons.csv", index=False)
    compared.to_csv(out / "strict_vs_names.csv", index=False)
    pd.concat(selections, ignore_index=True).to_csv(out / "selected_cells.csv", index=False)
    cache = CASE / "data/overnight/road_names_sensitivity/daily_all.parquet"
    cache.parent.mkdir(parents=True, exist_ok=True)
    pd.concat(daily_rows, ignore_index=True).to_parquet(cache, index=False)
    write_json(out / "audit.json", {"completed_at": utcnow(), "config_sha256": sha256(CASE / "overnight_road_names_config.yaml"),
                                   "base_config_sha256": sha256(CASE / cfg["base_config"]), "code_sha256": sha256(Path(__file__)),
                                   "shared_code_sha256": sha256(CASE / "gangnam/overnight_road_context.py"),
                                   "source_audit": audit, "additional_links": sorted(additional), "excluded_links": excluded,
                                   "prior_comparisons_sha256": sha256(prior_path), "daily_all_path": str(cache.relative_to(CASE)),
                                   "daily_all_sha256": sha256(cache), "outputs": {p.name: sha256(p) for p in out.glob("*.csv")},
                                   "interpretation": cfg["interpretation"]})
