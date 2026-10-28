"""고정 정류장·노선 구간의 지수와 주변 도로 변화를 재현 가능한 탐색으로 계산한다."""

from __future__ import annotations

import json
import re
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd

from .common import CASE, digest, holiday_dates, read_yaml, sha256, write_json
from .followup_data import read_manifest, verify
from .topis import parse_month

OUT = CASE / "results/followup"
CACHE = CASE / "data/followup/processed"
VALUES = {"bus_time": "운행시간", "bus_trips": "버스운행횟수", "bus_boardings": "승차_승객_수"}
RENAME = {"기준_날짜": "date", "노선_ID": "route", "정류장_ID": "stop",
          "정류장_순서": "sequence", "출발_정류장_ID": "stop", "출발_정류장_순서": "sequence",
          "도착_정류장_ID": "arrival", "도착_정류장_순서": "arrival_sequence"}


def registry():
    policy = read_yaml("followup-policy.yaml")
    master = pd.read_csv(CASE / "data/discovery/stop_master.csv", encoding="cp949", dtype=str)
    if master["정류장_ID"].duplicated().any():
        raise ValueError("정류장 마스터 ID 중복")
    historical = pd.concat([pd.read_csv(CASE / f"data/discovery/boarding_{m}.csv", encoding="cp949", dtype=str,
                                      usecols=["표준버스정류장ID", "버스정류장ARS번호"])
                            for m in ("202405", "202407")]).drop_duplicates()
    pairs = set(map(tuple, historical.to_numpy()))
    rows = []
    for group, stops in policy["stations"].items():
        for order, ars in enumerate(stops):
            found = master[master["정류장_번호"].eq(ars)]
            if len(found) != 1:
                raise ValueError(f"ARS와 현 마스터 대응이 유일하지 않습니다: {ars}")
            row = found.iloc[0]
            rows.append({"stop": row["정류장_ID"], "ars": ars, "group": group, "order": order,
                         "name": policy["historical_name_overrides"].get(ars, row["정류장_명칭"]),
                         "current_name": row["정류장_명칭"],
                         "historical_id_ars_pair": (row["정류장_ID"], ars) in pairs,
                         "mapping_status": "2024_card_pair" if (row["정류장_ID"], ars) in pairs else "provisional_current_master"})
    result = pd.DataFrame(rows)
    if result.stop.duplicated().any():
        raise ValueError("분석 정류장 중복")
    return result


def clean_duplicates(frame, keys):
    """같은 값의 중복만 제거하고, 값이 다른 중복 키는 전체를 격리한다."""
    if frame[keys].isna().any().any():
        raise ValueError("결측 결합 키")
    exact = int(frame.duplicated().sum())
    unique = frame.drop_duplicates()
    conflicts = unique.duplicated(keys, keep=False)
    return unique.loc[~conflicts].copy(), {"identical_removed": exact, "conflicting_rows_quarantined": int(conflicts.sum()),
                                         "conflicting_keys": len(unique.loc[conflicts, keys].drop_duplicates())}


