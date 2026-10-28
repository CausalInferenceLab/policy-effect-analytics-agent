"""고정 셀의 방향별 지속성을 인접 구간으로 분해하고 단일 구간·노선의 구성 영향을 점검한다."""

import json
from pathlib import Path

import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .directional import CELL
from .overnight_bus import make_time_panel, read_panel
from .overnight_bus_extract import load_wide
from .overnight_sensitivity import aggregate_daily, describe_comparison

OUT = CASE / "results/overnight/persistence_segments"
RAW = CASE / "data/overnight/persistence_segments"


def adjacent_cells(selected, registry):
    if registry.stop.duplicated().any():
        raise ValueError("정류장 레지스트리 ID 중복")
    info = registry.set_index("stop")
    result = selected.copy()
    for endpoint, prefix in [("stop", "from"), ("arrival", "to")]:
        for field in ["group", "order", "ars", "name"]:
            result[f"{prefix}_{field}"] = result[endpoint].map(info[field])
    if result[["from_group", "to_group", "from_order", "to_order"]].isna().any().any():
        raise ValueError("고정 셀에 레지스트리 미확인 정류장이 있습니다")
    mask = result.from_group.eq(result.group) & result.to_group.eq(result.group) & result.to_order.eq(result.from_order + 1)
    result["segment"] = result.group + "|" + result.stop + "|" + result.arrival
    return result[mask].copy(), result[~mask].copy()


def remove_unit(cells, normalized, unit, identifier):
    if unit not in {"route", "segment"} or identifier not in set(cells[unit]):
        raise ValueError("사전 선택에 없는 제외 단위")
    return cells[cells[unit].ne(identifier)].copy(), normalized[normalized[unit].ne(identifier)].copy()


def load_inputs(cfg):
    parent = read_yaml(cfg["parent_config"])
    source = CASE / "results/overnight/persistence"
    audit = json.loads((source / "audit.json").read_text())
    if cfg["locked_year"] != 2026 or audit["configuration"] != parent or any(not m.startswith("2025-") for m in parent["months"]):
        raise ValueError("연장 분석의 설정·잠금 범위가 변경되었습니다")
    for path, expected in audit["inputs"].items():
        if sha256(CASE / path) != expected:
            raise ValueError(f"연장 분석 입력 변경: {path}")
    chosen = source / "pre2025_retention.csv"
    if sha256(chosen) != audit["outputs"][chosen.name]:
        raise ValueError("기존 고정 셀 결과 해시 불일치")
    selected = pd.read_csv(chosen, dtype={key: str for key in CELL if key != "hour"})
    selected = selected[selected.policy_group.eq(cfg["subset"])].copy()
    registry = pd.read_csv(CASE / "results/directional/station_registry.csv", dtype={"stop": str, "ars": str})
    old, old_audit = read_panel()
    if old_audit["panel_sha256"] != audit["original_panel_sha256"]:
        raise ValueError("기존 시간 패널 해시가 연장 분석과 다릅니다")
    wide, new_audit = load_wide(parent["source_scope"], parent["kind"], parent["months"])
    if new_audit["inputs"] != audit["new_input_audit"]["inputs"]:
        raise ValueError("2025년 캐시 구성이 연장 분석과 다릅니다")
    base = read_yaml("directional_config.yaml")
    base["hours"] = sorted({h for hours in parent["bands"].values() for h in hours})
    new, repeats = make_time_panel(wide, registry, base)
    panel = pd.concat([old[old.date.str.startswith("2024")], new], ignore_index=True)
    if panel.duplicated(["date", *CELL]).any():
        raise ValueError("구간 연장 패널의 날짜·셀 중복")
    return parent, audit, selected, registry, panel, repeats


def influence(normalized, selected, dates, calendar, cfg):
    rows = []
    for group, cells in selected.groupby("group"):
        data = normalized[normalized.group.eq(group)]
        removals = [("none", "full")]
        removals += [(unit, identifier) for unit in cfg["leave_one_out"]["units"] for identifier in sorted(cells[unit].unique())]
        for unit, identifier in removals:
            remaining, values = (cells, data) if unit == "none" else remove_unit(cells, data, unit, identifier)
            daily = aggregate_daily(values, remaining, dates, "equal_cells", cfg["minimum_coverage"])
            for name, (before, after) in cfg["comparisons"].items():
                result = describe_comparison(daily, calendar[before], calendar[after], cfg)
                support = remaining.route.nunique() >= cfg["leave_one_out"]["minimum_remaining_routes"]
                rows.append({"group": group, "comparison": name, "omitted_unit": unit, "omitted_id": identifier,
                             "original_cells": len(cells), "remaining_cells": len(remaining),
                             "remaining_routes": remaining.route.nunique(), "index_quality_pass": result["quality_pass"],
                             **result, "quality_pass": bool(support and result["quality_pass"])})
    return pd.DataFrame(rows)


