"""기존 사전 고정 셀의 2025년 관측 유지율과 방향별 시간 지수 지속성을 계산한다."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .directional import CELL, holiday_set
from .overnight_bus import candidate_routes, make_time_panel, read_panel
from .overnight_bus_extract import load_wide
from .overnight_forecast_data import allowed_months
from .overnight_sensitivity import aggregate_daily, describe_comparison

OUT = CASE / "results/overnight/persistence"
RAW = CASE / "data/overnight/persistence"


def periods(cfg):
    import holidays

    actual = {str(day) for day in holidays.KR(years=[2025]) if "2025-05-01" <= str(day) <= "2025-08-31"}
    if actual != set(cfg["holidays_2025_in_scope"]):
        raise ValueError("2025년 공식 대조 공휴일 목록과 패키지가 다릅니다")
    closed = holiday_set(read_yaml("directional_config.yaml")) | actual
    return {name: [str(day.date()) for day in pd.date_range(start, end)
                   if day.dayofweek < 5 and str(day.date()) not in closed]
            for name, (start, end) in cfg["periods"].items()}


def verify_identity(identity, stations, months):
    expected = pd.MultiIndex.from_product([months, stations.stop], names=["month", "stop"])
    chosen = identity[identity.month.isin(months) & identity.stop.isin(stations.stop)].copy()
    if chosen.duplicated(["month", "stop"]).any():
        raise ValueError("2025년 정류장 식별자 대조가 중복됩니다")
    chosen = chosen.set_index(["month", "stop"]).reindex(expected)
    required = ["id_observed", "id_ars_pair_observed", "all_observed_ars_agree"]
    if not chosen[required].eq(True).all().all():
        raise ValueError("2025년 중앙 정류장 ID·ARS 대조에 누락 또는 불일치가 있습니다")
    return len(chosen)


def pre_retention(panel, selected, before, minimum):
    """2025년 사전 양수 관측만 판정하며 원래 셀·2024년 기준 평균을 보존한다."""
    if selected.duplicated(CELL).any() or panel.duplicated(["date", *CELL]).any() or not before:
        raise ValueError("셀·날짜 중복 또는 빈 사전 기간")
    observed = panel[panel.date.isin(before)].groupby(CELL).value.agg(["count", "mean"])
    audit = selected.merge(observed, on=CELL, how="left", validate="one_to_one")
    audit["pre2025_positive_count"] = audit["count"].fillna(0).astype(int)
    audit["pre2025_coverage"] = audit.pre2025_positive_count / len(before)
    audit["pre2025_eligible"] = audit.pre2025_coverage.ge(minimum) & audit["mean"].gt(0)
    return audit.drop(columns=["count", "mean"])


def record_states(panel, selected, calendar, source_dates):
    chosen = panel.merge(selected[CELL], on=CELL, validate="many_to_one")
    rows = []
    for name, dates in calendar.items():
        missing_dates = set(dates) - set(source_dates)
        for group, cells in selected.groupby("group"):
            data = chosen[chosen.group.eq(group) & chosen.date.isin(dates)]
            if data.date.isin(missing_dates).any():
                raise ValueError("원본 날짜 감사와 셀 관측 날짜가 모순됩니다")
            states = data.record_status.value_counts()
            expected = len(cells) * len(dates)
            missing_source = len(cells) * len(missing_dates)
            missing_row = expected - missing_source - len(data)
            if missing_row < 0 or int(states.sum()) != len(data):
                raise ValueError("셀 관측 상태의 분모 또는 행 수가 맞지 않습니다")
            rows.append({"period": name, "group": group, "selected_cells": len(cells),
                         "expected_days": len(dates), "expected_cell_days": expected,
                         "source_missing": missing_source, "row_absent": missing_row,
                         **{status: int(states.get(status, 0)) for status in ["positive", "zero", "blank", "negative"]}})
    return pd.DataFrame(rows)


def run():
    cfg = read_yaml("overnight_persistence_config.yaml")
    if cfg["locked_year"] != 2026 or any(month >= "2026-01" for month in cfg["months"]):
        raise ValueError("잠금 연도 또는 분석 월 설정 오류")
    if set(cfg["months"]) != set(allowed_months("test", read_yaml("overnight_forecast_config.yaml"))):
        raise ValueError("기존 시험 버스의 검증된 범위 밖입니다")
    calendar = periods(cfg)
    selection_path = CASE / cfg["selection_path"]
    selection_audit = json.loads((selection_path.parent / "sensitivity_audit.json").read_text())
    if sha256(selection_path) != selection_audit["outputs"][selection_path.name]:
        raise ValueError("기존 사전 선택 셀 해시 불일치")
    registry = CASE / "results/directional/station_registry.csv"
    stations = pd.read_csv(registry, dtype={"stop": str, "ars": str})
    identity_path = CASE / "results/overnight/cards/station_identity.csv"
    identity_audit = json.loads((identity_path.parent / "analysis_audit.json").read_text())
    if sha256(identity_path) != identity_audit["outputs"][identity_path.name]:
        raise ValueError("정류장 역사 식별자 결과 해시 불일치")
    identity = pd.read_csv(identity_path, dtype={"month": str, "stop": str})
    identity_count = verify_identity(identity, stations[stations.group.isin(cfg["groups"])], cfg["months"])
    old, old_audit = read_panel()
    old = old[old.date.str[:4].eq("2024") & old.group.isin(cfg["groups"])].copy()
    wide, new_audit = load_wide(cfg["source_scope"], cfg["kind"], cfg["months"])
    base = read_yaml("directional_config.yaml")
    base["hours"] = sorted({hour for band in cfg["bands"].values() for hour in band})
    new, repeats = make_time_panel(wide, stations, base)
    new = new[new.group.isin(cfg["groups"])].copy()
    panel = pd.concat([old, new], ignore_index=True)
    if panel.duplicated(["date", *CELL]).any():
        raise ValueError("연장 패널의 날짜·셀 중복")
    selected = pd.read_csv(selection_path, dtype={key: str for key in CELL if key != "hour"})
    selected = selected[selected.cohort.eq(cfg["selection_cohort"]) & selected.group.isin(cfg["groups"])].copy()
    route_groups = candidate_routes().set_index("route").policy_group
    selected["policy_group"] = selected.route.map(route_groups).fillna("other_or_unclassified")
    selected = selected.drop(columns="cohort")
    dates = sorted({date for period in calendar.values() for date in period})
    source_dates = set(old_audit["source_available_dates"]) | set(new_audit["source_available_dates"])
    settings = {**cfg, "bootstrap": {"draws": cfg["bootstrap_repetitions"], "seed": cfg["bootstrap_seed"]}}
    rows, retention, selections, states, dailies = [], [], [], [], []
    for band, hours in cfg["bands"].items():
        original = selected[selected.band.eq(band)].copy()
        part = panel[panel.hour.isin(hours)]
        qualified = pre_retention(part, original, calendar["pre2025"], cfg["minimum_coverage"])
        retention.append(qualified)
        for cohort in cfg["cohorts"]:
            chosen = qualified if cohort == "frozen_pre2023_pre2024" else qualified[qualified.pre2025_eligible]
            for subset in cfg["subsets"]:
                cells = chosen if subset == "all_preselected" else chosen[chosen.policy_group.eq(subset)]
                tags = {"band": band, "cohort": cohort, "subset": subset}
                selections.append(cells.assign(**tags))
                states.append(record_states(part, cells, calendar, source_dates).assign(**tags))
                normalized = part.merge(cells[CELL + ["baseline_2024"]], on=CELL, validate="many_to_one")
                normalized["index"] = 100 * normalized.value / normalized.baseline_2024
                if np.isinf(normalized["index"]).any():
                    raise ValueError("고정 기준 정규화에 무한대가 있습니다")
                for method in cfg["aggregations"]:
                    daily = aggregate_daily(normalized, cells, dates, method, cfg["minimum_coverage"])
                    dailies.append(daily.assign(**tags, aggregation=method))
                    for group in cfg["groups"]:
                        group_data = daily[daily.group.eq(group)]
                        chosen_group = cells[cells.group.eq(group)]
                        original_group = original[original.group.eq(group)]
                        if subset != "all_preselected":
                            original_group = original_group[original_group.policy_group.eq(subset)]
                        for name, (before, after) in cfg["comparisons"].items():
                            rows.append({**tags, "aggregation": method, "group": group, "comparison": name,
                                         "selected_cells": len(chosen_group), "original_cells": len(original_group),
                                         "selected_routes": chosen_group.route.nunique(),
                                         "retained_fraction": len(chosen_group) / len(original_group) if len(original_group) else np.nan,
                                         **describe_comparison(group_data, calendar[before], calendar[after], settings,
                                                               interval=method == "equal_cells")})
        print(f"2025년 고정 셀 연장: {band}", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    daily = pd.concat(dailies, ignore_index=True)
    cache = RAW / "daily_all.parquet"
    daily.to_parquet(cache, index=False)
    outputs = {"comparisons.csv": pd.DataFrame(rows), "pre2025_retention.csv": pd.concat(retention, ignore_index=True),
               "selected_cells.csv": pd.concat(selections, ignore_index=True), "record_states.csv": pd.concat(states, ignore_index=True),
               "daily_equal_cells.csv": daily[daily.aggregation.eq("equal_cells")]}
    for name, frame in outputs.items():
        frame.to_csv(OUT / name, index=False)
    inputs = [selection_path, selection_path.parent / "sensitivity_audit.json", identity_path, registry,
              CASE / f"results/overnight/{cfg['source_scope']}/extraction_audit.json",
              CASE / "gangnam/overnight_bus.py", CASE / "gangnam/overnight_bus_extract.py",
              CASE / "gangnam/overnight_sensitivity.py", CASE / "gangnam/directional.py"]
    write_json(OUT / "audit.json", {"completed_at": utcnow(), "configuration": cfg, "calendar": calendar,
                                    "code_sha256": sha256(Path(__file__)), "historical_id_pairs_verified": identity_count,
                                    "original_panel_sha256": old_audit["panel_sha256"], "new_input_audit": new_audit,
                                    "excluded_new_revisit_rows": repeats,
                                    "inputs": {str(path.relative_to(CASE)): sha256(path) for path in inputs},
                                    "daily_all_path": str(cache.relative_to(CASE)), "daily_all_sha256": sha256(cache),
                                    "comparisons": len(rows), "quality_pass": int(outputs["comparisons.csv"].quality_pass.sum()),
                                    "outputs": {name: sha256(OUT / name) for name in outputs}})