def extract_archive(args):
    entry, stops, hours = args
    path = verify(entry)
    cols = [f"{VALUES[entry['kind']]}_{h:02}시" for h in hours]
    keys = ["기준_날짜", "노선_ID"]
    if entry["kind"] == "bus_time":
        keys += ["출발_정류장_ID", "출발_정류장_순서", "도착_정류장_ID", "도착_정류장_순서"]
    else:
        keys += ["정류장_ID", "정류장_순서"]
    parts, dates, total = [], set(), 0
    with ZipFile(path) as archive:
        for name in sorted(archive.namelist()):
            with archive.open(name) as f:
                for chunk in pd.read_csv(f, encoding="cp949", dtype=str, usecols=keys + cols, chunksize=100000):
                    total += len(chunk)
                    dates.update(chunk["기준_날짜"].unique())
                    chosen = chunk[keys[2]].isin(stops)
                    if entry["kind"] == "bus_time":
                        chosen |= chunk["도착_정류장_ID"].isin(stops)
                    part = chunk.loc[chosen].copy()
                    for c in cols:
                        part[c] = pd.to_numeric(part[c], errors="raise")
                    parts.append(part)
    d = pd.concat(parts, ignore_index=True).rename(columns=RENAME | {c: f"h{h:02}" for c, h in zip(cols, hours, strict=True)})
    pd.to_datetime(d.date, format="%Y%m%d", errors="raise")
    # 월 ZIP에는 다음 달 날짜가 포함된다. 날짜를 보존하고 전체 결합 뒤 중복 검사한다.
    target = CACHE / f"{entry['kind']}_{entry['month']}.parquet"
    d.to_parquet(target, index=False)
    info = {"path": str(target.relative_to(CASE)), "raw_sha256": entry["sha256"], "rows_scanned": total,
            "rows_selected": len(d), "dates": sorted(dates), "hours": hours, "stops_hash": digest(sorted(stops)),
            "parser_sha256": sha256(Path(__file__)), "sha256": sha256(target)}
    write_json(target.with_suffix(".json"), info)
    print(f"버스 추출: {entry['kind']} {entry['month']} {len(d):,}행", flush=True)
    return info


def extract_road(month):
    cfg = read_yaml("followup_config.yaml")
    source = CASE / "data/raw" / f"{month}.xlsx"
    manifest = json.loads(source.with_suffix(".source.json").read_text())
    if sha256(source) != manifest["sha256"]:
        raise ValueError("속도 원본 해시 변경")
    frame, meta = parse_month(source, month, cfg["roads"]["names"], read_yaml("data_contract.yaml")["checks"]["missing_values"]["value"])
    target = CACHE / f"roads_{month}.parquet"
    frame.to_parquet(target, index=False)
    meta.update(raw_sha256=manifest["sha256"], sha256=sha256(target), roads=cfg["roads"]["names"])
    write_json(target.with_suffix(".json"), meta)
    print(f"도로 추출: {month} {len(frame):,}행", flush=True)
    return meta


def prepare():
    cfg, stations = read_yaml("followup_config.yaml"), registry()
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    stations.to_csv(OUT / "station_registry.csv", index=False)
    jobs, reports = [], []
    for entry in read_manifest():
        if entry["kind"] == "volume":
            verify(entry)
            continue
        target = CACHE / f"{entry['kind']}_{entry['month']}.parquet"
        sidecar = target.with_suffix(".json")
        if target.exists() and sidecar.exists():
            info = json.loads(sidecar.read_text())
            if (info["raw_sha256"] == entry["sha256"] and info["hours"] == cfg["profile_hours"]
                    and info["stops_hash"] == digest(sorted(stations.stop)) and sha256(target) == info["sha256"]):
                verify(entry)
                reports.append(info)
                continue
            raise ValueError(f"기존 추출 조건 또는 해시 변경: {target}")
        jobs.append((entry, set(stations.stop), cfg["profile_hours"]))
    with ProcessPoolExecutor(max_workers=2) as pool:
        reports.extend(pool.map(extract_archive, jobs))
    months = []
    for month in cfg["collection_months"]:
        target = CACHE / f"roads_{month}.parquet"
        sidecar = target.with_suffix(".json")
        if target.exists() and sidecar.exists():
            info = json.loads(sidecar.read_text())
            if sha256(target) != info["sha256"] or info["roads"] != cfg["roads"]["names"]:
                raise ValueError("도로 캐시 변경")
        else:
            months.append(month)
    with ProcessPoolExecutor(max_workers=2) as pool:
        list(pool.map(extract_road, months))
    write_json(OUT / "extraction_audit.json", sorted(reports, key=lambda x: x["path"]))


