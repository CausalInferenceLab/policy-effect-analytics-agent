"""같은 버스 구간의 전년·날씨·가을 비교와 정책 후보 노선의 관측 경로를 점검한다."""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, write_json
from .directional_data import OUT, collect_history
from .followup import clean_duplicates, registry

CELL = ["group", "route", "stop", "arrival", "hour"]


def expected_dates(cfg):
    return [str(d.date()) for month in cfg["months"] for d in pd.date_range(month + "-01", periods=pd.Period(month).days_in_month)]


def holiday_set(cfg):
    import holidays

    contract = read_yaml("data_contract.yaml")["checks"]["holidays"]
    expected = set(contract["dates"]) | set(cfg["holiday_extension"]["dates"])
    actual = {str(d) for d in holidays.KR(years=[2023, 2024]) if "2023-01-01" <= str(d) <= "2024-10-31"}
    if expected != actual:
        raise ValueError("공식 대조 공휴일 목록과 패키지 결과가 다릅니다")
    return expected


def period_dates(cfg, source_dates=None):
    closed = holiday_set(cfg)
    result = {}
    for name, (start, end) in cfg["periods"].items():
        dates = [str(d.date()) for d in pd.date_range(start, end) if d.dayofweek < 5 and str(d.date()) not in closed]
        result[name] = dates if source_dates is None else [d for d in dates if d in source_dates]
    return result


def extended_registry():
    stations = registry()
    pairs = set()
    manifest = json.loads((CASE / "directional-history-sources.json").read_text())
    for entry in manifest["files"]:
        path = CASE / entry["path"]
        if sha256(path) != entry["sha256"]:
            raise ValueError("역사적 정류장 원본 해시 불일치")
        data = pd.read_csv(path, encoding="cp949", dtype=str, usecols=["표준버스정류장ID", "버스정류장ARS번호"])
        pairs.update(map(tuple, data.to_numpy()))
    stations["historical_2023_pair"] = [(s, a) in pairs for s, a in zip(stations.stop, stations.ars, strict=True)]
    stations.to_csv(OUT / "station_registry.csv", index=False)
    return stations


def read_bus(kind, cfg):
    entries = [x for x in json.loads((OUT / "extraction_audit.json").read_text()) if x["kind"] == kind]
    expected_months = set(cfg["months"] + cfg.get("boundary_months", []))
    if {x["month"] for x in entries} != expected_months:
        raise ValueError(f"필수 월의 추출이 완료되지 않았습니다: {kind}")
    frames = []
    values = [f"h{h:02}" for h in cfg["hours"]]
    for entry in entries:
        path = CASE / entry["path"]
        if not path.resolve().is_relative_to((CASE / "data").resolve()) or sha256(path) != entry["sha256"]:
            raise ValueError("버스 캐시 경로 또는 해시 오류")
        frame = pd.read_parquet(path)
        frames.append(frame[[c for c in frame if not c.startswith("h") or c in values]])
    d = pd.concat(frames, ignore_index=True)
    keys = ["date", "route", "stop", "sequence"] + (["arrival", "arrival_sequence"] if kind == "bus_time" else [])
    d, audit = clean_duplicates(d, keys)
    d["date"] = pd.to_datetime(d.date, format="%Y%m%d", errors="raise").dt.strftime("%Y-%m-%d")
    d = d[d.date.str[:7].isin(cfg["months"]) & d.route.ne("0")].copy()
    audit.update(selected_rows=len(d), missing_cells=int(d[values].isna().sum().sum()), zero_cells=int(d[values].eq(0).sum().sum()),
                 negative_cells=int(d[values].lt(0).sum().sum()), rows_scanned=sum(x["rows_scanned"] for x in entries))
    source_dates = {pd.Timestamp(date).strftime("%Y-%m-%d") for x in entries for date in x["dates"]}
    audit["source_missing_dates"] = sorted(set(expected_dates(cfg)) - source_dates)
    audit["source_available_dates"] = sorted(set(expected_dates(cfg)) & source_dates)
    quality = d.assign(missing=d[values].isna().sum(axis=1), zero=d[values].eq(0).sum(axis=1), positive=d[values].gt(0).sum(axis=1)).groupby("date").agg(
        rows=("route", "size"), routes=("route", "nunique"), missing=("missing", "sum"), zero=("zero", "sum"), positive=("positive", "sum"))
    quality.reindex(expected_dates(cfg)).rename_axis("date").to_csv(OUT / f"quality_{kind}.csv")
    return d, audit


