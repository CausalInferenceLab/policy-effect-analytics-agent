"""기존 버스 원본의 16시간 캐시를 보존하며 관측 상태와 고정 구간 패널을 만든다."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, write_json
from .directional import CELL, expected_dates
from .followup import clean_duplicates

RAW = CASE / "data/overnight/bus"
OUT = CASE / "results/overnight/bus"
OLD = CASE / "results/directional"


def load_wide(kind, cfg):
    """해시를 대조한 기존 추출물만 읽고 이전 결과 파일에는 쓰지 않는다."""
    entries = [x for x in json.loads((OLD / "extraction_audit.json").read_text()) if x["kind"] == kind]
    months = set(cfg["months"] + cfg.get("boundary_months", []))
    if {x["month"] for x in entries} != months:
        raise ValueError(f"버스 캐시 월 구성이 다릅니다: {kind}")
    values = [f"h{h:02}" for h in cfg["hours"]]
    parts = []
    for entry in entries:
        path = CASE / entry["path"]
        if (not path.resolve().is_relative_to((CASE / "data").resolve())
                or sha256(path) != entry["sha256"] or not set(cfg["hours"]).issubset(entry["hours"])):
            raise ValueError(f"버스 캐시 경로·해시·시간 불일치: {kind}")
        frame = pd.read_parquet(path)
        parts.append(frame[[c for c in frame if not c.startswith("h") or c in values]])
    d = pd.concat(parts, ignore_index=True)
    keys = ["date", "route", "stop", "sequence"] + (["arrival", "arrival_sequence"] if kind == "bus_time" else [])
    d, audit = clean_duplicates(d, keys)
    d["date"] = pd.to_datetime(d.date, format="%Y%m%d", errors="raise").dt.strftime("%Y-%m-%d")
    d = d[d.date.str[:7].isin(cfg["months"]) & d.route.ne("0")].copy()
    actual = {pd.Timestamp(t).strftime("%Y-%m-%d") for x in entries for t in x["dates"]}
    audit.update(rows=len(d), source_available_dates=sorted(set(expected_dates(cfg)) & actual),
                 source_missing_dates=sorted(set(expected_dates(cfg)) - actual),
                 input_files=[{"path": x["path"], "sha256": x["sha256"]} for x in entries])
    return d, audit


def candidate_routes():
    d = pd.read_csv(OLD / "route_movement.csv", dtype={"route": str, "family": str})
    d = d[["route", "family", "policy_group"]].drop_duplicates()
    if d.route.duplicated().any():
        raise ValueError("노선 후보가 둘 이상의 정책군에 속합니다")
    return d


def make_time_panel(wide, stations, cfg):
    """행 부재와 행 내부 0/공란을 보존하며 중복 방문 구간은 격리한다."""
    repeated = wide.duplicated(["date", "route", "stop", "arrival"], keep=False)
    d = wide.loc[~repeated].copy()
    info = stations.set_index("stop")
    for endpoint, prefix in (("stop", "from"), ("arrival", "to")):
        for col in ("group", "order", "historical_id_ars_pair", "historical_2023_pair"):
            d[f"{prefix}_{col}"] = d[endpoint].map(info[col])
    valid = d.from_group.eq(d.to_group) & d.from_group.isin(cfg["primary_groups"] + cfg["secondary_groups"])
    valid &= d.from_group.eq("curb_south") | d.to_order.gt(d.from_order)
    history = (d.from_historical_id_ars_pair.eq(True) & d.to_historical_id_ars_pair.eq(True)
               & d.from_historical_2023_pair.eq(True) & d.to_historical_2023_pair.eq(True))
    valid &= d.from_group.eq("curb_south") | history
    d = d.loc[valid].copy()
    d["group"] = d.from_group
    d = d.melt(id_vars=["date", "route", "stop", "arrival", "group"], value_vars=[f"h{h:02}" for h in cfg["hours"]],
               var_name="hour", value_name="raw_value")
    d["hour"] = d.hour.str[1:].astype(int)
    d["record_status"] = np.select([d.raw_value.isna(), d.raw_value.eq(0), d.raw_value.lt(0)],
                                    ["blank", "zero", "negative"], default="positive")
    d["value"] = d.raw_value.where(d.raw_value.gt(0))
    if d.duplicated(["date", *CELL]).any():
        raise ValueError("운행시간 날짜·셀 중복")
    return d, int(repeated.sum())


def summarize_records(d, cfg):
    bands = {hour: band for band, hours in cfg["bus_exploration"]["bands"].items() for hour in hours}
    part = d.assign(band=d.hour.map(bands).fillna("between_bands"))
    return part.groupby(["date", "group", "band", "record_status"], observed=True).size().rename("cells").reset_index()


def prepare():
    cfg = read_yaml("overnight_config.yaml")
    base = read_yaml(cfg["bus_exploration"]["base_config"])
    base["hours"] = cfg["bus_exploration"]["hours"]
    RAW.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    stations = pd.read_csv(OLD / "station_registry.csv", dtype={"stop": str, "ars": str})
    wide, audit = load_wide("bus_time", base)
    panel, repeated = make_time_panel(wide, stations, base)
    routes = candidate_routes()
    panel = panel.merge(routes, on="route", how="left", validate="many_to_one")
    panel["policy_group"] = panel.policy_group.fillna("other_or_unclassified")
    path = RAW / "time_panel.parquet"
    panel.to_parquet(path, index=False)
    summarize_records(panel, cfg).to_csv(OUT / "daily_record_states.csv", index=False)
    audit.update(panel_rows=len(panel), excluded_revisit_rows=repeated, panel_path=str(path.relative_to(CASE)),
                 panel_sha256=sha256(path), station_registry_sha256=sha256(OLD / "station_registry.csv"),
                 route_candidates_sha256=sha256(OLD / "route_movement.csv"), code_sha256=sha256(Path(__file__)),
                 source_audit_sha256=sha256(OLD / "extraction_audit.json"), hours=base["hours"],
                 note="정책 후보는 당시 경로로 대조한 현재 ID 후보이며 역사적 노선명 확정이 아님. 비후보도 무처치 대조군이 아님.")
    write_json(OUT / "panel_audit.json", audit)
    print(f"확장 버스 패널: {len(panel):,}행, {panel.route.nunique()}개 노선 ID", flush=True)


def read_panel():
    audit = json.loads((OUT / "panel_audit.json").read_text())
    path = CASE / audit["panel_path"]
    if not path.resolve().is_relative_to(RAW.resolve()) or sha256(path) != audit["panel_sha256"]:
        raise ValueError("확장 버스 패널 경로·해시 불일치")
    return pd.read_parquet(path), audit