def bus_frame(kind):
    frames = []
    for m in read_yaml("followup_config.yaml")["collection_months"]:
        path = CACHE / f"{kind}_{m}.parquet"
        info = json.loads(path.with_suffix(".json").read_text())
        if sha256(path) != info["sha256"]:
            raise ValueError(f"추출 캐시 해시 변경: {path}")
        frames.append(pd.read_parquet(path))
    d = pd.concat(frames, ignore_index=True)
    keys = ["date", "route", "stop", "sequence"] + (["arrival", "arrival_sequence"] if kind == "bus_time" else [])
    d, audit = clean_duplicates(d, keys)
    d = d[d.date.between("20240401", "20240831")].copy()
    audit.update(rows=len(d), dates=sorted(d.date.unique()), route_zero_rows=int(d.route.eq("0").sum()))
    d = d[d.route.ne("0")]
    if kind == "bus_time":
        # 월별 정류장 순번 변경은 동일 구간으로 비교하되 같은 날 반복 방문은 모호하므로 격리한다.
        repeated = d.duplicated(["date", "route", "stop", "arrival"], keep=False)
        audit["revisited_segment_rows_quarantined"] = int(repeated.sum())
        d = d[~repeated]
    else:
        repeated = d.duplicated(["date", "route", "stop"], keep=False)
        audit["revisited_stop_rows_quarantined"] = int(repeated.sum())
        d = d[~repeated]
    values = [c for c in d if c.startswith("h") and c[1:].isdigit()]
    audit.update(missing_cells=int(d[values].isna().sum().sum()), zero_cells=int(d[values].eq(0).sum().sum()),
                 negative_cells=int(d[values].lt(0).sum().sum()))
    quality = d.assign(missing=d[values].isna().sum(axis=1), zero=d[values].eq(0).sum(axis=1),
                       positive=d[values].gt(0).sum(axis=1)).groupby("date").agg(
                           rows=("route", "size"), routes=("route", "nunique"), missing=("missing", "sum"),
                           zero=("zero", "sum"), positive=("positive", "sum"))
    expected = pd.date_range("2024-04-01", "2024-08-31").strftime("%Y%m%d")
    quality = quality.reindex(expected)
    quality["has_selected_rows"] = quality.rows.notna()
    quality.rename_axis("date").to_csv(OUT / f"quality_{kind}.csv")
    long = d.melt(id_vars=[c for c in d if c not in values], value_vars=values, var_name="hour", value_name="value")
    long["hour"] = long.hour.str[1:].astype(int)
    long["date"] = pd.to_datetime(long.date, format="%Y%m%d").dt.strftime("%Y-%m-%d")
    long.loc[long.value.le(0), "value"] = np.nan
    return long, audit


def weekdays(start, end):
    days = pd.date_range(start, end)
    holidays = holiday_dates(start, end)
    return [str(d.date()) for d in days if d.dayofweek < 5 and str(d.date()) not in holidays]


def bootstrap_change(pre, post, seed=20261028, draws=2000):
    """날짜별 독립 재표집 구간이며 자기상관을 해결한 인과 신뢰구간은 아니다."""
    rng = np.random.default_rng(seed)
    a, b = np.asarray(pre, dtype=float), np.asarray(post, dtype=float)
    if len(a) < 2 or len(b) < 2 or not np.isfinite(a).all() or not np.isfinite(b).all():
        return [None, None]
    delta = rng.choice(b, (draws, len(b)), replace=True).mean(1) - rng.choice(a, (draws, len(a)), replace=True).mean(1)
    return np.quantile(delta, [.025, .975]).tolist()


