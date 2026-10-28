"""기존 공통 운영 셀의 구간별 시간·운행·승차·기록 비율을 같은 기준으로 연장한다."""

import json
from pathlib import Path

import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .directional import CELL
from .overnight_bus import load_wide, make_time_panel, read_panel
from .overnight_bus_extract import load_wide as load_new_wide
from .overnight_mechanism import METRICS, count_panel, joint_grid
from .overnight_operations_persistence import daily_ratio, normalize_fixed
from .overnight_persistence import periods
from .overnight_sensitivity import aggregate_daily, describe_comparison

OUT = CASE / "results/overnight/segment_operations"


def attach_segments(selected, time_only):
    """선택 공통 셀이 원래 시간 전용 인접 셀의 부분집합인지 검증하고 구간 표식을 붙인다."""
    if selected.duplicated(CELL).any() or time_only.duplicated(CELL).any():
        raise ValueError("운영·시간 전용 사전 셀의 키 중복")
    fields = ["segment", "from_ars", "to_ars", "from_order", "from_name", "to_name"]
    result = selected.merge(time_only[CELL + fields], on=CELL, how="left", validate="one_to_one", indicator=True)
    if not result._merge.eq("both").all():
        raise ValueError("운영 셀이 원래 시간 전용 인접 표본에 포함되지 않습니다")
    return result.drop(columns="_merge")


def load_observations(cfg, source, calendar):
    dates = sorted({d for values in calendar.values() for d in values})
    stations = pd.read_csv(CASE / "results/directional/station_registry.csv", dtype={"stop": str})
    stops = set(stations[stations.group.isin(source["groups"])].stop)
    base = read_yaml("directional_config.yaml")
    base["hours"] = read_yaml(source["calendar_from"])["bands"][cfg["band"]]
    old, old_audit = read_panel()
    new, new_audit = load_new_wide(source["time_and_trips_scope"], "bus_time", source["months"])
    new, repeated = make_time_panel(new, stations, base)
    panel = pd.concat([old[old.date.str.startswith("2024")], new], ignore_index=True)
    panel = panel[panel.date.isin(dates) & panel.hour.isin(base["hours"])]
    counts, audits = {}, {"time_old": old_audit, "time_new": new_audit, "time_excluded_revisit_rows": repeated}
    for kind, metric in [("bus_trips", "trips"), ("bus_boardings", "boardings")]:
        old, old_audit = load_wide(kind, base)
        scope = source["time_and_trips_scope"] if metric == "trips" else source["source_scope"]
        new, new_audit = load_new_wide(scope, kind, source["months"])
        wide = pd.concat([old[old.date.str.startswith("2024")], new], ignore_index=True)
        wide = wide[wide.date.isin(dates)]
        counts[metric], repeated = count_panel(wide, base["hours"], metric, stops)
        audits[metric] = {"old": old_audit, "new": new_audit, "excluded_revisit_rows": repeated}
    return panel, counts, audits, dates