def time_panel(wide, stations, cfg):
    repeated = wide.duplicated(["date", "route", "stop", "arrival"], keep=False)
    d = wide[~repeated].copy()
    info = stations.set_index("stop")
    for endpoint, prefix in (("stop", "from"), ("arrival", "to")):
        for col in ("group", "order", "historical_id_ars_pair", "historical_2023_pair"):
            d[f"{prefix}_{col}"] = d[endpoint].map(info[col])
    valid = d.from_group.eq(d.to_group) & d.from_group.isin(cfg["primary_groups"] + cfg["secondary_groups"])
    valid &= d.from_group.eq("curb_south") | d.to_order.gt(d.from_order)
    historical = d.from_historical_id_ars_pair.eq(True) & d.to_historical_id_ars_pair.eq(True)
    historical &= d.from_historical_2023_pair.eq(True) & d.to_historical_2023_pair.eq(True)
    valid &= d.from_group.eq("curb_south") | historical
    d = d.loc[valid].copy()
    d["group"] = d.from_group
    d = d.melt(id_vars=["date", "route", "stop", "arrival", "group"], value_vars=[f"h{h:02}" for h in cfg["hours"]],
               var_name="hour", value_name="value")
    d["hour"] = d.hour.str[1:].astype(int)
    d.loc[d.value.le(0), "value"] = np.nan
    if d.duplicated(["date", *CELL]).any():
        raise ValueError("동일 구간의 날짜·시각 키 중복")
    return d, int(repeated.sum())


def select_cells(d, periods, minimum, cohort):
    def baseline(name):
        x = d[d.date.isin(periods[name])].groupby(CELL, observed=True).value.agg(["mean", "count"])
        return x[x["count"].ge(len(periods[name]) * minimum) & x["mean"].gt(0)].rename(
            columns={"mean": "baseline_" + name[-4:], "count": "pre_count_" + name[-4:]})
    selected = baseline("pre2024")
    if cohort != "2024_pre_calendar":
        selected = selected.join(baseline("pre2023"), how="inner")
    else:
        selected["baseline_2023"] = np.nan
    if cohort == "summer_survivors_source_days":
        for name in ("post2023", "post2024"):
            count = d[d.date.isin(periods[name])].groupby(CELL, observed=True).value.count()
            selected = selected.join(count.rename(name + "_count"), how="left")
            selected = selected[selected[name + "_count"].ge(len(periods[name]) * minimum)]
    return selected.reset_index()


def daily_index(d, selected, dates, cfg, aggregate):
    if selected.empty:
        return pd.DataFrame(columns=[*aggregate, "date", "index", "observed", "coverage"])
    merged = d.merge(selected[CELL + ["baseline_2023", "baseline_2024"]], on=CELL, validate="many_to_one")
    baseline = merged.baseline_2024.where(merged.date.str.startswith("2024"), merged.baseline_2023)
    merged["index"] = 100 * merged.value / baseline
    count = selected.groupby(aggregate).size().rename("selected_cells")
    daily = merged.groupby([*aggregate, "date"]).agg(index=("index", "mean"), observed=("index", "count"))
    groups = selected[aggregate].drop_duplicates()
    expected = groups.merge(pd.DataFrame({"date": dates}), how="cross").set_index([*aggregate, "date"]).index
    daily = daily.reindex(expected).join(count, on=aggregate)
    daily["coverage"] = daily.observed.fillna(0) / daily.selected_cells
    daily.loc[daily.coverage.lt(cfg["minimum_coverage"]), "index"] = np.nan
    return daily.reset_index()


def week_means(frame, draws, rng):
    """관측 날짜를 달력 주로 묶어 주 전체를 재표집한다."""
    d = frame.dropna(subset=["index"]).copy()
    if d.empty:
        return None
    d["week"] = pd.to_datetime(d.date).dt.to_period("W-SUN").astype(str)
    weeks = d.groupby("week")["index"].agg(["sum", "count"])
    if len(weeks) < 2:
        return None
    multiplicity = rng.multinomial(len(weeks), np.full(len(weeks), 1 / len(weeks)), size=draws)
    return (multiplicity @ weeks["sum"].to_numpy()) / (multiplicity @ weeks["count"].to_numpy())


