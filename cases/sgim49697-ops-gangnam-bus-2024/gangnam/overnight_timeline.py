"""기존 고정 구간·노선의 32개월 주간 궤적과 단일 수준 분할을 기술적으로 요약한다."""

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
from .overnight_sensitivity import aggregate_daily

OUT = CASE / "results/overnight/timeline"
RAW = CASE / "data/overnight/timeline"


def expected_calendar(cfg):
    import holidays

    parent = read_yaml("overnight_persistence_config.yaml")
    periods(parent)  # 기존 2025년 5~8월 공식 공휴일 목록 대조를 실행한다.
    closed = holiday_set(read_yaml("directional_config.yaml")) | set(parent["holidays_2025_in_scope"]) | set(cfg["holiday_extension_dates"])
    start, end = cfg["range"]
    actual = {str(d) for d in holidays.KR(years=[2023, 2024, 2025]) if start <= str(d) <= end}
    if closed != actual:
        raise ValueError("장기 궤적의 공휴일 연장 목록과 패키지 결과가 다릅니다")
    return [str(d.date()) for d in pd.date_range(start, end) if d.dayofweek < 5 and str(d.date()) not in closed], sorted(closed)


def series_cells(selected, cfg):
    """구간 전체와 강조 두 구간의 모든 기존 노선을 별도 계열로 복제하며 새 셀을 고르지 않는다."""
    if selected.duplicated(CELL).any() or selected.baseline_2024.le(0).any() or selected.baseline_2024.isna().any():
        raise ValueError("장기 궤적 사전 셀 중복 또는 기준 평균 오류")
    chosen, metadata = [], []
    highlights = {(item["from_ars"], item["to_ars"]) for item in cfg["route_scope"]}
    observed_highlights = set()
    for segment, cells in selected.groupby("segment"):
        first = cells.iloc[0]
        scopes = [("segment", "all", cells)]
        if (first.from_ars, first.to_ars) in highlights:
            observed_highlights.add((first.from_ars, first.to_ars))
            scopes += [("route", route, rows) for route, rows in cells.groupby("route")]
        for scope, route, rows in scopes:
            series = segment if scope == "segment" else segment + "|route:" + str(route)
            chosen.append(rows.assign(series=series))
            metadata.append({"series": series, "scope": scope, "group": first.group, "segment": segment, "route": route,
                             "from_ars": first.from_ars, "to_ars": first.to_ars, "from_name": first.from_name,
                             "to_name": first.to_name, "selected_cells": len(rows), "selected_routes": rows.route.nunique()})
    if observed_highlights != highlights:
        raise ValueError("장기 궤적 강조 구간이 기존 선택에서 확인되지 않습니다")
    return pd.concat(chosen, ignore_index=True), pd.DataFrame(metadata)


def weekly_table(daily, cfg):
    """유효 일수와 예정 평일 분모를 모두 사용하고 짧은 공휴일 주를 자동 보간하지 않는다."""
    data = daily.copy()
    weeks = pd.to_datetime(data.date).dt.to_period("W-SUN")
    data["week_start"], data["week_end"] = weeks.dt.start_time.dt.strftime("%Y-%m-%d"), weeks.dt.end_time.dt.strftime("%Y-%m-%d")
    result = data.groupby(["aggregation", "group", "week_start", "week_end"]).agg(
        index=("index", "mean"), valid_days=("index", "count"), expected_days=("date", "size"),
        mean_cell_coverage=("coverage", "mean")).reset_index()
    result["day_coverage"] = result.valid_days / result.expected_days
    result["quality_pass"] = result.valid_days.ge(cfg["minimum_valid_days"]) & result.day_coverage.ge(cfg["minimum_expected_day_coverage"])
    result.loc[~result.quality_pass, "index"] = np.nan
    return result.rename(columns={"group": "series"})