def fixed_index(frame, pre_dates, post_dates, keys, minimum_coverage=.8, common_coverage=False):
    """노선·구간·시간대는 사전 기간 관측률로만 고른다. 미관측은 0으로 채우지 않는다."""
    if frame.duplicated(["date", *keys]).any():
        raise ValueError("지수 계산 키 중복")
    pre = frame[frame.date.isin(pre_dates)]
    base = pre.groupby(keys, observed=True).value.agg(["mean", "count"])
    base["pre_coverage"] = base["count"] / len(pre_dates)
    selected = base[(base.pre_coverage >= minimum_coverage) & base["mean"].gt(0)].reset_index()
    selected = selected.rename(columns={"mean": "baseline"})
    if common_coverage:
        post = frame[frame.date.isin(post_dates)].groupby(keys, observed=True).value.count() / len(post_dates)
        selected = selected.merge(post.rename("post_coverage"), on=keys, how="left", validate="one_to_one")
        selected = selected[selected.post_coverage.ge(minimum_coverage)].copy()
    if selected.empty:
        return pd.DataFrame(columns=["date", "index", "coverage"]), selected
    d = frame.merge(selected[keys + ["baseline"]], on=keys, validate="many_to_one")
    d["index"] = 100 * d.value / d.baseline
    daily = d.groupby("date").agg(index=("index", "mean"), observed=("index", "count")).reindex(sorted(set(pre_dates) | set(post_dates)))
    daily["coverage"] = daily.observed.fillna(0) / len(selected)
    daily.loc[daily.coverage < minimum_coverage, "index"] = np.nan
    return daily.rename_axis("date").reset_index(), selected


def summarize_daily(daily, pre, post, cfg, value="index"):
    a = daily[daily.date.isin(pre)][value].dropna()
    b = daily[daily.date.isin(post)][value].dropna()
    ac = daily[daily.date.isin(pre)].coverage.mean()
    bc = daily[daily.date.isin(post)].coverage.mean()
    enough = len(a) >= cfg["minimum_common_days"] and len(b) >= cfg["minimum_common_days"]
    balanced = pd.notna(ac) and pd.notna(bc) and abs(ac - bc) <= cfg["maximum_coverage_gap"]
    return {"pre_mean": float(a.mean()) if len(a) else None, "post_mean": float(b.mean()) if len(b) else None,
            "change": float(b.mean() - a.mean()) if len(a) and len(b) else None,
            "relative_change_pct": float(100 * (b.mean() / a.mean() - 1)) if len(a) and len(b) and a.mean() else None,
            "pre_days": len(a), "post_days": len(b), "pre_coverage": float(ac) if pd.notna(ac) else None,
            "post_coverage": float(bc) if pd.notna(bc) else None, "quality_pass": bool(enough and balanced),
            "descriptive_interval": bootstrap_change(a, b, **{k: cfg["bootstrap"][k] for k in ("seed", "draws")})}


def periods(cfg, scenario="main"):
    pre, post = list(cfg["pre"]), list(cfg["post"])
    if scenario == "before_announcement":
        pre[1] = "2024-06-16"
    elif scenario == "include_first_week":
        post[0] = cfg["sensitivities"]["include_first_week_from"]
    elif scenario == "july_only":
        post = cfg["sensitivities"]["july_only"]
    elif scenario == "official_dates":
        return cfg["sensitivities"]["official_dates_pre"], cfg["sensitivities"]["official_dates_post"]
    elif scenario not in {"main", "common_recording"}:
        raise ValueError(f"알 수 없는 비교 기간: {scenario}")
    return weekdays(*pre), weekdays(*post)


