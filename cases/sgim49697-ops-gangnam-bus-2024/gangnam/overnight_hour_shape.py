"""강조 구간의 전 시간대 공동 노선 표본으로 시간대별 변화 모양을 비교한다."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .directional import CELL, holiday_set
from .overnight_bus import make_time_panel
from .overnight_bus_extract import load_wide
from .overnight_forecast_data import allowed_months
from .overnight_persistence import periods
from .overnight_sensitivity import describe_comparison

OUT = CASE / "results/overnight/hour_shape"
RAW = CASE / "data/overnight/hour_shape"


def joint_hours(rows, routes, hours, dates):
    """한 시간이라도 양수 기록이 없으면 해당 노선·날짜의 전체 시간을 함께 제외한다."""
    if rows.duplicated(["date", "route", "hour"]).any():
        raise ValueError("노선·날짜·시간 중복")
    if len(set(hours)) != len(hours) or not routes or not dates:
        raise ValueError("시간 중복 또는 비어 있는 후보 격자")
    grid = pd.MultiIndex.from_product([dates, routes], names=["date", "route"])
    matrix = rows.pivot(index=["date", "route"], columns="hour", values="value").reindex(index=grid, columns=hours)
    matrix = matrix.where(np.isfinite(matrix) & matrix.gt(0))
    joint = matrix.notna().all(axis=1)
    return matrix.where(joint, axis=0), joint


def select_routes(matrix, joint, reference, minimum):
    """사전 공동 관측으로만 노선을 선택하고 각 시간의 사전 평균으로 기준화한다."""
    support = pd.DataFrame(index=matrix.index.get_level_values("route").unique())
    for name, dates in reference.items():
        if not dates:
            raise ValueError("공동 시간의 사전 선택 분모가 비었습니다")
        sample = joint[joint.index.get_level_values("date").isin(dates)]
        support[f"{name}_coverage"] = sample.groupby(level="route").mean()
    support["eligible"] = support.ge(minimum).all(axis=1)
    values = matrix[matrix.index.get_level_values("route").isin(support.index[support.eligible])]
    before = values[values.index.get_level_values("date").isin(reference["pre2024"])]
    baseline = before.groupby(level="route").mean()
    if baseline.isna().any().any() or baseline.le(0).any().any():
        raise ValueError("공동 시간 사전 기준값 오류")
    normalized = values / baseline.reindex(values.index.get_level_values("route")).to_numpy() * 100
    return support.reset_index(), baseline, normalized


def daily_profile(normalized, expected_routes, dates, minimum):
    rows = []
    for hour in normalized.columns:
        grouped = normalized[hour].groupby(level="date").agg(["mean", "count"]).reindex(dates)
        coverage = grouped["count"].fillna(0) / expected_routes if expected_routes else pd.Series(0., index=dates)
        rows.append(pd.DataFrame({"date": dates, "hour": hour,
                                 "index": grouped["mean"].where(coverage.ge(minimum)).to_numpy(),
                                 "coverage": coverage.to_numpy(), "unit_coverage": coverage.to_numpy()}))
    return pd.concat(rows, ignore_index=True)


def run():
    cfg = read_yaml("overnight_hour_shape_config.yaml")
    if cfg["locked_year"] != 2026:
        raise ValueError("시간 모양 분석의 잠금 연도 오류")
    chosen_path, audit_path = CASE / cfg["selection"], CASE / cfg["selection_audit"]
    audit = json.loads(audit_path.read_text())
    if sha256(chosen_path) != audit["outputs"][chosen_path.name]:
        raise ValueError("기존 사전 선택 셀 변경")
    selected = pd.read_csv(chosen_path, dtype={key: str for key in CELL if key != "hour"})
    selected = selected[selected.band.eq("evening")]
    registry = pd.read_csv(CASE / "results/directional/station_registry.csv", dtype={"stop": str, "ars": str})
    calendar = periods(read_yaml("overnight_persistence_config.yaml"))
    closed = holiday_set(read_yaml("directional_config.yaml"))
    selection_calendar = {key: [str(day.date()) for day in pd.date_range(*bounds)
                               if day.dayofweek < 5 and str(day.date()) not in closed]
                          for key, bounds in cfg["selection_periods"].items()}
    old_path = CASE / "results/overnight/bus/panel_audit.json"
    old = json.loads(old_path.read_text())
    if sha256(CASE / old["panel_path"]) != old["panel_sha256"]:
        raise ValueError("기존 사전 원본 날짜를 정한 시간 패널 변경")
    reference = {key: [day for day in days if day in old["source_available_dates"]]
                 for key, days in selection_calendar.items()}
    dates = sorted(set().union(*calendar.values(), *selection_calendar.values()))
    months = sorted({day[:7] for day in dates})
    test_months = allowed_months("test", read_yaml("overnight_forecast_config.yaml"))
    segments = []
    for spec in cfg["segments"]:
        endpoints = []
        for name in ["from_ars", "to_ars"]:
            matched = registry[registry.ars.eq(spec[name])]
            if len(matched) != 1:
                raise ValueError("시간 모양 구간의 정류장 대응 오류")
            endpoints.append(matched.iloc[0])
        if endpoints[0].group != endpoints[1].group or endpoints[1].order - endpoints[0].order != 1:
            raise ValueError("시간 모양의 같은 방향 인접 구간 조건 오류")
        segments.append({**spec, "stop": endpoints[0].stop, "arrival": endpoints[1].stop})
    legs = pd.DataFrame(segments)
    panels, sources = [], {}
    base = read_yaml("directional_config.yaml")
    base["hours"] = cfg["hours"]
    for scope in cfg["source_scopes"]:
        requested = [month for month in months if (month in test_months) == (scope == "forecast_bus_test")]
        wide, source = load_wide(scope, "bus_time", requested)
        wide = wide.merge(legs[["stop", "arrival"]], on=["stop", "arrival"], validate="many_to_one")
        panel, repeated = make_time_panel(wide, registry, base)
        panels.append(panel)
        sources[scope] = {**source, "excluded_revisit_rows": repeated}
    panel = pd.concat(panels, ignore_index=True)
    if panel.duplicated(["date", *CELL]).any():
        raise ValueError("시간 모양 입력의 중복")
    results, dailies, supports, baselines, states = [], [], [], [], []
    for spec in segments:
        cells = selected[selected.stop.eq(spec["stop"]) & selected.arrival.eq(spec["arrival"])]
        routes = sorted(cells.route.unique())
        rows = panel[panel.stop.eq(spec["stop"]) & panel.arrival.eq(spec["arrival"]) & panel.route.isin(routes)]
        matrix, joint = joint_hours(rows, routes, cfg["hours"], dates)
        support, baseline, normalized = select_routes(matrix, joint, reference, cfg["minimum_pre_joint_coverage"])
        number = int(support.eligible.sum())
        daily = daily_profile(normalized, number, dates, cfg["minimum_coverage"])
        for hour, frame in daily.groupby("hour"):
            for name, (before, after) in cfg["comparisons"].items():
                result = describe_comparison(frame, calendar[before], calendar[after], cfg, interval=True)
                result["quality_pass"] = bool(result["quality_pass"] and number >= cfg["minimum_routes"]
                                              and min(result["before_coverage"], result["after_coverage"]) >= cfg["minimum_coverage"])
                results.append({"segment": spec["key"], "from_ars": spec["from_ars"], "to_ars": spec["to_ars"],
                                "hour": hour, "comparison": name, "candidate_routes": len(routes),
                                "selected_routes": number, **result})
        for name, days in calendar.items():
            mask = joint.index.get_level_values("date").isin(days)
            chosen = joint.index.get_level_values("route").isin(support.loc[support.eligible, "route"])
            states.append({"segment": spec["key"], "period": name, "expected_route_days": len(days) * number,
                           "joint_positive_route_days": int(joint[mask & chosen].sum()),
                           "excluded_route_days": int((~joint[mask & chosen]).sum())})
        supports.append(support.assign(segment=spec["key"]))
        baselines.append(baseline.reset_index().assign(segment=spec["key"]))
        dailies.append(daily.assign(segment=spec["key"]))
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    tables = {"comparisons": pd.DataFrame(results), "daily": pd.concat(dailies, ignore_index=True),
              "eligibility": pd.concat(supports, ignore_index=True), "joint_states": pd.DataFrame(states)}
    for name, frame in tables.items():
        frame.to_csv(OUT / f"{name}.csv", index=False)
    baseline_path = RAW / "baseline.parquet"
    pd.concat(baselines, ignore_index=True).rename(columns=str).to_parquet(baseline_path, index=False)
    write_json(OUT / "audit.json", {"completed_at": utcnow(), "configuration": cfg, "calendar": calendar,
        "selection_reference_dates": reference, "source_audits": sources,
        "inputs": {str(path.relative_to(CASE)): sha256(path) for path in [chosen_path, audit_path, old_path,
            CASE / "overnight_hour_shape_config.yaml", CASE / "overnight_persistence_config.yaml", Path(__file__)]},
        "baseline_path": str(baseline_path.relative_to(CASE)), "baseline_sha256": sha256(baseline_path),
        "comparisons": len(tables["comparisons"]), "quality_pass": int(tables["comparisons"].quality_pass.sum()),
        "outputs": {f"{name}.csv": sha256(OUT / f"{name}.csv") for name in tables}})
    print(f"동일 노선 시간 모양: {len(results)}개 비교, {int(tables['comparisons'].quality_pass.sum())}개 통과", flush=True)