def single_level_change(weekly, cfg):
    """두 상수 수준의 최소 제곱오차 분할. 추세·계절 보정이나 변화일 검정은 하지 않는다."""
    if weekly.week_start.duplicated().any():
        raise ValueError("한 계열에 주 시작일 중복")
    frame = weekly.sort_values("week_start").copy()
    if frame["index"].dropna().le(0).any() or np.isinf(frame["index"]).any():
        raise ValueError("주간 로그 지수는 유한 양수여야 합니다")
    observed = frame.dropna(subset=["index"])
    n, expected = len(observed), len(frame)
    fraction = n / expected if expected else 0.
    minimum = cfg["minimum_weeks_each_side"]
    passed = n >= minimum * 2 and fraction >= cfg["minimum_observed_week_fraction"]
    result = {"expected_weeks": expected, "observed_weeks": n, "observed_week_fraction": fraction,
              "quality_pass": bool(passed), "status": "insufficient" if not passed else "fitted",
              "candidate_splits": 0, "split_week": None, "last_pre_observed_week": None,
              "before_weeks": None, "after_weeks": None, "before_geometric_level": None, "after_geometric_level": None,
              "geometric_change_pct": None, "null_sse": None, "split_sse": None, "sse_reduction_fraction": None}
    if not passed:
        return result
    y = np.log(observed["index"].to_numpy(dtype=float))
    total_sse = float(np.square(y - y.mean()).sum())
    result["null_sse"] = total_sse
    if total_sse < 1e-12:
        result.update(status="constant", sse_reduction_fraction=0.)
        return result
    candidates = []
    for split in range(minimum, n - minimum + 1):
        left, right = y[:split], y[split:]
        error = float(np.square(left - left.mean()).sum() + np.square(right - right.mean()).sum())
        candidates.append((error, split))
    error, split = min(candidates, key=lambda item: (item[0], item[1]))
    before, after = float(np.exp(y[:split].mean())), float(np.exp(y[split:].mean()))
    result.update(candidate_splits=len(candidates), split_week=observed.iloc[split].week_start,
                  last_pre_observed_week=observed.iloc[split - 1].week_start,
                  before_weeks=split, after_weeks=n - split, before_geometric_level=before, after_geometric_level=after,
                  geometric_change_pct=100 * (after / before - 1), split_sse=error,
                  sse_reduction_fraction=max(0., 1 - error / total_sse))
    return result


