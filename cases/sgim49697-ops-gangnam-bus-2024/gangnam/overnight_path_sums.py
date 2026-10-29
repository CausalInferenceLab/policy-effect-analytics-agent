"""같은 노선·시간의 인접 구간 평균 합과 각 구간을 동일 공동 표본에서 비교한다."""

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

OUT = CASE / "results/overnight/path_sums"
RAW = CASE / "data/overnight/path_sums"


def path_legs(spec, registry):
    wanted = registry[registry.ars.isin(spec["ars"])]
    if wanted.ars.duplicated().any() or len(wanted) != len(spec["ars"]):
        raise ValueError("경로의 ARS를 유일한 정류장으로 연결할 수 없습니다")
    ordered = wanted.set_index("ars").reindex(spec["ars"])
    if ordered.group.nunique() != 1 or not ordered.order.diff().iloc[1:].eq(1).all():
        raise ValueError("경로가 같은 방향의 인접 정류장 순서가 아닙니다")
    return pd.DataFrame([{"leg": i, "stop": ordered.iloc[i].stop, "arrival": ordered.iloc[i + 1].stop,
                          "from_ars": spec["ars"][i], "to_ars": spec["ars"][i + 1]}
                         for i in range(len(ordered) - 1)])


def joint_matrix(panel, candidates, legs, dates):
    """한 구간이라도 관측되지 않으면 전체 경로와 모든 성분의 그 셀·날짜를 함께 결측으로 둔다."""
    rows = panel.merge(legs[["stop", "arrival", "leg"]], on=["stop", "arrival"], validate="many_to_one")
    rows = rows.merge(candidates[["route", "hour"]], on=["route", "hour"], validate="many_to_one")
    if rows.duplicated(["date", "route", "hour", "leg"]).any():
        raise ValueError("경로의 날짜·노선·시간·구간 중복")
    grid = pd.DataFrame({"date": dates}).merge(candidates[["route", "hour"]], how="cross").set_index(["date", "route", "hour"]).index
    matrix = rows.pivot(index=["date", "route", "hour"], columns="leg", values="value").reindex(index=grid, columns=legs.leg)
    matrix = matrix.where(np.isfinite(matrix) & matrix.gt(0))
    joint = matrix.notna().all(axis=1)
    matrix = matrix.where(joint, axis=0)
    matrix.columns = [f"leg_{i}" for i in legs.leg]
    matrix["sum"] = matrix.sum(axis=1, min_count=len(legs))
    return matrix, joint


def choose_and_normalize(matrix, joint, reference, minimum):
    """사전 공동 관측만으로 선택하고 원시 구간 합을 먼저 만든 후 자기 기준 평균으로 나눈다."""
    support = pd.DataFrame(index=matrix.index.droplevel("date").unique())
    for name, dates in reference.items():
        sample = joint[joint.index.get_level_values("date").isin(dates)]
        if not dates or sample.empty:
            raise ValueError("경로의 사전 공동 관측 분모가 비었습니다")
        support[f"{name}_coverage"] = sample.groupby(level=["route", "hour"]).mean()
    support["eligible"] = support.ge(minimum).all(axis=1)
    selected_keys = support.index[support.eligible]
    values = matrix[matrix.index.droplevel("date").isin(selected_keys)]
    before = values[values.index.get_level_values("date").isin(reference["pre2024"])]
    baseline = before.groupby(level=["route", "hour"]).mean()
    if baseline.isna().any().any() or baseline.le(0).any().any():
        raise ValueError("경로의 공동 사전 기준 평균 오류")
    aligned = baseline.reindex(values.index.droplevel("date")).to_numpy()
    normalized = values / aligned * 100
    return support.reset_index(), baseline.reset_index(), normalized


def daily_indices(normalized, expected_cells, dates, minimum):
    results = []
    for metric in normalized.columns:
        table = normalized[metric].groupby(level="date").agg(["mean", "count"]).reindex(dates)
        coverage = table["count"].fillna(0) / expected_cells if expected_cells else pd.Series(0., index=dates)
        values = table["mean"].where(coverage.ge(minimum))
        results.append(pd.DataFrame({"date": dates, "metric": metric, "index": values.to_numpy(),
                                     "coverage": coverage.to_numpy(), "unit_coverage": coverage.to_numpy()}))
    return pd.concat(results, ignore_index=True)


