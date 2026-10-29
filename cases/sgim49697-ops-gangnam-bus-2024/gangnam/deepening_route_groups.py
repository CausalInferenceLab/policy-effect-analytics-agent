"""공식 정류소 안내로 나눈 고정 노선에서 기존 방향별 변화의 구성 민감도를 확인한다."""

import json

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .deepening_infrastructure import CONFIG, MANIFEST, OUT, verify
from .overnight_matched_directions import daily_paired, joint_directions
from .overnight_sensitivity import describe_comparison


def common_dates(daily):
    """모든 안내군에서 관측률을 통과한 같은 날짜만 남긴다."""
    sets = [set(part.loc[part["index"].notna(), "date"]) for _, part in daily[daily.segment.eq("south")].groupby("group")]
    if not sets:
        raise ValueError("공통 날짜를 정할 노선 그룹이 없습니다")
    return set.intersection(*sets)


def group_gap(daily, before, after, draws, seed):
    """같은 달력 주를 두 그룹에 함께 적용한 변화율 차이의 기술 구간이다."""
    labels = ["announced_central", "announced_curb"]
    wide = daily.pivot(index="date", columns="group", values="index")[labels].dropna()
    parts = [wide.loc[wide.index.isin(days)] for days in [before, after]]
    if any(part.empty or not np.isfinite(part).all().all() or part.le(0).any().any() for part in parts):
        raise ValueError("안내군 대비의 유효 날짜·양수 지수 부족")
    rng = np.random.default_rng(seed)
    estimates, metadata = [], {}
    for name, part in zip(["before", "after"], parts, strict=True):
        weeks = pd.to_datetime(part.index).to_period("W-SUN")
        grouped = part.groupby(weeks)
        sums, sizes = grouped.sum().to_numpy(), grouped.size().to_numpy()
        sampled = rng.integers(0, len(sizes), size=(draws, len(sizes)))
        estimates.append(sums[sampled].sum(axis=1) / sizes[sampled].sum(axis=1)[:, None])
        metadata[name + "_days"], metadata[name + "_weeks"] = len(part), len(sizes)
    observed = 100 * (parts[1].mean().to_numpy() / parts[0].mean().to_numpy() - 1)
    sampled = 100 * (estimates[1] / estimates[0] - 1)
    low, high = np.quantile(sampled[:, 0] - sampled[:, 1], [.025, .975])
    return dict(**metadata, central_minus_curb_percentage_points=observed[0] - observed[1],
                week_bootstrap_low=float(low), week_bootstrap_high=float(high))