def analyze_bus(cfg, stations):
    d, audit = bus_frame("bus_time")
    info = stations.set_index("stop")
    for key, prefix in (("stop", "from"), ("arrival", "to")):
        for col in ("group", "order", "historical_id_ars_pair", "ars", "name"):
            d[f"{prefix}_{col}"] = d[key].map(info[col])
    same = d.from_group.eq(d.to_group) & d.from_group.ne("feeder")
    # 가로변 목록의 순서는 같은 위도의 대체 정류장도 포함하므로 방향 판단에 쓰지 않는다.
    valid = same & (d.from_group.eq("curb_south") | d.to_order.gt(d.from_order))
    d = d[valid].copy()
    d["group"] = d.from_group
    keys = ["route", "stop", "arrival", "hour"]
    summaries, curves, daily_frames, cells, pairs = [], [], [], [], []
    for scenario in ("main", "common_recording", "before_announcement", "include_first_week", "july_only", "official_dates"):
        pre, post = periods(cfg, scenario)
        for group, part in d[d.hour.isin(cfg["evening_hours"])].groupby("group"):
            daily, selected = fixed_index(part, pre, post, keys, cfg["minimum_coverage"], common_coverage=scenario == "common_recording")
            result = summarize_daily(daily, pre, post, cfg)
            summaries.append({"scenario": scenario, "group": group, "selected_cells": len(selected), **result})
            if scenario == "main":
                daily_frames.append(daily.assign(group=group))
                cells.append(selected.assign(group=group))
    pre, post = periods(cfg)
    for (group, hour), part in d.groupby(["group", "hour"]):
        daily, selected = fixed_index(part, pre, post, keys, cfg["minimum_coverage"])
        curves.append({"group": group, "hour": int(hour), "selected_cells": len(selected), **summarize_daily(daily, pre, post, cfg)})
    for (stop, arrival), part in d[d.hour.isin(cfg["evening_hours"])].groupby(["stop", "arrival"]):
        daily, selected = fixed_index(part, pre, post, keys, cfg["minimum_coverage"])
        a, b = info.loc[stop], info.loc[arrival]
        common_daily, common_cells = fixed_index(part, pre, post, keys, cfg["minimum_coverage"], common_coverage=True)
        common = summarize_daily(common_daily, pre, post, cfg)
        pairs.append({"stop": stop, "arrival": arrival, "from_ars": a.ars, "to_ars": b.ars,
                      "from_name": a["name"], "to_name": b["name"], "group": a.group,
                      "adjacent": bool(b.order == a.order + 1), "order": int(a.order),
                      "mapping_verified": bool(a.historical_id_ars_pair and b.historical_id_ars_pair),
                      "selected_cells": len(selected), **summarize_daily(daily, pre, post, cfg),
                      "common_recording_cells": len(common_cells), "common_recording_change_pct": common["relative_change_pct"],
                      "common_recording_quality_pass": common["quality_pass"]})
    pd.DataFrame(summaries).to_csv(OUT / "bus_summary.csv", index=False)
    pd.DataFrame(curves).to_csv(OUT / "bus_hour_profile.csv", index=False)
    pd.DataFrame(pairs).to_csv(OUT / "bus_segments.csv", index=False)
    pd.concat(daily_frames, ignore_index=True).to_csv(OUT / "bus_daily.csv", index=False)
    pd.concat(cells, ignore_index=True).to_csv(OUT / "bus_selected_cells.csv", index=False)
    return audit