def sequence_audit(wide, legs, routes, calendar):
    """수치 결과와 별개로 같은 고정 경로 노선의 순서 키 집합과 관측 날짜 수를 남긴다."""
    records = wide[wide.route.isin(routes)].merge(legs, on=["stop", "arrival"], validate="many_to_one")
    results = []
    for name, dates in calendar.items():
        part = records[records.date.isin(dates)].copy()
        part["gap"] = pd.to_numeric(part.arrival_sequence, errors="raise") - pd.to_numeric(part.sequence, errors="raise")
        part["pair"] = part.sequence.astype(str) + "→" + part.arrival_sequence.astype(str)
        for route in routes:
            for leg in legs.itertuples():
                rows = part[part.route.eq(route) & part.leg.eq(leg.leg)]
                pairs = sorted(rows.pair.unique())
                results.append({"period": name, "route": route, "leg": leg.leg, "from_ars": leg.from_ars,
                                "to_ars": leg.to_ars, "expected_days": len(dates), "observed_days": rows.date.nunique(),
                                "sequence_pairs": " | ".join(pairs), "pair_count": len(pairs),
                                "nonconsecutive_rows": int(rows.gap.ne(1).sum())})
    return pd.DataFrame(results)


def run():
    cfg = read_yaml("overnight_path_sums_config.yaml")
    if cfg["locked_year"] != 2026:
        raise ValueError("경로 합의 잠금 연도 오류")
    audit_path, chosen_path = CASE / cfg["selection_audit"], CASE / cfg["selection"]
    selection_audit = json.loads(audit_path.read_text())
    if sha256(chosen_path) != selection_audit["outputs"][chosen_path.name]:
        raise ValueError("경로 합의 사전 선택 셀 해시 변경")
    selected = pd.read_csv(chosen_path, dtype={key: str for key in CELL if key != "hour"})
    selected = selected[selected.band.eq(cfg["band"])].copy()
    if selected.duplicated(CELL).any():
        raise ValueError("경로 합의 기존 사전 선택 셀 중복")
    registry = pd.read_csv(CASE / "results/directional/station_registry.csv", dtype={"stop": str, "ars": str})
    parent = read_yaml("overnight_persistence_config.yaml")
    calendar = periods(parent)
    closed = holiday_set(read_yaml("directional_config.yaml"))
    selection_calendar = {name: [str(day.date()) for day in pd.date_range(*bounds)
                                 if day.dayofweek < 5 and str(day.date()) not in closed]
                          for name, bounds in cfg["selection_periods"].items()}
    old_audit_path = CASE / "results/overnight/bus/panel_audit.json"
    old = json.loads(old_audit_path.read_text())
    if sha256(CASE / old["panel_path"]) != old["panel_sha256"]:
        raise ValueError("경로 선택에 사용하는 원래 버스 패널 해시 변경")
    reference = {name: [day for day in dates if day in old["source_available_dates"]] for name, dates in selection_calendar.items()}
    all_dates = sorted(set().union(*calendar.values(), *selection_calendar.values()))
    months = sorted({day[:7] for day in all_dates})
    test_months = allowed_months("test", read_yaml("overnight_forecast_config.yaml"))
    base = read_yaml("directional_config.yaml")
    base["hours"] = cfg["hours"]
    panels, metadatas, sources = [], [], {}
    for scope in cfg["source_scopes"]:
        requested = [month for month in months if (month in test_months) == (scope == "forecast_bus_test")]
        wide, source = load_wide(scope, "bus_time", requested)
        repeated = wide.duplicated(["date", "route", "stop", "arrival"], keep=False)
        metadatas.append(wide.loc[~repeated, ["date", "route", "stop", "arrival", "sequence", "arrival_sequence"]])
        panel, revisit = make_time_panel(wide, registry, base)
        panels.append(panel)
        sources[scope] = {**source, "excluded_revisit_rows": revisit}
    panel = pd.concat(panels, ignore_index=True)
    metadata = pd.concat(metadatas, ignore_index=True)
    if panel.duplicated(["date", *CELL]).any() or metadata.duplicated(["date", "route", "stop", "arrival"]).any():
        raise ValueError("경로 합의 입력 결합 중복")
    comparisons, dailies, eligibility, sequences, states, baselines, specifications = [], [], [], [], [], [], []
    for spec in cfg["paths"]:
        legs = path_legs(spec, registry)
        prior = selected.merge(legs[["stop", "arrival", "leg"]], on=["stop", "arrival"], validate="many_to_one")
        counts = prior.groupby(["route", "hour"]).leg.nunique()
        candidates = counts[counts.eq(len(legs))].reset_index()[["route", "hour"]]
        if candidates.empty:
            raise ValueError(f"기존 모든 구간을 공유하는 사전 셀이 없습니다: {spec['key']}")
        matrix, joint = joint_matrix(panel[panel.date.isin(all_dates)], candidates, legs, all_dates)
        support, baseline, normalized = choose_and_normalize(matrix, joint, reference, cfg["minimum_pre_joint_coverage"])
        chosen = support[support.eligible]
        daily = daily_indices(normalized, len(chosen), all_dates, cfg["minimum_coverage"])
        routes = sorted(chosen.route.unique())
        for metric, frame in daily.groupby("metric"):
            for name, (before, after) in cfg["comparisons"].items():
                row = describe_comparison(frame, calendar[before], calendar[after], cfg, interval=True)
                row["quality_pass"] = bool(row["quality_pass"] and len(routes) >= cfg["minimum_routes"]
                                           and min(row["before_coverage"], row["after_coverage"]) >= cfg["minimum_coverage"])
                comparisons.append({"path": spec["key"], "metric": metric, "comparison": name,
                                    "selected_cells": len(chosen), "selected_routes": len(routes), **row})
        for name, dates in calendar.items():
            valid = normalized[normalized.index.get_level_values("date").isin(dates)]["sum"]
            states.append({"path": spec["key"], "period": name, "expected_cell_days": len(chosen) * len(dates),
                           "joint_positive": int(valid.notna().sum()), "any_leg_invalid": int(valid.isna().sum())})
        dailies.append(daily.assign(path=spec["key"]))
        eligibility.append(support.assign(path=spec["key"]))
        baselines.append(baseline.assign(path=spec["key"]))
        sequences.append(sequence_audit(metadata, legs, routes, calendar).assign(path=spec["key"]))
        specifications.append(legs.assign(path=spec["key"]))
        print(f"경로 합: {spec['key']}, 기존 교집합 {len(candidates)}셀 → 공동 사전 {len(chosen)}셀, {len(routes)}노선", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    tables = {"comparisons.csv": pd.DataFrame(comparisons), "daily.csv": pd.concat(dailies, ignore_index=True),
              "eligibility.csv": pd.concat(eligibility, ignore_index=True), "sequence_pairs.csv": pd.concat(sequences, ignore_index=True),
              "record_states.csv": pd.DataFrame(states), "path_legs.csv": pd.concat(specifications, ignore_index=True)}
    for name, frame in tables.items():
        frame.to_csv(OUT / name, index=False)
    pd.concat(baselines, ignore_index=True).to_parquet(RAW / "baselines.parquet", index=False)
    inputs = [CASE / "overnight_path_sums_config.yaml", audit_path, chosen_path, old_audit_path,
              CASE / "results/directional/station_registry.csv", CASE / "overnight_persistence_config.yaml",
              CASE / "directional_config.yaml", CASE / "data_contract.yaml", CASE / "gangnam/overnight_bus.py",
              CASE / "gangnam/overnight_bus_extract.py", CASE / "gangnam/overnight_sensitivity.py", CASE / "gangnam/directional.py"]
    write_json(OUT / "audit.json", {"completed_at": utcnow(), "configuration": cfg, "code_sha256": sha256(Path(__file__)),
                                   "inputs": {str(p.relative_to(CASE)): sha256(p) for p in inputs}, "source_audits": sources,
                                   "calendar": calendar, "selection_reference": reference,
                                   "comparisons": len(comparisons), "quality_pass": int(tables["comparisons.csv"].quality_pass.sum()),
                                   "baselines_sha256": sha256(RAW / "baselines.parquet"),
                                   "outputs": {name: sha256(OUT / name) for name in tables}, "interpretation": cfg["interpretation"]})
    print(f"경로 합 비교: {len(comparisons)}개, 통과 {int(tables['comparisons.csv'].quality_pass.sum())}개", flush=True)