def run():
    cfg, frozen = verify()
    parent_cfg = read_yaml(cfg["reference_config"])
    shape = read_yaml(parent_cfg["base_config"])
    cohort = json.loads((CASE / cfg["cohort_audit"]).read_text())
    original = json.loads((CASE / cohort["configuration"]["reference_audit"]).read_text())
    grid_path = CASE / frozen["grid_path"]
    if sha256(grid_path) != frozen["grid_sha256"] or not grid_path.resolve().is_relative_to((CASE / "data/deepening/cohort").resolve()):
        raise ValueError("공동 관측 격자의 경로·해시 변경")
    grid = pd.read_parquet(grid_path, columns=["date", "route", "segment", "hour", "raw_value", "record_status"])
    if grid.date.str[:4].astype(int).ge(cfg["locked_year"]).any():
        raise ValueError("노선 그룹 분석에 잠금 연도 발견")
    grid["value"] = grid.raw_value.where(grid.record_status.eq("positive"))
    calendar = original["calendar"]
    dates = sorted(set().union(*calendar.values(), *original["selection_reference_dates"].values()))
    matrix, _ = joint_directions(grid, frozen["retained_routes"], shape["hours"], dates)
    baseline = pd.read_parquet(CASE / original["baseline_path"]).set_index("route")
    baseline.columns = pd.MultiIndex.from_tuples([(col.split("_h")[0], int(col.split("_h")[1])) for col in baseline.columns], names=["segment", "hour"])
    denominator = baseline.reindex(matrix.index.get_level_values("route"), columns=matrix.columns).to_numpy()
    if not np.isfinite(denominator).all() or (denominator <= 0).any():
        raise ValueError("동결한 노선별 사전 기준값이 유효하지 않습니다")
    normalized = matrix / denominator * 100
    all_daily = daily_paired(normalized, 13, dates, parent_cfg["report_hours"], parent_cfg["minimum_coverage"])
    old_daily_path = CASE / "results/deepening/cohort/daily.csv"
    if sha256(old_daily_path) != cohort["outputs"]["daily.csv"]:
        raise ValueError("기존 13개 노선 일별 결과 변경")
    old_daily = pd.read_csv(old_daily_path)
    old_daily = old_daily[old_daily.cohort.eq("retained_13_original_coverage_rule")].drop(columns="cohort").reset_index(drop=True)
    pd.testing.assert_frame_equal(all_daily, old_daily, check_exact=False, rtol=1e-10, atol=1e-10)
    membership = pd.read_csv(OUT / "route_groups.csv", dtype=str)
    selected = {group: part.route.tolist() for group, part in membership.groupby("group")}
    native = []
    for group, routes in selected.items():
        part = normalized.loc[normalized.index.get_level_values("route").isin(routes)]
        daily = daily_paired(part, len(routes), dates, parent_cfg["report_hours"], parent_cfg["minimum_coverage"])
        native.append(daily.assign(group=group, selected_routes=len(routes)))
    native = pd.concat(native, ignore_index=True)
    shared = common_dates(native)
    native = pd.concat([native, all_daily.assign(group="reference_all13", selected_routes=13)], ignore_index=True)
    common = native.copy()
    common["index"] = common["index"].where(common.date.isin(shared))
    daily = pd.concat([native.assign(date_rule="native_group_coverage"), common.assign(date_rule="common_partition_dates")], ignore_index=True)
    comparisons, retention = [], []
    for (rule, group, segment), part in daily.groupby(["date_rule", "group", "segment"]):
        number = int(part.selected_routes.iloc[0])
        for period, days in calendar.items():
            subset = part[part.date.isin(days)]
            retention.append(dict(date_rule=rule, group=group, segment=segment, period=period, selected_routes=number,
                                  expected_days=len(days), accepted_days=int(subset["index"].notna().sum()), mean_coverage=float(subset.coverage.mean())))
        for comparison, (before, after) in shape["comparisons"].items():
            result = describe_comparison(part, calendar[before], calendar[after], parent_cfg, interval=True)
            result["quality_pass"] = bool(result["quality_pass"] and number >= cfg["minimum_routes_for_interpretation"]
                and min(result["before_coverage"], result["after_coverage"]) >= parent_cfg["minimum_coverage"])
            comparisons.append(dict(date_rule=rule, group=group, segment=segment, comparison=comparison, selected_routes=number,
                                    minimum_routes_pass=number >= cfg["minimum_routes_for_interpretation"], **result))
    comparisons = pd.DataFrame(comparisons)
    contrasts = []
    for segment in ["south", "north"]:
        sub = daily[daily.date_rule.eq("common_partition_dates") & daily.segment.eq(segment)
                    & daily.group.isin(["announced_central", "announced_curb"])]
        for comparison, (before, after) in shape["comparisons"].items():
            check = comparisons[comparisons.date_rule.eq("common_partition_dates") & comparisons.segment.eq(segment)
                & comparisons.comparison.eq(comparison) & comparisons.group.isin(["announced_central", "announced_curb"])]
            contrasts.append(dict(segment=segment, comparison=comparison, quality_pass=len(check) == 2 and bool(check.quality_pass.all()),
                                  **group_gap(sub, calendar[before], calendar[after], **parent_cfg["bootstrap"])))
    outputs = {"group_daily.csv": daily, "group_comparisons.csv": comparisons,
               "group_contrasts.csv": pd.DataFrame(contrasts), "group_date_retention.csv": pd.DataFrame(retention)}
    for name, table in outputs.items():
        table.to_csv(OUT / name, index=False, lineterminator="\n")
    write_json(OUT / "group_audit.json", dict(completed_at=utcnow(), code_sha256=sha256(__file__),
        configuration_sha256=sha256(CASE / CONFIG), manifest_sha256=sha256(MANIFEST),
        grid_sha256=frozen["grid_sha256"], input_grid_rows=len(grid), original_13_daily_rows_reproduced=len(all_daily),
        comparisons=len(comparisons), quality_pass=int(comparisons.quality_pass.sum()), contrasts=len(contrasts),
        outputs={name: sha256(OUT / name) for name in outputs},
        scope="공지에 근거한 구성 민감도; 실제 경로 노출·무처리 대조군·인과 이중차분 아님"))
    print(f"노선 안내군 {len(comparisons)}개 비교·{len(contrasts)}개 같은 날짜 대비, 기존 13개 일별 {len(all_daily)}행 재현", flush=True)