def analyze_counts(cfg, stations):
    pre, post = periods(cfg)
    audits, records, route_presence, daily_records = {}, [], [], []
    policy = read_yaml("followup-policy.yaml")
    route_master = pd.read_csv(CASE / "data/discovery/route_master.csv", encoding="cp949", dtype=str).set_index("노선_ID")
    for kind in ("bus_trips", "bus_boardings"):
        d, audits[kind] = bus_frame(kind)
        d = d[d.hour.isin(cfg["evening_hours"]) & d.stop.isin(stations.stop)]
        d = d[d.date.isin(pre + post)].copy()
        d["period"] = np.where(d.date.isin(pre), "pre", "post")
        for (stop, period), part in d.groupby(["stop", "period"]):
            eligible = pre if period == "pre" else post
            subtotal = part.groupby("date").value.sum(min_count=1).reindex(eligible)
            observed = part.groupby("date").value.count().reindex(eligible, fill_value=0)
            present = part.groupby("date").size().reindex(eligible, fill_value=0)
            records.append({"kind": kind, "stop": stop, "period": period, "daily_recorded_positive_subtotal": subtotal.mean(),
                            "days_with_positive_records": int(subtotal.notna().sum()), "present_cells": len(part),
                            "positive_cells": int(part.value.notna().sum()), "positive_fraction_of_present": part.value.notna().mean(),
                            "routes_with_positive_records": part.loc[part.value.notna(), "route"].nunique()})
            daily_records.extend({"kind": kind, "stop": stop, "period": period, "date": date,
                                  "recorded_positive_subtotal": subtotal.loc[date], "observed_positive_cells": int(observed.loc[date]),
                                  "present_cells": int(present.loc[date])} for date in eligible)
        if kind == "bus_trips":
            candidate_group = {route: group for group, routes in policy["candidate_route_ids"].items() for route in routes}
            candidate = d[d.route.isin(candidate_group)].copy()
            candidate["group"] = candidate.stop.map(stations.set_index("stop").group)
            for (route, group, period), part in candidate.groupby(["route", "group", "period"]):
                route_presence.append({"route": route, "current_route_name": route_master.loc[route, "노선_명칭"],
                                       "candidate_policy_group": candidate_group[route], "station_group": group, "period": period,
                                       "observed_positive_days": part.loc[part.value.notna(), "date"].nunique(),
                                       "positive_cells": int(part.value.notna().sum()),
                                       "observed_ars": ";".join(sorted(set(part.loc[part.value.notna(), "stop"].map(stations.set_index("stop").ars)))),
                                       "historical_route_name_status": "unverified_current_name_candidate"})
    pd.DataFrame(records).merge(stations, on="stop", validate="many_to_one").to_csv(OUT / "station_recorded_counts.csv", index=False)
    pd.DataFrame(daily_records).to_csv(OUT / "station_counts_daily.csv", index=False)
    pd.DataFrame(route_presence).to_csv(OUT / "candidate_route_presence.csv", index=False)
    # 원문 20개 노선 각각의 대응 상태를 기록한다. 현재 명칭은 후보에만 사용한다.
    family_rows = []
    observed = {x["route"] for x in route_presence if x["positive_cells"]}
    for group, spec in policy["groups"].items():
        for family in spec["families"]:
            candidates = []
            for route in policy["candidate_route_ids"][group]:
                name = re.match(r"[A-Za-z0-9-]+", route_master.loc[route, "노선_명칭"]).group()
                accepted = {family, family + "A", family + "B"} if group == "reverse_evening" else {family}
                if name in accepted:
                    candidates.append(route)
            family_rows.append({"family": family, "policy_group": group, "source_page": spec["page"],
                                "candidate_ids": ";".join(candidates), "observed_candidate_ids": ";".join(x for x in candidates if x in observed),
                                "historical_id_name_status": "unverified", "official_2024_route_family": "verified"})
    pd.DataFrame(family_rows).to_csv(OUT / "policy_family_coverage.csv", index=False)
    return audits


def road_panel(cfg):
    frames, metadata = [], []
    for m in cfg["collection_months"]:
        p = CACHE / f"roads_{m}.parquet"
        info = json.loads(p.with_suffix(".json").read_text())
        if sha256(p) != info["sha256"]:
            raise ValueError("도로 캐시 해시 변경")
        frames.append(pd.read_parquet(p))
        metadata.extend(info["metadata"])
    meta = pd.DataFrame(metadata)
    fields = ["링크아이디", "도로명", "시점명", "종점명", "방향", "거리"]
    variants = meta[fields].drop_duplicates()
    changed = set(variants.loc[variants.duplicated("링크아이디", keep=False), "링크아이디"])
    stable = variants[~variants["링크아이디"].isin(changed)].copy()
    stable = stable.rename(columns={"링크아이디": "link_id", "도로명": "road", "방향": "direction", "거리": "length"})
    stable["length"] = pd.to_numeric(stable.length, errors="raise")
    if stable.length.le(0).any():
        raise ValueError("도로 길이가 양수가 아닙니다")
    d = pd.concat(frames, ignore_index=True)
    if d.duplicated(["link_id", "interval_start_kst"]).any():
        raise ValueError("도로 시간 키 중복")
    d["date"] = d.interval_start_kst.dt.strftime("%Y-%m-%d")
    d["hour"] = d.interval_start_kst.dt.hour
    d.loc[~d.is_valid, "speed_kmh"] = np.nan
    d = d.merge(stable, on="link_id", validate="many_to_one")
    stable.to_csv(OUT / "road_links.csv", index=False)
    return d, {"excluded_changed_links": sorted(changed), "stable_links": len(stable),
               "lane_count": "차선 수는 고정 길이 가중치에 사용하지 않으며 변화는 원본 메타데이터에 보존"}