def run():
    cfg = read_yaml("overnight_timeline_config.yaml")
    if cfg["locked_year"] != 2026 or cfg["range"] != ["2023-01-01", "2025-08-31"]:
        raise ValueError("장기 궤적의 고정 기간·잠금 오류")
    months = [str(m) for m in pd.period_range(cfg["range"][0][:7], cfg["range"][1][:7], freq="M")]
    test_months = allowed_months("test", read_yaml("overnight_forecast_config.yaml"))
    if any(month >= "2025-05" and month not in test_months for month in months):
        raise ValueError("장기 궤적의 시험 기간이 동결 범위 밖입니다")
    source = json.loads((CASE / cfg["selection_audit"]).read_text())
    path = CASE / cfg["selection"]
    if sha256(path) != source["outputs"][path.name]:
        raise ValueError("장기 궤적의 기존 선택 셀 해시 변경")
    selected = pd.read_csv(path, dtype={k: str for k in [*CELL[:-1], "from_ars", "to_ars"]})
    selected = selected[selected.band.eq(cfg["band"])].copy()
    chosen, metadata = series_cells(selected, cfg)
    registry = pd.read_csv(CASE / "results/directional/station_registry.csv", dtype={"stop": str, "ars": str})
    parts, audits = [], {}
    base = read_yaml("directional_config.yaml")
    base["hours"] = cfg["hours"]
    for scope, requested in [(cfg["sources"]["development_scope"], [m for m in months if m < "2025-05"]),
                              (cfg["sources"]["test_scope"], test_months)]:
        wide, audit = load_wide(scope, "bus_time", requested)
        panel, repeated = make_time_panel(wide, registry, base)
        parts.append(panel)
        audits[scope] = {**audit, "excluded_revisit_rows": repeated, "panel_rows": len(panel)}
        print(f"장기 궤적 입력: {scope}, {len(panel):,}행", flush=True)
    panel = pd.concat(parts, ignore_index=True)
    if panel.duplicated(["date", *CELL]).any():
        raise ValueError("장기 궤적 결합의 날짜·셀 중복")
    dates, closed = expected_calendar(cfg)
    merged = panel[panel.date.isin(dates)].merge(chosen[CELL + ["baseline_2024", "series"]], on=CELL, validate="many_to_many")
    if merged.duplicated(["date", "series", *CELL]).any():
        raise ValueError("한 계열에 같은 셀이 중복 반영됐습니다")
    merged["index"] = 100 * merged.value / merged.baseline_2024
    frames = []
    for method in cfg["aggregations"]:
        daily = aggregate_daily(merged.assign(group=merged.series), chosen.assign(group=chosen.series), dates,
                                method, cfg["minimum_daily_cell_coverage"])
        frames.append(daily.assign(aggregation=method))
    daily = pd.concat(frames, ignore_index=True)
    weekly = weekly_table(daily, cfg["weekly"])
    comparisons = []
    for (method, series), frame in weekly.groupby(["aggregation", "series"]):
        for name, (start, end) in cfg["single_level_change"]["ranges"].items():
            # 범위 경계에서 다른 연도의 날짜를 섞는 부분 주는 포함하지 않는다.
            chosen_weeks = frame[frame.week_start.ge(start) & frame.week_end.le(end)]
            result = single_level_change(chosen_weeks, cfg["single_level_change"])
            comparisons.append({"aggregation": method, "series": series, "range": name, **result,
                                "split_minus_policy_days": (pd.Timestamp(result["split_week"]) - pd.Timestamp(cfg["policy_reference_date"])).days
                                if result["split_week"] else None})
    comparisons = pd.DataFrame(comparisons).merge(metadata, on="series", validate="many_to_one")
    monthly = daily.assign(month=daily.date.str[:7]).groupby(["aggregation", "group", "month"]).agg(
        index=("index", "mean"), valid_days=("index", "count"), expected_days=("date", "size"),
        mean_cell_coverage=("coverage", "mean")).reset_index().rename(columns={"group": "series"})
    monthly["valid_day_fraction"] = monthly.valid_days / monthly.expected_days
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    tables = {"series.csv": metadata, "weekly.csv": weekly, "single_level_changes.csv": comparisons, "monthly.csv": monthly}
    for name, table in tables.items():
        table.to_csv(OUT / name, index=False)
    daily.to_parquet(RAW / "daily.parquet", index=False)
    inputs = [CASE / "overnight_timeline_config.yaml", path, CASE / cfg["selection_audit"],
              CASE / "results/directional/station_registry.csv", CASE / "overnight_persistence_config.yaml",
              CASE / "directional_config.yaml", CASE / "data_contract.yaml", CASE / "gangnam/overnight_bus.py",
              CASE / "gangnam/overnight_bus_extract.py", CASE / "gangnam/overnight_sensitivity.py",
              CASE / "gangnam/directional.py", CASE / "gangnam/overnight_persistence.py"]
    write_json(OUT / "audit.json", {"completed_at": utcnow(), "configuration": cfg, "code_sha256": sha256(Path(__file__)),
                                   "inputs": {str(p.relative_to(CASE)): sha256(p) for p in inputs}, "source_audits": audits,
                                   "calendar_dates": dates, "closed_dates": closed, "series": len(metadata),
                                   "source_scope_note": "확보한 원본을 재사용. 기존 역사적 ID 확인 범위를 넘어선 월의 물리 위치를 새로 입증한 것은 아님.",
                                   "daily_path": str((RAW / "daily.parquet").relative_to(CASE)), "daily_sha256": sha256(RAW / "daily.parquet"),
                                   "comparisons": len(comparisons), "quality_pass": int(comparisons.quality_pass.sum()),
                                   "statuses": comparisons.status.value_counts().to_dict(),
                                   "outputs": {name: sha256(OUT / name) for name in tables}, "interpretation": cfg["interpretation"]})
    print(f"장기 궤적: {len(metadata)}개 계열, {len(comparisons)}개 기술적 분할, 통과 {int(comparisons.quality_pass.sum())}개", flush=True)