def compare(daily, before, after, cfg):
    a, b = daily[daily.date.isin(before)], daily[daily.date.isin(after)]
    av, bv = a["index"].dropna(), b["index"].dropna()
    ac, bc = a.coverage.mean(), b.coverage.mean()
    change = 100 * (bv.mean() / av.mean() - 1) if len(av) and len(bv) and av.mean() else None
    rng = np.random.default_rng(cfg["bootstrap"]["seed"])
    boot_a = week_means(a, cfg["bootstrap"]["draws"], rng)
    boot_b = week_means(b, cfg["bootstrap"]["draws"], rng)
    interval = [None, None] if boot_a is None or boot_b is None else np.quantile(100 * (boot_b / boot_a - 1), [.025, .975]).tolist()
    passed = (len(av) >= cfg["minimum_days"] and len(bv) >= cfg["minimum_days"] and pd.notna(ac) and pd.notna(bc)
              and abs(ac - bc) <= cfg["maximum_coverage_gap"])
    return {"before_mean": float(av.mean()) if len(av) else None, "after_mean": float(bv.mean()) if len(bv) else None,
            "change_pct": float(change) if change is not None else None, "before_days": len(av), "after_days": len(bv),
            "before_coverage": float(ac) if pd.notna(ac) else None, "after_coverage": float(bc) if pd.notna(bc) else None,
            "quality_pass": bool(passed), "week_bootstrap_low": interval[0], "week_bootstrap_high": interval[1]}


def index_analysis(d, stations, audit, cfg):
    calendar = period_dates(cfg)
    source = period_dates(cfg, set(audit["source_available_dates"]))
    cohorts = ["2024_pre_calendar", "common_pre_calendar", "common_pre_source_days", "summer_survivors_source_days"]
    summary, daily_frames, pair_summary, selections = [], [], [], []
    dates = expected_dates(cfg)
    links = stations.set_index("stop")
    for cohort in cohorts:
        periods = source if "source_days" in cohort else calendar
        selected = select_cells(d, periods, cfg["minimum_coverage"], cohort)
        selections.append(selected.assign(cohort=cohort))
        daily = daily_index(d, selected, dates, cfg, ["group"])
        daily_frames.append(daily.assign(cohort=cohort))
        pair_daily = daily_index(d, selected, dates, cfg, ["group", "stop", "arrival"])
        contrasts = [("summer2024", "pre2024", "post2024"), ("autumn2024", "pre2024", "autumn2024")]
        if cohort != "2024_pre_calendar":
            contrasts.insert(0, ("summer2023", "pre2023", "post2023"))
        for label, pre, post in contrasts:
            for group, part in daily.groupby("group"):
                summary.append({"cohort": cohort, "group": group, "comparison": label,
                                "selected_cells": int(selected.group.eq(group).sum()), **compare(part, periods[pre], periods[post], cfg)})
            for (group, stop, arrival), part in pair_daily.groupby(["group", "stop", "arrival"]):
                a, b = links.loc[stop], links.loc[arrival]
                pair_summary.append({"cohort": cohort, "group": group, "comparison": label, "stop": stop, "arrival": arrival,
                                     "from_ars": a.ars, "to_ars": b.ars, "from_name": a["name"], "to_name": b["name"],
                                     "adjacent": bool(b.order == a.order + 1), "order": int(a.order),
                                     **compare(part, periods[pre], periods[post], cfg)})
    daily = pd.concat(daily_frames, ignore_index=True)
    pd.DataFrame(summary).to_csv(OUT / "index_comparisons.csv", index=False)
    pd.DataFrame(pair_summary).to_csv(OUT / "segment_comparisons.csv", index=False)
    pd.concat(selections, ignore_index=True).to_csv(OUT / "selected_cells.csv", index=False)
    daily.to_csv(OUT / "daily_indices.csv", index=False)
    # 이 수치는 계절 참고 차이이며 전년을 검증된 인과 대조군으로 지정하지 않는다.
    s = pd.DataFrame(summary)
    seasonal = s[s.comparison.eq("summer2024")].merge(s[s.comparison.eq("summer2023")], on=["cohort", "group"], suffixes=("_2024", "_2023"), validate="one_to_one")
    seasonal["difference_percentage_points"] = seasonal.change_pct_2024 - seasonal.change_pct_2023
    seasonal.to_csv(OUT / "seasonal_reference.csv", index=False)
    return daily