def road_daily(part, pre, post, cfg):
    base = part[part.date.isin(pre)].groupby(["link_id", "hour"]).speed_kmh.count() / len(pre)
    chosen = base[base.ge(cfg["minimum_coverage"])].rename("pre_coverage").reset_index()
    selected = part.merge(chosen, on=["link_id", "hour"], validate="many_to_one")
    denominator = selected[["link_id", "hour", "length"]].drop_duplicates().length.sum()
    if not denominator:
        return pd.DataFrame(columns=["date", "index", "coverage"]), 0
    selected["weighted"] = selected.speed_kmh * selected.length
    selected["valid_length"] = selected.length.where(selected.speed_kmh.notna())
    daily = selected.groupby("date").agg(total=("weighted", lambda x: x.sum(min_count=1)), length=("valid_length", "sum"))
    daily["coverage"] = daily.length / denominator
    daily["index"] = daily.total / daily.length.replace(0, np.nan)
    daily.loc[daily.coverage < cfg["minimum_coverage"], "index"] = np.nan
    daily = daily.reindex(sorted(set(pre + post)))
    daily["coverage"] = daily.coverage.fillna(0)
    return daily.rename_axis("date").reset_index(), chosen.link_id.nunique()


def analyze_roads(cfg):
    d, audit = road_panel(cfg)
    evening = d[d.hour.isin(cfg["evening_hours"])]
    rows, daily_rows = [], []
    for scenario in ("main", "before_announcement", "include_first_week", "july_only", "official_dates"):
        pre, post = periods(cfg, scenario)
        for (road, direction), part in evening.groupby(["road", "direction"]):
            daily, count = road_daily(part, pre, post, cfg)
            rows.append({"scenario": scenario, "road": road, "direction": direction, "links": count,
                         **summarize_daily(daily, pre, post, cfg)})
            if scenario == "main":
                daily_rows.append(daily.assign(road=road, direction=direction))
    pd.DataFrame(rows).to_csv(OUT / "road_summary.csv", index=False)
    pd.concat(daily_rows, ignore_index=True).to_csv(OUT / "road_daily.csv", index=False)
    return d, audit


def volume_panel(cfg):
    from openpyxl import load_workbook

    frames = []
    for entry in read_manifest():
        if entry["kind"] != "volume":
            continue
        w = load_workbook(verify(entry), read_only=True, data_only=True)
        try:
            m = entry["month"]
            rows = w[f"{m[:4]}년 {m[-2:]}월"].values
            d = pd.DataFrame(rows, columns=next(rows))
            if list(d.columns[6:]) != [f"{h}시" for h in range(24)]:
                raise ValueError("교통량 시간 열 변경")
            d = d[d["지점번호"].isin(cfg["volume"]["points"])].copy()
            d = d.rename(columns={"일자": "date", "지점번호": "point", "방향": "direction", "구분": "description"})
            d = d.melt(id_vars=["date", "point", "direction", "description"], value_vars=[f"{h}시" for h in range(24)], var_name="hour", value_name="value")
            d["date"] = pd.to_datetime(d.date.astype(str), format="%Y%m%d").dt.strftime("%Y-%m-%d")
            d["hour"] = d.hour.str.removesuffix("시").astype(int)
            d["value"] = pd.to_numeric(d.value, errors="raise")
            if d.value.lt(0).any():
                raise ValueError("교통량 음수 확인 필요")
            frames.append(d)
        finally:
            w.close()
    result = pd.concat(frames, ignore_index=True)
    if result.duplicated(["date", "point", "direction", "hour"]).any():
        raise ValueError("교통량 시간 키 중복")
    return result


