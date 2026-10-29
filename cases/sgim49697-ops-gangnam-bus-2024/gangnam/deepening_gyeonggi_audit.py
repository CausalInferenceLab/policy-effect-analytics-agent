"""경기 대표일 집계의 중복·설명 연도·승하차와 시간 합계를 대조한다."""

import json

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .deepening_gyeonggi_parse import CONFIG, OUT, RAW, aliases

BASE = ["year", "city", "month", "route", "day_type"]
KEY_EXTRA = {"hourly": ["hour"], "daily": ["detail"], "trips": []}
TRIP_NAMES = [f"{kind}_{action}" for kind in ["single", "transfer", "total"] for action in ["boarding", "alighting", "combined"]]


def canonical_records(frame, family):
    """설명 열을 제외한 같은 키·같은 값은 대조용 한 표현으로만 만든다."""
    keys = BASE + KEY_EXTRA[family]
    values = [f"v{i}" for i in range(9 if family == "trips" else 1)]
    unique = frame.drop_duplicates(keys + values)
    versions = unique.groupby(keys, dropna=False).size().rename("value_versions")
    descriptions = frame.groupby(keys, dropna=False).terminal.nunique(dropna=False).rename("terminal_versions")
    grouped = frame.groupby(keys, dropna=False).size().rename("source_rows").to_frame().join([versions, descriptions]).reset_index()
    full_key = keys + ["terminal"]
    full_unique = frame.drop_duplicates(full_key + values)
    full_conflicts = full_unique.groupby(full_key, dropna=False).size().gt(1)
    summary = dict(year=int(frame.year.iloc[0]), family=family, rows=len(frame), natural_keys=len(grouped),
                   repeated_full_key_rows=int(frame.duplicated(full_key, keep=False).sum()),
                   identical_full_row_excess=len(frame) - len(full_unique),
                   full_keys_with_conflicting_values=int(full_conflicts.sum()),
                   natural_keys_with_conflicting_values=int(grouped.value_versions.gt(1).sum()),
                   natural_keys_with_multiple_terminal_descriptions=int(grouped.terminal_versions.gt(1).sum()),
                   rows_with_missing_value=int(frame[values].isna().any(axis=1).sum()),
                   rows_with_negative_value=int(frame[values].lt(0).any(axis=1).sum()))
    keep = unique[~unique.duplicated(keys, keep=False)].merge(grouped, on=keys, validate="one_to_one")
    return keep, grouped, summary


def compare_pair(frame, label, left, right, eligible=None):
    d = frame.copy()
    d["check"] = label
    d["left"] = left
    d["right"] = right
    known = d.left.notna() & d.right.notna() & np.isfinite(d.left) & np.isfinite(d.right)
    if eligible is None:
        eligible = pd.Series(True, index=d.index)
    d["difference"] = d.left - d.right
    d["status"] = np.select([~known, ~eligible, d.difference.eq(0)],
                             ["missing_component", "incomplete_hour_coverage", "equal"], default="mismatch")
    columns = BASE + ["check", "left", "right", "difference", "status"]
    columns += [c for c in ["observed_hours", "required_hours"] if c in d]
    return d[columns]


def arithmetic_checks(parts):
    trip = parts["trips"]
    pairs = [("single_boarding_plus_alighting", trip.v0 + trip.v1, trip.v2),
             ("transfer_boarding_plus_alighting", trip.v3 + trip.v4, trip.v5),
             ("total_boarding_plus_alighting", trip.v6 + trip.v7, trip.v8),
             ("boarding_single_plus_transfer", trip.v0 + trip.v3, trip.v6),
             ("alighting_single_plus_transfer", trip.v1 + trip.v4, trip.v7),
             ("combined_single_plus_transfer", trip.v2 + trip.v5, trip.v8)]
    results = [compare_pair(trip, label, left, right) for label, left, right in pairs]
    daily = parts["daily"]
    merged = daily[daily.detail.eq("전일")][BASE + ["v0"]].merge(trip[BASE + ["v8"]], on=BASE, how="outer", validate="one_to_one")
    results.append(compare_pair(merged, "daily_combined_vs_trip_combined", merged.v0, merged.v8))
    hours = parts["hourly"]
    for label, allowed, detail in [("all_hours_vs_daily_combined", list(range(24)), "전일"),
                                   ("daytime_hours_vs_daily_combined", list(range(7, 19)), "주간")]:
        h = hours[hours.hour.isin(allowed)]
        sums = h.groupby(BASE).agg(hour_sum=("v0", lambda v: v.sum(min_count=1)),
                                  observed_hours=("v0", "count"), unique_hours=("hour", "nunique")).reset_index()
        d = daily[daily.detail.eq(detail)][BASE + ["v0"]].merge(sums, on=BASE, how="outer", validate="one_to_one")
        d["required_hours"] = len(allowed)
        eligible = d.observed_hours.eq(len(allowed)) & d.unique_hours.eq(len(allowed))
        results.append(compare_pair(d, label, d.hour_sum, d.v0, eligible))
    return pd.concat(results, ignore_index=True)


def save_csv(name, frame):
    frame.to_csv(OUT / name, index=False, lineterminator="\n")