def standardize_weather(frame, before, after, strata, minimum_per_stratum=2):
    """양쪽에서 관측된 기상 층에 같은 가중치를 적용하며 제외된 표본 수를 공개한다."""
    a = frame[frame.date.isin(before)].dropna(subset=["index", *strata]).copy()
    b = frame[frame.date.isin(after)].dropna(subset=["index", *strata]).copy()
    x = a.groupby(strata, observed=True)["index"].agg(["mean", "count"])
    y = b.groupby(strata, observed=True)["index"].agg(["mean", "count"])
    joined = x.join(y, how="inner", lsuffix="_before", rsuffix="_after")
    joined = joined[(joined.count_before >= minimum_per_stratum) & (joined.count_after >= minimum_per_stratum)].copy()
    if joined.empty:
        return {"before_mean": None, "after_mean": None, "change_pct": None, "before_used": 0, "after_used": 0,
                "before_total": len(a), "after_total": len(b), "before_retained": 0., "after_retained": 0., "strata": 0}, joined
    joined["weight"] = .5 * (joined.count_before / len(a) + joined.count_after / len(b))
    joined["weight"] /= joined.weight.sum()
    before_mean, after_mean = (joined.mean_before * joined.weight).sum(), (joined.mean_after * joined.weight).sum()
    return {"before_mean": float(before_mean), "after_mean": float(after_mean), "change_pct": float(100 * (after_mean / before_mean - 1)),
            "before_used": int(joined.count_before.sum()), "after_used": int(joined.count_after.sum()),
            "before_total": len(a), "after_total": len(b), "before_retained": float(joined.count_before.sum() / len(a)),
            "after_retained": float(joined.count_after.sum() / len(b)), "strata": len(joined)}, joined.reset_index()


def weather_analysis(daily, audit, cfg):
    weather = pd.read_csv(OUT / "weather_daily.csv")
    if weather.date.duplicated().any():
        raise ValueError("기상 날짜 중복")
    periods = period_dates(cfg, set(audit["source_available_dates"]))
    d = daily[daily.cohort.eq("common_pre_source_days")].merge(weather, on="date", how="left", validate="many_to_one")
    if d.temperature_mean_c.isna().any():
        raise ValueError("기상 결합 누락 또는 평균기온 결측")
    rows, strata_rows, weather_rows = [], [], []
    contrasts = [("summer2023", "pre2023", "post2023"), ("summer2024", "pre2024", "post2024"), ("autumn2024", "pre2024", "autumn2024")]
    for label, pre, post in contrasts:
        for group, part in d.groupby("group"):
            index_quality = compare(part, periods[pre], periods[post], cfg)["quality_pass"]
            for name, strata in {"weekday": ["weekday"], "rain_record": ["rain_group"],
                                 "rain_temperature": ["rain_group", "temperature_bin"],
                                 "rain_temperature_weekday": ["rain_group", "temperature_bin", "weekday"]}.items():
                result, cells = standardize_weather(part, periods[pre], periods[post], strata)
                result["support_pass"] = bool(result["before_used"] >= cfg["minimum_days"] and result["after_used"] >= cfg["minimum_days"]
                                              and result["before_retained"] >= cfg["minimum_coverage"] and result["after_retained"] >= cfg["minimum_coverage"])
                result["index_quality_pass"] = index_quality
                result["usable_comparison"] = index_quality and result["support_pass"]
                rows.append({"comparison": label, "group": group, "scheme": name, **result})
                if not cells.empty:
                    strata_rows.append(cells.assign(comparison=label, group=group, scheme=name))
            for rain, subset in part.groupby("rain_group"):
                result = compare(subset, periods[pre], periods[post], {**cfg, "minimum_days": cfg["minimum_stratum_days"]})
                rows.append({"comparison": label, "group": group, "scheme": "stratum_" + rain, **result})
    for label, dates in periods.items():
        part = weather[weather.date.isin(dates)]
        weather_rows.append({"period": label, "days": len(part), "mean_temperature_c": part.temperature_mean_c.mean(),
                             **{f"days_{g}": int(part.rain_group.eq(g).sum()) for g in cfg["weather"]["groups"]}})
    pd.DataFrame(rows).to_csv(OUT / "weather_comparisons.csv", index=False)
    if strata_rows:
        pd.concat(strata_rows, ignore_index=True).to_csv(OUT / "weather_common_strata.csv", index=False)
    pd.DataFrame(weather_rows).to_csv(OUT / "period_weather.csv", index=False)