def run():
    cfg = read_yaml("overnight_persistence_segments_config.yaml")
    parent, parent_audit, selected, registry, panel, repeats = load_inputs(cfg)
    calendar = parent_audit["calendar"]
    dates = sorted({day for days in calendar.values() for day in days})
    rows, dailies, all_chosen, excluded, influence_rows = [], [], [], [], []
    for band in cfg["bands"]:
        cells, skipped = adjacent_cells(selected[selected.band.eq(band)], registry)
        all_chosen.append(cells)
        excluded.append(skipped)
        part = panel[panel.hour.isin(parent["bands"][band])]
        normalized = part.merge(cells[CELL + ["baseline_2024", "segment"]], on=CELL, validate="many_to_one")
        normalized["index"] = 100 * normalized.value / normalized.baseline_2024
        daily = aggregate_daily(normalized.assign(group=normalized.segment), cells.assign(group=cells.segment),
                                dates, cfg["aggregation"], cfg["minimum_coverage"])
        dailies.append(daily.assign(band=band))
        for segment, segment_cells in cells.groupby("segment"):
            first = segment_cells.iloc[0]
            meta = {"band": band, "segment": segment, "group": first.group, "stop": first.stop, "arrival": first.arrival,
                    "from_ars": first.from_ars, "to_ars": first.to_ars, "from_order": int(first.from_order),
                    "from_name": first.from_name, "to_name": first.to_name, "selected_cells": len(segment_cells),
                    "selected_routes": segment_cells.route.nunique()}
            daily_segment = daily[daily.group.eq(segment)]
            for name, (before, after) in cfg["comparisons"].items():
                result = describe_comparison(daily_segment, calendar[before], calendar[after], cfg, interval=band == "evening")
                rows.append({**meta, "comparison": name, "index_quality_pass": result["quality_pass"], **result,
                             "quality_pass": bool(result["quality_pass"] and meta["selected_routes"] >= cfg["minimum_segment_routes"])})
        if band == cfg["leave_one_out"]["band"]:
            influence_rows.append(influence(normalized, cells, dates, calendar, cfg).assign(band=band))
        print(f"인접 구간 지속성: {band}, {cells.segment.nunique()}개 구간", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    outputs = {"segment_comparisons.csv": pd.DataFrame(rows), "daily_segments.csv": pd.concat(dailies, ignore_index=True),
               "selected_cells.csv": pd.concat(all_chosen, ignore_index=True), "excluded_nonadjacent.csv": pd.concat(excluded, ignore_index=True),
               "leave_one_out.csv": pd.concat(influence_rows, ignore_index=True)}
    for name, frame in outputs.items():
        frame.to_csv(OUT / name, index=False)
    inputs = [CASE / "results/overnight/persistence/audit.json", CASE / "results/overnight/persistence/pre2025_retention.csv",
              CASE / "results/directional/station_registry.csv", CASE / "gangnam/overnight_sensitivity.py",
              CASE / "gangnam/overnight_bus.py", CASE / "gangnam/overnight_bus_extract.py", CASE / "gangnam/directional.py"]
    write_json(OUT / "audit.json", {"completed_at": utcnow(), "configuration": cfg, "code_sha256": sha256(Path(__file__)),
                "inputs": {str(path.relative_to(CASE)): sha256(path) for path in inputs},
                "excluded_new_revisit_rows": repeats, "segment_comparisons": len(rows),
                "segment_quality_pass": int(outputs["segment_comparisons.csv"].quality_pass.sum()),
                "leave_one_out_comparisons": len(outputs["leave_one_out.csv"]),
                "leave_one_out_quality_pass": int(outputs["leave_one_out.csv"].quality_pass.sum()),
                "outputs": {name: sha256(OUT / name) for name in outputs}})
