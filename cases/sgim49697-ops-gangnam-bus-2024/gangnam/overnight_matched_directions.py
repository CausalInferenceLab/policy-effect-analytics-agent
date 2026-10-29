"""같은 노선·날짜의 양방향 공동 관측으로 강조 구간의 구성 민감도를 비교한다."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .overnight_bus import make_time_panel
from .overnight_bus_extract import load_wide
from .overnight_forecast_data import allowed_months
from .overnight_hour_shape import select_routes
from .overnight_sensitivity import describe_comparison

OUT = CASE / "results/overnight/matched_directions"
RAW = CASE / "data/overnight/matched_directions"
CONFIG = "overnight_matched_directions_config.yaml"


def joint_directions(rows, routes, hours, dates):
    """두 방향의 모든 시간 중 하나라도 없으면 양쪽 노선·날짜를 같이 제외한다."""
    if rows.duplicated(["date", "route", "segment", "hour"]).any():
        raise ValueError("양방향 공동 관측 키 중복")
    if not routes or not dates or not hours or len(set(hours)) != len(hours):
        raise ValueError("양방향 후보 격자가 비었거나 시간이 중복됩니다")
    if not set(rows.segment).issubset({"south", "north"}):
        raise ValueError("양방향 이외 구간")
    grid = pd.MultiIndex.from_product([dates, routes], names=["date", "route"])
    columns = pd.MultiIndex.from_product([["south", "north"], hours], names=["segment", "hour"])
    matrix = rows.pivot(index=["date", "route"], columns=["segment", "hour"], values="value")
    matrix = matrix.reindex(index=grid, columns=columns)
    matrix = matrix.where(np.isfinite(matrix) & matrix.gt(0))
    joint = matrix.notna().all(axis=1)
    return matrix.where(joint, axis=0), joint


def daily_paired(normalized, expected_routes, dates, report_hours, minimum):
    """사후 누락 노선도 고정 분모에 남기며 두 방향에 동일한 노선·날짜를 적용한다."""
    rows = []
    for segment in ["south", "north"]:
        values = normalized[segment][report_hours].mean(axis=1)
        grouped = values.groupby(level="date").agg(["mean", "count"]).reindex(dates)
        coverage = grouped["count"].fillna(0) / expected_routes if expected_routes else pd.Series(0., index=dates)
        rows.append(pd.DataFrame({"date": dates, "segment": segment,
            "index": grouped["mean"].where(coverage.ge(minimum)).to_numpy(),
            "coverage": coverage.to_numpy(), "unit_coverage": coverage.to_numpy()}))
    result = pd.concat(rows, ignore_index=True)
    shared = result.pivot(index="date", columns="segment", values="coverage")
    if not shared.south.equals(shared.north):
        raise ValueError("양방향의 공동 표본 분모가 다릅니다")
    return result


def paired_gap(daily, before, after, draws, seed):
    """동일 달력 주를 양쪽에 함께 재표집해 방향별 변화율 차이의 기술적 범위를 구한다."""
    wide = daily.pivot(index="date", columns="segment", values="index")[["south", "north"]].dropna()
    parts = [wide.loc[wide.index.isin(days)] for days in [before, after]]
    counts = {"before_days": len(parts[0]), "after_days": len(parts[1])}
    if any(part.empty or not np.isfinite(part).all().all() or part.le(0).any().any() for part in parts):
        return {**counts, "gap_percentage_points": np.nan, "week_bootstrap_low": np.nan, "week_bootstrap_high": np.nan}
    rng = np.random.default_rng(seed)
    samples = []
    for label, part in zip(["before", "after"], parts, strict=True):
        week = pd.to_datetime(part.index).to_period("W-SUN")
        grouped = part.groupby(week)
        sums, sizes = grouped.sum().to_numpy(), grouped.size().to_numpy()
        counts[label + "_weeks"] = len(sizes)
        selected = rng.integers(0, len(sizes), size=(draws, len(sizes)))
        samples.append(sums[selected].sum(axis=1) / sizes[selected].sum(axis=1)[:, None])
    change = 100 * (parts[1].mean().to_numpy() / parts[0].mean().to_numpy() - 1)
    sample_change = 100 * (samples[1] / samples[0] - 1)
    low, high = np.quantile(sample_change[:, 1] - sample_change[:, 0], [.025, .975])
    return {**counts, "gap_percentage_points": change[1] - change[0],
            "week_bootstrap_low": float(low), "week_bootstrap_high": float(high)}


def run():
    cfg = read_yaml(CONFIG)
    base = read_yaml(cfg["base_config"])
    if cfg["locked_year"] != 2026 or base["locked_year"] != 2026:
        raise ValueError("양방향 공동 표본의 잠금 연도 오류")
    audit_path, eligibility_path = CASE / cfg["candidate_audit"], CASE / cfg["candidate_eligibility"]
    audit = json.loads(audit_path.read_text())
    if sha256(eligibility_path) != audit["outputs"][eligibility_path.name]:
        raise ValueError("공동 노선의 사전 선택표 변경")
    for name, expected in audit["inputs"].items():
        if sha256(CASE / name) != expected:
            raise ValueError(f"시간대 분석의 기존 입력 변경: {name}")
    eligibility = pd.read_csv(eligibility_path, dtype={"route": str})
    candidates = sorted(set(eligibility.loc[eligibility.segment.eq("south") & eligibility.eligible, "route"])
                        & set(eligibility.loc[eligibility.segment.eq("north") & eligibility.eligible, "route"]))
    if candidates != cfg["expected_common_routes"]:
        raise ValueError("결과 계산 전에 고정한 공통 노선 후보와 다릅니다")
    calendar, reference = audit["calendar"], audit["selection_reference_dates"]
    dates = sorted(set().union(*calendar.values(), *reference.values()))
    if any(day.startswith("2026") for day in dates):
        raise ValueError("공동 방향의 잠금 날짜 오류")
    months = sorted({day[:7] for day in dates})
    registry_path = CASE / "results/directional/station_registry.csv"
    registry = pd.read_csv(registry_path, dtype={"stop": str, "ars": str})
    legs = []
    for spec in base["segments"]:
        endpoints = [registry[registry.ars.eq(spec[key])] for key in ["from_ars", "to_ars"]]
        if any(len(part) != 1 for part in endpoints):
            raise ValueError("공동 방향의 정류장 대응 오류")
        origin, destination = [part.iloc[0] for part in endpoints]
        if origin.group != destination.group or destination.order - origin.order != 1:
            raise ValueError("같은 방향 인접 정류장이 아닙니다")
        legs.append({"segment": spec["key"], "stop": origin.stop, "arrival": destination.stop})
    legs = pd.DataFrame(legs)
    test_months = allowed_months("test", read_yaml("overnight_forecast_config.yaml"))
    time_cfg = read_yaml("directional_config.yaml")
    time_cfg["hours"] = base["hours"]
    panels, sources = [], {}
    for scope in base["source_scopes"]:
        requested = [month for month in months if (month in test_months) == (scope == "forecast_bus_test")]
        wide, source = load_wide(scope, "bus_time", requested)
        wide = wide[wide.route.isin(candidates)].merge(legs[["stop", "arrival"]], on=["stop", "arrival"], validate="many_to_one")
        panel, repeated = make_time_panel(wide, registry, time_cfg)
        panels.append(panel.merge(legs, on=["stop", "arrival"], validate="many_to_one"))
        sources[scope] = {**source, "excluded_revisit_rows": repeated}
    matrix, joint = joint_directions(pd.concat(panels, ignore_index=True), candidates, base["hours"], dates)
    support, baseline, normalized = select_routes(matrix, joint, reference, cfg["minimum_pre_joint_coverage"])
    number = int(support.eligible.sum())
    daily = daily_paired(normalized, number, dates, cfg["report_hours"], cfg["minimum_coverage"])
    comparisons, gaps, states = [], [], []
    for name, (before, after) in base["comparisons"].items():
        quality = []
        for segment in ["south", "north"]:
            result = describe_comparison(daily[daily.segment.eq(segment)], calendar[before], calendar[after], cfg, interval=True)
            result["quality_pass"] = bool(result["quality_pass"] and number >= cfg["minimum_routes"]
                and min(result["before_coverage"], result["after_coverage"]) >= cfg["minimum_coverage"])
            quality.append(result["quality_pass"])
            comparisons.append({"comparison": name, "segment": segment, "selected_routes": number, **result})
        gap = paired_gap(daily, calendar[before], calendar[after], **cfg["bootstrap"])
        gaps.append({"comparison": name, "selected_routes": number, "quality_pass": all(quality), **gap})
    selected = joint.index.get_level_values("route").isin(support.loc[support.eligible, "route"])
    for name, days in calendar.items():
        values = joint[selected & joint.index.get_level_values("date").isin(days)]
        states.append({"period": name, "expected_route_days": len(days) * number,
                       "joint_positive_route_days": int(values.sum()), "excluded_route_days": int((~values).sum())})
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    tables = {"comparisons": pd.DataFrame(comparisons), "paired_gaps": pd.DataFrame(gaps), "daily": daily,
              "eligibility": support, "joint_states": pd.DataFrame(states)}
    for name, frame in tables.items():
        frame.to_csv(OUT / f"{name}.csv", index=False)
    baseline = baseline.copy()
    baseline.columns = [f"{segment}_h{hour:02d}" for segment, hour in baseline.columns]
    baseline_path = RAW / "baseline.parquet"
    baseline.reset_index().to_parquet(baseline_path, index=False)
    write_json(OUT / "audit.json", {"completed_at": utcnow(), "configuration": cfg, "calendar": calendar,
        "selection_reference_dates": reference, "candidate_routes": candidates, "selected_routes": number,
        "source_audits": sources, "inputs": {str(path.relative_to(CASE)): sha256(path) for path in
            [CASE / CONFIG, CASE / cfg["base_config"], eligibility_path, audit_path, registry_path, Path(__file__),
             CASE / "gangnam/overnight_hour_shape.py", CASE / "gangnam/overnight_sensitivity.py"]},
        "baseline_path": str(baseline_path.relative_to(CASE)), "baseline_sha256": sha256(baseline_path),
        "outputs": {name + ".csv": sha256(OUT / (name + ".csv")) for name in tables}})
    print(f"같은 노선 양방향 공동 표본: 후보 {len(candidates)}개 → 사전 통과 {number}개", flush=True)