def route_candidates():
    cfg, policy = read_yaml("directional_config.yaml"), read_yaml("followup-policy.yaml")
    master = pd.read_csv(CASE / "data/discovery/route_master.csv", encoding="cp949", dtype=str).set_index("노선_ID")
    rows = []
    for group, spec in policy["groups"].items():
        for family in spec["families"]:
            ids = policy["candidate_route_ids"][group] + cfg["additional_route_candidates"].get(family, [])
            for route in ids:
                name = re.match(r"[A-Za-z0-9-]+", master.loc[route, "노선_명칭"]).group()
                accepted = {family, family + "A", family + "B"} if group == "reverse_evening" else {family}
                if name in accepted:
                    rows.append({"family": family, "policy_group": group, "route": route,
                                 "current_name": master.loc[route, "노선_명칭"], "historical_id_name": "unverified"})
    return pd.DataFrame(rows).drop_duplicates()


def positive_presence(wide, hours):
    """같은 날짜·노선·정류장의 재방문은 기록 존재 여부의 합집합으로만 집계한다."""
    d = wide.assign(positive=wide[[f"h{h:02}" for h in hours]].gt(0).any(axis=1))
    return d.groupby(["date", "route", "stop"]).positive.max().reset_index()


def route_analysis(wide, audit, stations, cfg):
    candidates = route_candidates()
    # 순번이 여러 개인 방문도 '있음'의 합집합에는 쓸 수 있다. 운행횟수 합계에는 쓰지 않는다.
    d = wide[wide.route.isin(candidates.route) & wide.stop.isin(stations.stop)].copy()
    presence = positive_presence(d, cfg["hours"])
    presence = presence[presence.positive].merge(candidates, on="route", validate="many_to_one")
    presence = presence.merge(stations[["stop", "ars", "group", "mapping_status"]], on="stop", validate="many_to_one")
    periods = period_dates(cfg, set(audit["source_available_dates"]))
    records, family_rows = [], []
    for period in ("pre2024", "post2024", "autumn2024"):
        dates = periods[period]
        part = presence[presence.date.isin(dates)]
        for row in candidates.itertuples():
            candidate = part[part.route.eq(row.route)]
            for group in cfg["primary_groups"] + cfg["secondary_groups"]:
                observed = candidate[candidate.group.eq(group)]
                records.append({"family": row.family, "policy_group": row.policy_group, "route": row.route,
                                "current_name": row.current_name, "historical_id_name": row.historical_id_name,
                                "period": period, "group": group, "source_available_days": len(dates),
                                "positive_record_days": observed.date.nunique(), "observed_ars": ";".join(sorted(observed.ars.unique())),
                                "has_provisional_station": bool(observed.mapping_status.eq("provisional_current_master").any())})
        for (family, group), family_ids in candidates.groupby(["family", "policy_group"]):
            observed = part[part.family.eq(family)]
            row = {"family": family, "policy_group": group, "period": period, "source_available_days": len(dates),
                   "candidate_ids": ";".join(sorted(family_ids.route.unique())), "observed_ids": ";".join(sorted(observed.route.unique())),
                   "historical_id_name": "unverified"}
            for stop_group in cfg["primary_groups"] + cfg["secondary_groups"]:
                section = observed[observed.group.eq(stop_group)]
                row[stop_group + "_days"] = section.date.nunique()
                row[stop_group + "_ars"] = ";".join(sorted(section.ars.unique()))
            family_rows.append(row)
    pd.DataFrame(records).to_csv(OUT / "route_movement.csv", index=False)
    families = pd.DataFrame(family_rows)
    families.to_csv(OUT / "family_movement.csv", index=False)
    changes = []
    policy = read_yaml("followup-policy.yaml")
    for family, rows in families.groupby("family"):
        rows = rows.set_index("period")
        def stop_set(period, group, records=rows):
            return set(filter(None, records.loc[period, group + "_ars"].split(";")))
        row = {"family": family, "policy_group": rows.policy_group.iloc[0], "source": policy["source"],
               "source_page": policy["groups"][rows.policy_group.iloc[0]]["page"], "effective_date": policy["effective"],
               "candidate_ids": rows.candidate_ids.iloc[0], "historical_id_name": "unverified"}
        for group in cfg["primary_groups"] + cfg["secondary_groups"]:
            pre, post, fall = [stop_set(period, group) for period in ("pre2024", "post2024", "autumn2024")]
            row[group + "_removed"] = ";".join(sorted(pre - post))
            row[group + "_added"] = ";".join(sorted(post - pre))
            row[group + "_added_still_observed_autumn"] = ";".join(sorted((post - pre) & fall))
        changes.append(row)
    pd.DataFrame(changes).to_csv(OUT / "route_path_changes.csv", index=False)
    return {"candidate_ids": len(candidates), "policy_families": candidates.family.nunique(),
            "candidate_ids_with_positive_records": presence.route.nunique(),
            "positive_presence_rule": "same_date_route_stop_any_positive_across_sequences; not_a_trip_total"}