def run():
    cfg = read_yaml(CONFIG)
    extraction_path = OUT / "extraction.json"
    extraction = json.loads(extraction_path.read_text())
    if extraction["configuration_sha256"] != sha256(CONFIG):
        raise ValueError("extraction configuration changed")
    names = aliases(cfg)
    summaries, file_rows, coverage_rows, target_rows, target_checks, check_counts, examples = [], [], [], [], [], [], []
    for year in cfg["years"]:
        parts = {}
        for family in ["hourly", "daily", "trips"]:
            entries = [x for x in extraction["files"] if x["year"] == year and x["family"] == family]
            if not entries:
                raise ValueError("missing workbook family/year")
            frames = []
            for entry in entries:
                path = CASE / entry["path"]
                if sha256(path) != entry["sha256"]:
                    raise ValueError("cached workbook checksum changed")
                frames.append(pd.read_parquet(path))
                file_rows.append({k: entry[k] for k in ["source", "member", "year", "family", "declared_rows", "declared_columns", "rows", "xml_rows_scanned", "fully_blank_xml_rows", "blank_first", "blank_last", "missing_values", "zero_values", "negative_values", "name_candidate_rows"]}
                                 | {k: ";".join(entry[k]) for k in ["statistics_years", "route_description_years", "route_description_months"]})
            frame = pd.concat(frames, ignore_index=True)
            if set(frame.year) != {year} or year >= cfg["locked_year"]:
                raise ValueError("locked or unexpected year in extracted values")
            parts[family], grouped, summary = canonical_records(frame, family)
            summaries.append(summary)
            targets = frame[frame.policy_name.ne("")]
            keys = ["year", "city", "route", "day_type", "policy_name"]
            cov = targets.groupby(keys).agg(source_rows=("route", "size"), months=("month", "nunique"),
                                            month_list=("month", lambda v: ";".join(str(x) for x in sorted(set(v)))),
                                            terminal_descriptions=("terminal", "nunique"),
                                            terminal_names=("terminal", lambda v: " | ".join(sorted(set(v))))).reset_index()
            grouped["policy_name"] = grouped.route.map(names).fillna("")
            target_quality = grouped[grouped.policy_name.ne("")].groupby(keys).agg(
                natural_keys=("route", "size"),
                value_conflict_keys=("value_versions", lambda v: int(v.gt(1).sum())),
                multiple_description_keys=("terminal_versions", lambda v: int(v.gt(1).sum()))).reset_index()
            cov = cov.merge(target_quality, on=keys, validate="one_to_one")
            cov["family"] = family
            coverage_rows.append(cov)
            trouble = grouped[grouped.terminal_versions.gt(1) | grouped.value_versions.gt(1)]
            trouble[trouble.route.isin(names)].assign(family=family).to_parquet(RAW / f"target_key_ambiguities_{year}_{family}.parquet", index=False)
            # Public examples document the schema issue; all keys remain in local audit artifacts.
            keys_for_example = trouble.head(8)[BASE + KEY_EXTRA[family]]
            if len(keys_for_example):
                example = frame.merge(keys_for_example, on=BASE + KEY_EXTRA[family], validate="many_to_one")
                examples.append(example.drop_duplicates(BASE + KEY_EXTRA[family] + ["terminal", "v0"])[
                    ["year", "family", "city", "month", "route", "day_type", "detail", "terminal", "v0"]])
            del frame, frames, grouped, targets
        checks = arithmetic_checks(parts)
        checks.to_parquet(RAW / f"all_arithmetic_checks_{year}.parquet", index=False)
        check_counts.append(checks.groupby(["year", "check", "status"]).agg(
            records=("status", "size"), maximum_absolute_difference=("difference", lambda v: v.abs().max())).reset_index())
        target_checks.append(checks[checks.route.isin(names)])
        trips = parts["trips"]
        selected = trips[trips.route.isin(names)][BASE + ["terminal", "terminal_versions", "source_rows", *[f"v{i}" for i in range(9)]]].copy()
        selected["policy_name_candidate"] = selected.route.map(names)
        selected["historical_id_verified"] = False
        selected["sampling"] = "one_selected_weekday_or_saturday_in_month"
        target_rows.append(selected.rename(columns={f"v{i}": name for i, name in enumerate(TRIP_NAMES)}
                                          | {"terminal": "one_exported_terminal_description"}))
        print(f"{year}: key and arithmetic audit completed", flush=True)
    coverage = pd.concat(coverage_rows, ignore_index=True)
    presence = []
    for year in cfg["years"]:
        for name in cfg["policy_names"]:
            d = coverage[(coverage.year == year) & coverage.policy_name.eq(name)]
            presence.append(dict(year=year, policy_name=name, matching_names=";".join(sorted(set(d.route))),
                                 cities=";".join(sorted(set(d.city))), observed=bool(len(d)),
                                 status="name_candidate_not_id_confirmation" if len(d) else "no_exact_name_candidate_in_export"))
    save_csv("file_audit.csv", pd.DataFrame(file_rows))
    save_csv("key_audit.csv", pd.DataFrame(summaries))
    save_csv("candidate_coverage.csv", coverage)
    save_csv("policy_name_presence.csv", pd.DataFrame(presence))
    save_csv("candidate_representative_day_trips.csv", pd.concat(target_rows, ignore_index=True))
    save_csv("arithmetic_summary.csv", pd.concat(check_counts, ignore_index=True))
    save_csv("candidate_arithmetic_checks.csv", pd.concat(target_checks, ignore_index=True))
    if examples:
        save_csv("description_ambiguity_examples.csv", pd.concat(examples, ignore_index=True))
    write_json(OUT / "audit.json", dict(completed_at=utcnow(), configuration=cfg,
               configuration_sha256=sha256(CONFIG), extraction_sha256=sha256(extraction_path),
               code_sha256=sha256(__file__), outputs={name: sha256(OUT / name) for name in [
                   "file_audit.csv", "key_audit.csv", "candidate_coverage.csv", "policy_name_presence.csv",
                   "candidate_representative_day_trips.csv", "arithmetic_summary.csv",
                   "candidate_arithmetic_checks.csv", "description_ambiguity_examples.csv"]},
               limitations=["no historical route identifier in actual exports", "representative dates unavailable", "canonical values used only for internal arithmetic checks"]))
