"""노선 안내군의 공동 관측·정규화·같은 주 대비를 별도 긴 표 계산으로 검증한다."""

import json
import math
from datetime import date, timedelta
from statistics import mean

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .deepening_infrastructure import MANIFEST, OUT, verify


def route_day_values(rows, baselines, hours, report_hours):
    expected = {(segment, hour) for segment in ["south", "north"] for hour in hours}
    actual = {(row.segment, row.hour) for row in rows}
    if len(rows) != len(expected) or actual != expected:
        raise ValueError("공동 관측 검증의 32개 키 누락·중복")
    if any(row.record_status != "positive" or not math.isfinite(row.raw_value) or row.raw_value <= 0 for row in rows):
        return None
    return {segment: mean(row.raw_value / baselines[(row.route, row.segment, row.hour)] * 100
                          for row in rows if row.segment == segment and row.hour in report_hours)
            for segment in ["south", "north"]}


def independent_gap(before, after, draws, seed):
    """날짜 문자열에서 월요일을 계산해 동일 주 재표집의 가중 평균을 직접 만든다."""
    rng = np.random.default_rng(seed)
    sampled = []
    observed = []
    for records in [before, after]:
        grouped = {}
        for day, values in sorted(records.items()):
            parsed = date.fromisoformat(day)
            monday = (parsed - timedelta(days=parsed.weekday())).isoformat()
            grouped.setdefault(monday, []).append(values)
        weeks = [np.array(values, dtype=float) for _, values in sorted(grouped.items())]
        means = np.array([part.mean(axis=0) for part in weeks])
        weights = np.array([len(part) for part in weeks])
        picks = rng.integers(0, len(weeks), size=(draws, len(weeks)))
        sampled.append(np.array([np.average(means[index], weights=weights[index], axis=0) for index in picks]))
        observed.append(np.array(list(records.values())).mean(axis=0))
    changes = 100 * (sampled[1] / sampled[0] - 1)
    difference = 100 * (observed[1] / observed[0] - 1)
    lower, upper = np.quantile(changes[:, 0] - changes[:, 1], [.025, .975])
    return difference[0] - difference[1], lower, upper


def run():
    cfg, frozen = verify()
    audit = json.loads((OUT / "group_audit.json").read_text())
    for name, expected in audit["outputs"].items():
        if sha256(OUT / name) != expected:
            raise ValueError("안내군 독립 검증의 집계 입력 변경")
    if sha256(CASE / frozen["grid_path"]) != frozen["grid_sha256"]:
        raise ValueError("공동 관측 격자 해시 변경")
    parent = read_yaml(cfg["reference_config"])
    shape = read_yaml(parent["base_config"])
    cohort = json.loads((CASE / cfg["cohort_audit"]).read_text())
    original = json.loads((CASE / cohort["configuration"]["reference_audit"]).read_text())
    dates = sorted(set().union(*original["calendar"].values(), *original["selection_reference_dates"].values()))
    baselines = {}
    for row in pd.read_parquet(CASE / original["baseline_path"]).to_dict("records"):
        for column, value in row.items():
            if column != "route":
                segment, hour = column.split("_h")
                baselines[(row["route"], segment, int(hour))] = value
    grid = pd.read_parquet(CASE / frozen["grid_path"])
    grid = grid[grid.date.isin(dates) & grid.route.isin(frozen["retained_routes"])]
    normalized = {}
    for (day, route), rows in grid.groupby(["date", "route"]):
        values = route_day_values(list(rows.itertuples()), baselines, shape["hours"], parent["report_hours"])
        if values is not None:
            normalized[(day, route)] = values
    membership = pd.read_csv(OUT / "route_groups.csv", dtype=str)
    routes = {group: part.route.tolist() for group, part in membership.groupby("group")}
    routes["reference_all13"] = frozen["retained_routes"]
    native, complete = {}, {group: set() for group in routes}
    for group, selected in routes.items():
        for day in dates:
            observed = [normalized[(day, route)] for route in selected if (day, route) in normalized]
            coverage = len(observed) / len(selected)
            if coverage >= parent["minimum_coverage"]:
                complete[group].add(day)
            for segment in ["south", "north"]:
                index = mean(value[segment] for value in observed) if coverage >= parent["minimum_coverage"] else float("nan")
                native[(group, day, segment)] = (index, coverage)
    shared = set.intersection(*(days for group, days in complete.items() if group != "reference_all13"))
    daily = pd.read_csv(OUT / "group_daily.csv")
    maximum, scalar_checks = 0., 0

    def equal(actual, expected):
        nonlocal maximum, scalar_checks
        scalar_checks += 1
        if math.isnan(actual) and math.isnan(expected):
            return
        if not math.isfinite(actual) or not math.isfinite(expected) or abs(actual - expected) > 1e-10:
            raise ValueError(f"독립 안내군 수치 불일치: {actual} / {expected}")
        maximum = max(maximum, abs(actual - expected))

    for row in daily.itertuples(index=False):
        expected, coverage = native[(row.group, row.date, row.segment)]
        if row.date_rule == "common_partition_dates" and row.date not in shared:
            expected = float("nan")
        equal(row.index, expected)
        equal(row.coverage, coverage)
    comparisons = pd.read_csv(OUT / "group_comparisons.csv")
    for row in comparisons.itertuples(index=False):
        periods = shape["comparisons"][row.comparison]
        means = []
        for period in periods:
            values = [native[(row.group, day, row.segment)][0] for day in original["calendar"][period]
                      if row.date_rule == "native_group_coverage" or day in shared]
            means.append(mean(value for value in values if math.isfinite(value)))
        for actual, expected in zip([row.before_mean, row.after_mean, row.change_pct], [*means, 100 * (means[1] / means[0] - 1)], strict=True):
            equal(actual, expected)
    contrasts = pd.read_csv(OUT / "group_contrasts.csv")
    for row in contrasts.itertuples(index=False):
        parts = []
        for period in shape["comparisons"][row.comparison]:
            parts.append({day: [native[(group, day, row.segment)][0] for group in ["announced_central", "announced_curb"]]
                          for day in original["calendar"][period] if day in shared})
        result = independent_gap(*parts, **parent["bootstrap"])
        for actual, expected in zip([row.central_minus_curb_percentage_points, row.week_bootstrap_low, row.week_bootstrap_high], result, strict=True):
            equal(actual, expected)
    write_json(OUT / "group_validation.json", dict(completed_at=utcnow(), code_sha256=sha256(__file__),
        manifest_sha256=sha256(MANIFEST), audit_sha256=sha256(OUT / "group_audit.json"),
        daily_rows=len(daily), comparison_rows=len(comparisons), contrast_rows=len(contrasts),
        numeric_checks=scalar_checks, maximum_absolute_difference=maximum, mismatches=0,
        scope="독립 긴 표의 공동 관측·노선별 기준값·집단 평균 및 주별 대비; 기존 집계 함수 호출 없음"))
    print(f"노선 안내군 {scalar_checks:,}개 일별/평균/대비 수치 독립 대조 일치", flush=True)