def station_records(wide, stations, cfg, kind):
    repeated = wide.duplicated(["date", "route", "stop"], keep=False)
    d = wide[~repeated & wide.stop.isin(stations.stop)].copy()
    values = [f"h{h:02}" for h in cfg["hours"]]
    d[values] = d[values].where(d[values] > 0)
    d["subtotal"] = d[values].sum(axis=1, min_count=1)
    d["positive_cells"] = d[values].notna().sum(axis=1)
    daily = d.groupby(["date", "stop"]).agg(recorded_subtotal=("subtotal", lambda x: x.sum(min_count=1)),
                                             positive_cells=("positive_cells", "sum"), rows=("route", "size")).reset_index()
    daily["positive_fraction"] = daily.positive_cells / (daily.rows * len(values))
    results = []
    for period, dates in period_dates(cfg).items():
        part = daily[daily.date.isin(dates)]
        for stop, rows in part.groupby("stop"):
            results.append({"kind": kind, "stop": stop, "period": period, "recorded_subtotal_daily_mean": rows.recorded_subtotal.mean(),
                            "days_with_positive_records": int(rows.recorded_subtotal.notna().sum()),
                            "positive_fraction_of_present": rows.positive_fraction.mean()})
    pd.DataFrame(results).merge(stations, on="stop", validate="many_to_one").to_csv(OUT / f"station_{kind}.csv", index=False)
    return int(repeated.sum())


def mechanism_alignment():
    segments = pd.read_csv(OUT / "segment_comparisons.csv", dtype={"arrival": str})
    segments = segments[segments.cohort.eq("common_pre_source_days") & segments.comparison.eq("summer2024") & segments.adjacent]
    counts = pd.read_csv(OUT / "station_bus_trips.csv", dtype={"stop": str})
    before = counts[counts.period.eq("pre2024")].set_index("stop")
    after = counts[counts.period.eq("post2024")].set_index("stop")
    rows = []
    for row in segments.to_dict("records"):
        stop = row["arrival"]
        if stop not in before.index or stop not in after.index:
            continue
        a, b = before.loc[stop], after.loc[stop]
        change = 100 * (b.recorded_subtotal_daily_mean / a.recorded_subtotal_daily_mean - 1)
        rows.append({**row, "arrival_recorded_trips_change_pct": change,
                     "arrival_recorded_trips_pre": a.recorded_subtotal_daily_mean, "arrival_recorded_trips_post": b.recorded_subtotal_daily_mean,
                     "trip_positive_fraction_pre": a.positive_fraction_of_present, "trip_positive_fraction_post": b.positive_fraction_of_present,
                     "same_change_sign": bool(change * row["change_pct"] > 0),
                     "interpretation": "기록된 정류장 횟수와 구간 지수의 동반 변화. 인과·대기행렬 측정 아님"})
    pd.DataFrame(rows).to_csv(OUT / "mechanism_alignment.csv", index=False)


def analyze():
    cfg = read_yaml("directional_config.yaml")
    OUT.mkdir(parents=True, exist_ok=True)
    collect_history()
    stations = extended_registry()
    wide, time_audit = read_bus("bus_time", cfg)
    d, quarantined = time_panel(wide, stations, cfg)
    time_audit["revisited_segment_rows_quarantined"] = quarantined
    daily = index_analysis(d, stations, time_audit, cfg)
    print("전년·가을 동일 구간 지수 비교 완료", flush=True)
    weather_analysis(daily, time_audit, cfg)
    print("기상 층별 비교와 공통 범위 점검 완료", flush=True)
    del d, wide
    audits = {"bus_time": time_audit}
    for kind in ("bus_trips", "bus_boardings"):
        wide, audits[kind] = read_bus(kind, cfg)
        if kind == "bus_trips":
            audits["route_movement"] = route_analysis(wide, audits[kind], stations, cfg)
        audits[kind]["revisited_stop_rows_excluded_from_subtotals"] = station_records(wide, stations, cfg, kind)
    mechanism_alignment()
    write_json(OUT / "audit.json", {**audits, "calendar_period_dates": period_dates(cfg),
                                    "config_sha256": sha256(CASE / "directional_config.yaml"), "code_sha256": sha256(Path(__file__)),
                                    "causal_status": "not_identified", "travel_time_unit": "unverified_dimensionless_only"})
    print("노선 이동·정류장 기록·동반 변화 점검 완료", flush=True)