def run():
    cfg = read_yaml("overnight_segment_operations_config.yaml")
    source = read_yaml(cfg["source_config"])
    if cfg["locked_year"] != 2026 or source["locked_year"] != 2026 or cfg["band"] != "evening":
        raise ValueError("구간 운영 분석의 잠금 연도·시간대 오류")
    selected_path, time_path = CASE / cfg["selection"], CASE / cfg["time_only_selection"]
    source_audit, time_audit = [json.loads((CASE / cfg[key]).read_text()) for key in ["source_audit", "time_only_audit"]]
    for path, audit in [(selected_path, source_audit), (time_path, time_audit)]:
        if sha256(path) != audit["outputs"][path.name]:
            raise ValueError("구간 운영 사전 선택 해시 불일치")
    if sha256(CASE / cfg["source_config"]) != source_audit["inputs"][cfg["source_config"]]:
        raise ValueError("원래 운영 지속성 규칙이 변경됐습니다")
    for path in ["results/directional/station_registry.csv", "results/overnight/persistence/audit.json"]:
        if sha256(CASE / path) != source_audit["inputs"][path]:
            raise ValueError("원래 정류장 대응·2025년 정체성 검증이 변경됐습니다")
    calendar = periods(read_yaml(source["calendar_from"]))
    dtype = {k: str for k in CELL if k != "hour"}
    selected = pd.read_csv(selected_path, dtype=dtype)
    time_only = pd.read_csv(time_path, dtype={**dtype, "from_ars": str, "to_ars": str})
    selected = selected[selected.band.eq(cfg["band"])]
    time_only = time_only[time_only.band.eq(cfg["band"])]
    if time_only.segment.nunique() != 14:
        raise ValueError("시간 전용 14개 구간 범위가 다릅니다")
    panel, counts, audits, dates = load_observations(cfg, source, calendar)
    rows, dailies, eligibility, states = [], [], [], []
    for endpoint in cfg["endpoint_alignments"]:
        cells = attach_segments(selected[selected.endpoint.eq(endpoint)], time_only)
        count_stop = cells.arrival if endpoint == "arrival" else cells.stop
        if cells[["route", "hour"]].assign(count_stop=count_stop).duplicated().any():
            raise ValueError("같은 횟수 기록이 여러 선택 셀에 중복 배정됩니다")
        normalized = normalize_fixed(joint_grid(panel, cells, counts, dates, endpoint), cells)
        for segment, original in time_only.groupby("segment"):
            part = cells[cells.segment.eq(segment)]
            meta = original.iloc[0]
            description = {k: meta[k] for k in ["group", "from_ars", "to_ars", "from_order", "from_name", "to_name"]}
            eligibility.append({"endpoint": endpoint, "segment": segment, **description,
                                "time_only_cells": len(original), "joint_cells": len(part), "joint_routes": part.route.nunique(),
                                "retained_cell_fraction": len(part) / len(original)})
        data, keys = normalized.copy(), cells.copy()
        data["group"], keys["group"] = data.segment, keys.segment
        for period, period_dates in calendar.items():
            for segment, piece in data[data.date.isin(period_dates)].groupby("segment"):
                states.append({"endpoint": endpoint, "segment": segment, "period": period, "expected_cell_days": len(piece),
                               "joint_observed": int(piece.joint_known.sum()),
                               "zero_trips_positive_boardings": int(piece.zero_trips_positive_boardings.sum())})
        daily = {metric: aggregate_daily(data.assign(index=data[metric + "_index"]), keys, dates,
                    "equal_cells", source["minimum_daily_coverage"]) for metric in METRICS}
        daily["boardings_per_recorded_trip"] = daily_ratio(data, keys, dates, calendar["pre2024"], source["minimum_daily_coverage"])
        for metric, values in daily.items():
            dailies.append(values.assign(endpoint=endpoint, metric=metric).rename(columns={"group": "segment"}))
            for segment, original in time_only.groupby("segment"):
                chosen = cells[cells.segment.eq(segment)]
                meta = original.iloc[0]
                description = {k: meta[k] for k in ["group", "from_ars", "to_ars", "from_order", "from_name", "to_name"]}
                part = values[values.group.eq(segment)]
                for comparison, (before, after) in source["comparisons"].items():
                    result = describe_comparison(part, calendar[before], calendar[after], source,
                                                 interval=endpoint == cfg["primary_endpoint"])
                    route_pass = chosen.route.nunique() >= cfg["minimum_routes_per_segment"]
                    rows.append({"endpoint": endpoint, "segment": segment, **description, "metric": metric,
                                 "comparison": comparison, "selected_cells": len(chosen), "selected_routes": chosen.route.nunique(),
                                 **result, "minimum_routes_pass": route_pass, "quality_pass": result["quality_pass"] and route_pass})
        print(f"구간별 운영 연장: {endpoint}, {len(cells)}개 고정 셀, {cells.segment.nunique()}개 구간", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    tables = {"comparisons.csv": pd.DataFrame(rows), "daily.csv": pd.concat(dailies, ignore_index=True),
              "eligibility.csv": pd.DataFrame(eligibility), "observation_states.csv": pd.DataFrame(states)}
    for name, table in tables.items():
        table.to_csv(OUT / name, index=False)
    refs = ["overnight_segment_operations_config.yaml", cfg["source_config"], cfg["source_audit"], cfg["selection"],
            cfg["time_only_audit"], cfg["time_only_selection"], "results/directional/station_registry.csv", source["calendar_from"],
            "gangnam/overnight_operations_persistence.py", "gangnam/overnight_mechanism.py", "gangnam/overnight_sensitivity.py",
            "gangnam/overnight_bus.py", "gangnam/overnight_bus_extract.py", "gangnam/overnight_persistence.py"]
    write_json(OUT / "audit.json", {"completed_at": utcnow(), "configuration": cfg, "calendar": calendar,
               "code_sha256": sha256(Path(__file__)), "inputs": {p: sha256(CASE / p) for p in refs}, "source_audits": audits,
               "comparisons": len(rows), "quality_pass": int(tables["comparisons.csv"].quality_pass.sum()),
               "outputs": {name: sha256(OUT / name) for name in tables}, "interpretation": cfg["interpretation"]})
