"""폐선 이력과 고정 13개 노선 비교를 별도 경로에서 재현한다."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .followup import clean_duplicates
from .overnight_bus import make_time_panel
from .overnight_matched_directions import daily_paired, joint_directions, paired_gap
from .overnight_sensitivity import describe_comparison

OUT = CASE / "results/deepening/cohort"
RAW = CASE / "data/deepening/cohort"
STATES = ["positive", "zero", "negative", "blank", "row_absent", "source_date_absent"]


def load_narrow(scope, kind, routes, stops, window):
    """고정 원본의 검증된 추출물에서 목표 키만 읽되 모든 값 열로 중복을 검사한다."""
    audit_path = CASE / f"results/overnight/{scope}/extraction_audit.json"
    entries = [e for e in json.loads(audit_path.read_text()) if e["kind"] == kind]
    if not entries:
        raise ValueError("버스 추출 출처가 없습니다")
    pieces, dates = [], set()
    for entry in entries:
        if not "2023-01" <= entry["month"] <= "2025-08":
            raise ValueError("고정 역사 범위 밖의 버스 추출")
        path = CASE / entry["path"]
        if not path.resolve().is_relative_to((CASE / "data").resolve()) or sha256(path) != entry["sha256"]:
            raise ValueError("버스 추출 경로·해시 불일치")
        available = pd.to_datetime(entry["dates"], format="%Y%m%d").strftime("%Y-%m-%d")
        if any(d.startswith("2026") for d in available):
            raise ValueError("잠금 연도 발견")
        dates.update(available)
        piece = pd.read_parquet(path, filters=[("route", "in", routes), ("stop", "in", stops)])
        pieces.append(piece)
    keys = ["date", "route", "stop", "sequence"]
    if kind == "bus_time":
        keys += ["arrival", "arrival_sequence"]
    frame, duplicate_audit = clean_duplicates(pd.concat(pieces, ignore_index=True), keys)
    frame["date"] = pd.to_datetime(frame.date, format="%Y%m%d").dt.strftime("%Y-%m-%d")

    def eligible(date):
        return window[0] <= date <= window[1] and (date >= "2025-05-01") == (scope == "forecast_bus_test")

    frame = frame[frame.date.map(eligible)].copy()
    dates = sorted(d for d in dates if eligible(d))
    return frame, {"audit_path": str(audit_path.relative_to(CASE)), "audit_sha256": sha256(audit_path),
                   "inputs": [{"path": e["path"], "sha256": e["sha256"]} for e in entries],
                   "duplicate_audit": duplicate_audit, "source_available_dates": dates, "selected_rows": len(frame)}


def accepted_dates_only(daily, reference):
    """날짜 집합을 원래 유효 일자로 제한하며 관측률 분모는 현재 고정 노선을 유지한다."""
    keys = ["date", "segment"]
    if daily.duplicated(keys).any() or reference.duplicated(keys).any():
        raise ValueError("일별 비교 키 중복")
    mask = reference[keys].assign(reference_accepted=reference["index"].notna())
    result = daily.merge(mask, on=keys, how="left", validate="one_to_one")
    if result.reference_accepted.isna().any():
        raise ValueError("원래 분석에 없는 날짜")
    result["index"] = result["index"].where(result.reference_accepted)
    return result.drop(columns="reference_accepted")


def count_records(wide, hours):
    repeated = wide.duplicated(["date", "route", "stop"], keep=False)
    frame = wide[~repeated].melt(id_vars=["date", "route", "stop"],
                                value_vars=[f"h{h:02}" for h in hours], var_name="hour", value_name="trip_value")
    frame["hour"] = frame.hour.str[1:].astype(int)
    frame["trip_status"] = np.select([frame.trip_value.isna(), frame.trip_value.eq(0), frame.trip_value.lt(0)],
                                      ["blank", "zero", "negative"], default="positive")
    if frame.duplicated(["date", "route", "stop", "hour"]).any():
        raise ValueError("횟수 기록 키 중복")
    return frame, int(repeated.sum())


def record_grid(panel, counts, routes, hours, days, legs, source_dates):
    grid = pd.MultiIndex.from_product([days, routes, ["south", "north"], hours],
                                     names=["date", "route", "segment", "hour"]).to_frame(index=False)
    grid = grid.merge(legs, on="segment", validate="many_to_one")
    keys = ["date", "route", "segment", "hour", "stop", "arrival"]
    grid = grid.merge(panel[keys + ["raw_value", "record_status"]], on=keys, how="left", validate="one_to_one")
    grid["record_status"] = grid.record_status.fillna("row_absent")
    grid.loc[~grid.date.isin(source_dates["bus_time"]), "record_status"] = "source_date_absent"
    for label, endpoint in [("departure", "stop"), ("arrival", "arrival")]:
        values = counts.rename(columns={"stop": endpoint, "trip_value": label + "_trips", "trip_status": label + "_status"})
        grid = grid.merge(values, on=["date", "route", endpoint, "hour"], how="left", validate="many_to_one")
        grid[label + "_status"] = grid[label + "_status"].fillna("row_absent")
        grid.loc[~grid.date.isin(source_dates["bus_trips"]), label + "_status"] = "source_date_absent"
    grid["month"] = grid.date.str[:7]
    grid["count_support"] = np.select([
        grid.departure_status.eq("positive") & grid.arrival_status.eq("positive"),
        grid.departure_status.isin(["positive", "zero"]) & grid.arrival_status.isin(["positive", "zero"])],
        ["both_endpoints_positive", "both_known_at_least_one_zero"], default="at_least_one_unknown_or_invalid")
    return grid


def monthly_states(grid):
    result = []
    keys = ["month", "route", "segment"]
    for label, column in [("time", "record_status"), ("departure_trips", "departure_status"), ("arrival_trips", "arrival_status")]:
        counts = grid.groupby(keys + [column]).size().unstack(fill_value=0).reindex(columns=STATES, fill_value=0)
        counts["expected_cell_days"] = counts.sum(axis=1)
        counts["metric"] = label
        result.append(counts.reset_index())
    return pd.concat(result, ignore_index=True)


def verify_reference(cfg):
    original = json.loads((CASE / cfg["reference_audit"]).read_text())
    for name, expected in original["inputs"].items():
        if sha256(CASE / name) != expected:
            raise ValueError(f"원래 공동 표본 입력 변경: {name}")
    folder = (CASE / cfg["reference_audit"]).parent
    for name, expected in original["outputs"].items():
        if sha256(folder / name) != expected:
            raise ValueError(f"원래 공동 표본 출력 변경: {name}")
    if sha256(CASE / original["baseline_path"]) != original["baseline_sha256"]:
        raise ValueError("원래 공동 표본 기준값 변경")
    return original


def run():
    cfg = read_yaml("deepening_cohort_config.yaml")
    reference_cfg = read_yaml(cfg["reference_config"])
    shape = read_yaml(reference_cfg["base_config"])
    if cfg["locked_year"] != 2026 or cfg["record_window"] != ["2023-01-01", "2025-08-31"]:
        raise ValueError("구성 민감도 범위 잠금 오류")
    reference = verify_reference(cfg)
    closure = json.loads((CASE / cfg["closure_evidence"]).read_text())
    if any(closure[key] != cfg["retired_route"][other] for key, other in
           [("route_id", "id"), ("route_name", "name"), ("closure_date", "effective_date")]):
        raise ValueError("폐선 근거와 설정 불일치")
    for entry in closure["files"]:
        if sha256(CASE / entry["path"]) != entry["sha256"]:
            raise ValueError("공식 폐선 근거 원문 해시 변경")
    routes = reference["candidate_routes"]
    removed = cfg["retired_route"]["id"]
    if len(routes) != 14 or removed not in routes or cfg["retired_route"]["effective_date"] != "2024-08-24":
        raise ValueError("공식 이력으로 고정한 노선 범위 오류")
    history = pd.read_csv(CASE / cfg["history_routes"], dtype=str, keep_default_na=False)
    named = history[(history.target_route == removed) & history.match_status.eq("matched")]
    if set(named.route_name) != {cfg["retired_route"]["name"]}:
        raise ValueError("폐선 노선의 역사적 이름 대응 불일치")
    stations = pd.read_csv(CASE / "results/directional/station_registry.csv", dtype={"stop": str, "ars": str})
    mapping = stations.set_index("ars").stop.to_dict()
    legs = pd.DataFrame([{"segment": s["key"], "stop": mapping[s["from_ars"]], "arrival": mapping[s["to_ars"]]}
                         for s in shape["segments"]])
    stops = sorted(set(legs.stop) | set(legs.arrival))
    sources, wide = {}, {}
    source_dates = {kind: set() for kind in ["bus_time", "bus_trips"]}
    for kind in source_dates:
        pieces = []
        for scope in cfg["source_scopes"]:
            frame, audit = load_narrow(scope, kind, routes, stops, cfg["record_window"])
            pieces.append(frame)
            sources[kind + ":" + scope] = audit
            source_dates[kind].update(audit["source_available_dates"])
        wide[kind] = pd.concat(pieces, ignore_index=True)
    base = read_yaml("directional_config.yaml")
    base["hours"] = shape["hours"]
    time = wide["bus_time"].merge(legs, on=["stop", "arrival"], how="inner", validate="many_to_one")
    panel, repeated_time = make_time_panel(time, stations, base)
    panel = panel.merge(legs, on=["stop", "arrival"], validate="many_to_one")
    counts, repeated_counts = count_records(wide["bus_trips"], shape["hours"])
    days = pd.date_range(*cfg["record_window"]).strftime("%Y-%m-%d").tolist()
    grid = record_grid(panel, counts, routes, shape["hours"], days, legs, source_dates)
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    grid.to_parquet(RAW / "time_count_grid.parquet", index=False)
    monthly = monthly_states(grid)
    positive = grid[grid.record_status.eq("positive")]
    support = positive.groupby(["month", "route", "segment", "count_support"]).size().unstack(fill_value=0).reset_index()
    retired = grid[grid.route.eq(removed)]
    retired_daily = retirement_daily(retired)

    calendar = reference["calendar"]
    dates = sorted(set().union(*calendar.values(), *reference["selection_reference_dates"].values()))
    matrix, _ = joint_directions(panel, routes, shape["hours"], dates)
    baseline = pd.read_parquet(CASE / reference["baseline_path"]).set_index("route")
    baseline.columns = pd.MultiIndex.from_tuples([(c.split("_h")[0], int(c.split("_h")[1])) for c in baseline.columns],
                                                names=["segment", "hour"])
    baseline = baseline.reindex(columns=matrix.columns)
    normalized = matrix / baseline.reindex(matrix.index.get_level_values("route")).to_numpy() * 100
    original_daily = daily_paired(normalized, len(routes), dates, reference_cfg["report_hours"], reference_cfg["minimum_coverage"])
    saved_daily = pd.read_csv((CASE / cfg["reference_audit"]).parent / "daily.csv")
    pd.testing.assert_frame_equal(original_daily, saved_daily, check_exact=False, rtol=1e-10, atol=1e-10)
    kept = normalized[normalized.index.get_level_values("route") != removed]
    native = daily_paired(kept, len(routes) - 1, dates, reference_cfg["report_hours"], reference_cfg["minimum_coverage"])
    variants = {"original_14_reproduction": original_daily,
                "retained_13_same_accepted_dates": accepted_dates_only(native, original_daily),
                "retained_13_original_coverage_rule": native}
    if list(variants) != cfg["cohorts"]:
        raise ValueError("설정과 구현의 구성 비교 목록 불일치")
    comparisons, gaps, dailies, retention = [], [], [], []
    for label, daily in variants.items():
        number = 14 if label.startswith("original") else 13
        dailies.append(daily.assign(cohort=label))
        for period, period_dates in calendar.items():
            sub = daily[daily.date.isin(period_dates) & daily.segment.eq("south")]
            retention.append({"cohort": label, "period": period, "selected_routes": number,
                              "expected_days": len(period_dates), "accepted_days": int(sub["index"].notna().sum()),
                              "mean_coverage": sub.coverage.mean()})
        for name, (before, after) in shape["comparisons"].items():
            passed = []
            for segment in ["south", "north"]:
                result = describe_comparison(daily[daily.segment.eq(segment)], calendar[before], calendar[after], reference_cfg, interval=True)
                result["quality_pass"] = bool(result["quality_pass"] and number >= reference_cfg["minimum_routes"]
                    and min(result["before_coverage"], result["after_coverage"]) >= reference_cfg["minimum_coverage"])
                passed.append(result["quality_pass"])
                comparisons.append({"cohort": label, "comparison": name, "segment": segment, "selected_routes": number, **result})
            gaps.append({"cohort": label, "comparison": name, "selected_routes": number, "quality_pass": all(passed),
                         **paired_gap(daily, calendar[before], calendar[after], **reference_cfg["bootstrap"])})
    tables = {"monthly_record_states.csv": monthly, "positive_time_count_support.csv": support,
              "retired_route_daily.csv": retired_daily, "comparisons.csv": pd.DataFrame(comparisons),
              "paired_gaps.csv": pd.DataFrame(gaps), "daily.csv": pd.concat(dailies, ignore_index=True),
              "date_retention.csv": pd.DataFrame(retention)}
    for name, frame in tables.items():
        frame.to_csv(OUT / name, index=False)
    inputs = ["deepening_cohort_config.yaml", "gangnam/deepening_cohort.py", cfg["reference_audit"],
              cfg["reference_config"], cfg["history_audit"], cfg["history_routes"],
              cfg["closure_evidence"], "gangnam/overnight_matched_directions.py",
              "gangnam/overnight_bus.py", "gangnam/overnight_sensitivity.py", "gangnam/followup.py"]
    write_json(OUT / "audit.json", {"completed_at": utcnow(), "configuration": cfg,
        "inputs": {name: sha256(CASE / name) for name in inputs}, "source_audits": sources,
        "excluded_revisit_time_rows": repeated_time, "excluded_revisit_count_rows": repeated_counts,
        "original_daily_reproduction": "passed_rtol_atol_1e-10", "grid_rows": len(grid),
        "grid_path": str((RAW / "time_count_grid.parquet").relative_to(CASE)),
        "grid_sha256": sha256(RAW / "time_count_grid.parquet"),
        "outputs": {name: sha256(OUT / name) for name in tables}})
    print(f"공통 노선 구성 점검: 원래 14개 일별 수치 재현 통과, {len(comparisons)}개 비교와 시간·횟수 {len(grid):,}개 셀 기록", flush=True)


def retirement_daily(grid):
    rows = []
    for (date, segment), group in grid.groupby(["date", "segment"]):
        item = {"date": date, "segment": segment, "expected_hours": len(group)}
        for label, column in [("time", "record_status"), ("departure_trips", "departure_status"), ("arrival_trips", "arrival_status")]:
            item.update({f"{label}_{state}": int(group[column].eq(state).sum()) for state in STATES})
        rows.append(item)
    return pd.DataFrame(rows)