def analyze_volume(cfg, speed):
    d = volume_panel(cfg)
    quality = d.groupby(["point", "direction"]).value.agg(["size", "count", "min", "max"]).reset_index()
    quality.to_csv(OUT / "volume_quality.csv", index=False)
    rows, all_daily = [], []
    for scenario in ("main", "before_announcement", "include_first_week", "july_only", "official_dates"):
        pre, post = periods(cfg, scenario)
        for (point, direction), part in d[d.hour.isin(cfg["evening_hours"])].groupby(["point", "direction"]):
            daily = part.groupby("date").agg(index=("value", "mean"), observed=("value", "count"))
            daily["coverage"] = daily.observed / len(cfg["evening_hours"])
            daily.loc[daily.coverage < cfg["minimum_coverage"], "index"] = np.nan
            daily = daily.rename_axis("date").reset_index()
            rows.append({"scenario": scenario, "point": point, "direction": direction, "description": part.description.iloc[0],
                         **summarize_daily(daily, pre, post, cfg)})
            if scenario == "main":
                all_daily.append(daily.assign(point=point, direction=direction))
    pd.DataFrame(rows).to_csv(OUT / "volume_summary.csv", index=False)
    pd.concat(all_daily, ignore_index=True).to_csv(OUT / "volume_daily.csv", index=False)
    # 같은 D-35 값을 여러 링크의 독립 관측으로 세지 않고 한 시간에 한 행만 만든다.
    link = speed[speed.link_id.eq("1220021000")][["date", "hour", "speed_kmh"]]
    joined = d[d.point.eq("D-35") & d.direction.eq("유출")].merge(link, on=["date", "hour"], how="left", validate="one_to_one")
    joined.to_csv(OUT / "gangnam_speed_volume.csv", index=False)
    return {"cells": len(d), "missing_cells": int(d.value.isna().sum()),
            "speed_volume_rows": len(joined), "paired_valid": int(joined[["value", "speed_kmh"]].notna().all(axis=1).sum()),
            "spatial_caveat": "D-35 유출 검지지점과 강남역→우성아파트 링크의 맥락 결합. 동일 공간 측정으로 간주하지 않음"}


def analyze():
    cfg, stations = read_yaml("followup_config.yaml"), registry()
    OUT.mkdir(parents=True, exist_ok=True)
    bus = analyze_bus(cfg, stations)
    print("버스 구간 지수 완료", flush=True)
    counts = analyze_counts(cfg, stations)
    speed, roads = analyze_roads(cfg)
    volume = analyze_volume(cfg, speed)
    extraction = json.loads((OUT / "extraction_audit.json").read_text())
    expected = set(pd.date_range("2024-04-01", "2024-08-31").strftime("%Y%m%d"))
    source_quality = {}
    for kind in VALUES:
        entries = [x for x in extraction if kind in x["path"]]
        actual = {date for entry in entries for date in entry["dates"]}
        source_quality[kind] = {"rows_scanned": sum(x["rows_scanned"] for x in entries),
                                "missing_calendar_dates": sorted(expected - actual), "expected_calendar_days": len(expected)}
    audit = {"bus_time": bus, **counts, "roads": roads, "volume": volume,
             "config_sha256": sha256(CASE / "followup_config.yaml"), "policy_sha256": sha256(CASE / "followup-policy.yaml"),
             "code_sha256": sha256(Path(__file__)), "sources_sha256": sha256(CASE / "followup-sources.json"),
             "pre_dates": periods(cfg)[0], "post_dates": periods(cfg)[1],
             "bus_source_coverage": source_quality,
             "bus_units": "unverified; dimensionless positive-record index only",
             "causal_status": "not_identified", "historical_route_id_name": "unverified"}
    write_json(OUT / "audit.json", audit)
    print("수요·공급·주변 도로·교통량 분석 완료", flush=True)
