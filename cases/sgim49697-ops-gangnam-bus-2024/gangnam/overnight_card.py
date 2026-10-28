"""월별 서울 면허 버스 카드의 수록 범위와 역사적 정류장 대응을 검증한다."""

from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .overnight_auxiliary_data import MANIFEST, verify

OUT = CASE / "results/overnight/cards"
CACHE = CASE / "data/overnight/auxiliary/processed"
REGISTRY = CASE / "results/directional/station_registry.csv"
IDS = ["사용년월", "노선번호", "노선명", "표준버스정류장ID", "버스정류장ARS번호", "역명"]
RENAMES = dict(zip(IDS, ["month", "route_label", "route_name", "stop", "ars", "stop_name"], strict=True))


class CardSchemaError(ValueError):
    """역사적 월 파일의 손상된 헤더를 별도 격리하기 위한 오류다."""


def hour_columns(header):
    columns = {}
    for name in header:
        match = re.fullmatch(r"(\d{1,2})시(승차|하차)총승객수", name)
        if match:
            key = (int(match[1]), "boardings" if match[2] == "승차" else "alightings")
            if key in columns:
                raise ValueError("월 카드의 동일 시간·승하차 열이 중복됩니다")
            columns[key] = name
    if set(columns) != {(h, flow) for h in range(24) for flow in ["boardings", "alightings"]}:
        raise ValueError("월 카드의 24시간 승하차 열 구성이 다릅니다")
    return columns


def read_card(stream, month, stops, include_values):
    reader = csv.reader(stream)
    header = next(reader, [])
    if header[:6] != IDS or len(header) != len(set(header)):
        raise CardSchemaError(f"월 카드 식별 열·중복 헤더 오류: {header[:6]}")
    columns = hour_columns(header)
    positions = [header.index(c) for c in IDS]
    if include_values:
        positions += [header.index(c) for c in columns.values()]
    keep_names = [header[i] for i in positions]
    type_index = header.index("교통수단타입명") if "교통수단타입명" in header else None
    rows, routes, station_ids, types, selected = 0, set(), set(), Counter(), []
    for row in reader:
        rows += 1
        if len(row) != len(header) or row[0] != month.replace("-", ""):
            raise ValueError(f"월 카드 행 너비·실제 월 오류: {month} {rows}")
        routes.add(row[1])
        station_ids.add(row[3])
        types[row[type_index] if type_index is not None else "field_absent"] += 1
        if row[3] in stops:
            selected.append([row[i] for i in positions])
    if not rows:
        raise ValueError("월 카드 파일이 비어 있습니다")
    audit = {"month": month, "rows": rows, "header_columns": len(header), "route_labels": len(routes),
             "station_ids": len(station_ids), "transport_type_row_counts": dict(types),
             "selected_rows": len(selected), "values_read_for_analysis": include_values, "status": "usable"}
    frame = pd.DataFrame(selected, columns=keep_names).rename(columns=RENAMES)
    frame["month"] = month
    return frame, audit


def monthly_identity(frame, stations, month):
    rows = []
    for s in stations.itertuples():
        part = frame[frame.stop.eq(s.stop)]
        ars = sorted(set(part.ars))
        rows.append({"month": month, "group": s.group, "stop": s.stop, "expected_ars": s.ars,
                     "id_observed": not part.empty, "id_ars_pair_observed": s.ars in ars,
                     "all_observed_ars_agree": bool(ars == [s.ars]), "observed_ars": "|".join(ars),
                     "row_count": len(part), "route_label_count": part.route_label.nunique(),
                     "observed_names": "|".join(sorted({re.sub(r"\(\d+\)$", "", n) for n in part.stop_name}))})
    return rows


def eligible_long(frame, stations):
    keys = ["month", "route_label", "stop"]
    duplicate = frame.duplicated(keys, keep=False)
    expected = stations.set_index("stop").ars
    match = frame.ars.eq(frame.stop.map(expected))
    frame = frame.copy()
    frame["eligible_row"] = ~duplicate & match
    frame["excluded_reason"] = np.select([duplicate, ~match], ["repeated_route_stop", "id_ars_mismatch"], default="")
    excluded = frame.loc[~frame.eligible_row, [*keys, "ars", "stop_name", "excluded_reason"]]
    columns = hour_columns(frame.columns)
    d = frame.melt(id_vars=[*keys, "ars", "eligible_row"], value_vars=list(columns.values()),
                   var_name="source_column", value_name="raw_value")
    mapping = {name: key for key, name in columns.items()}
    d["hour"] = d.source_column.map(lambda x: mapping[x][0])
    d["flow"] = d.source_column.map(lambda x: mapping[x][1])
    raw = pd.to_numeric(d.raw_value.replace("", np.nan), errors="raise")
    if np.isinf(raw).any() or raw.dropna().mod(1).ne(0).any():
        raise ValueError("카드 승하차 인원에 비유한 값 또는 소수가 있습니다")
    d["status"] = np.select([~d.eligible_row, raw.isna(), raw.lt(0), raw.eq(0)],
                             ["excluded_row", "blank", "negative", "zero"], default="positive")
    d["value"] = raw.where(raw.ge(0) & d.eligible_row)
    return d.drop(columns=["raw_value", "source_column"]), excluded


def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    cfg = read_yaml("overnight_auxiliary_config.yaml")["card"]
    entries = [x for x in json.loads(MANIFEST.read_text())["files"] if x["kind"] in {"card", "card_history"}]
    stations = pd.read_csv(REGISTRY, dtype={"stop": str, "ars": str})
    stops = set(stations.stop)
    frames, audits, identities = [], [], []

    def consume(stream, entry, month, member=""):
        include = month in cfg["analysis_months"]
        try:
            frame, audit = read_card(stream, month, stops, include)
        except CardSchemaError as error:
            if entry["kind"] != "card_history" or include:
                raise
            audits.append({"month": month, "source_sha256": entry["sha256"], "member": member,
                           "status": "quarantined_header", "values_read_for_analysis": False, "error": str(error)})
            identities.extend({"month": month, "group": s.group, "stop": s.stop, "expected_ars": s.ars,
                               "source_status": "quarantined_header", "id_observed": None,
                               "id_ars_pair_observed": None, "all_observed_ars_agree": None} for s in stations.itertuples())
            print(f"카드 역사 파일 격리: {month} {error}", flush=True)
            return
        audits.append({**audit, "source_sha256": entry["sha256"], "member": member,
                       "transport_type_row_counts": json.dumps(audit["transport_type_row_counts"], ensure_ascii=False)})
        identities.extend({**x, "source_status": "usable"} for x in monthly_identity(frame, stations, month))
        if include:
            frames.append(frame)
        print(f"카드 범위·ID 확인: {month} {audit['rows']:,}행 / 선택 {len(frame):,}행", flush=True)

    for entry in entries:
        verify(entry)
        path = CASE / entry["path"]
        if entry["kind"] == "card_history":
            with ZipFile(path) as z:
                seen = set()
                for name in sorted(z.namelist()):
                    match = re.search(r"\((\d{2})", name)
                    if not match:
                        raise ValueError("연간 카드의 월별 파일명 오류")
                    month = f"{entry['month']}-{match[1]}"
                    if month in seen:
                        raise ValueError("연간 카드에 동일 월 파일이 중복됩니다")
                    seen.add(month)
                    with z.open(name) as f:
                        consume(io.TextIOWrapper(f, encoding="cp949"), entry, month, name)
                if seen != {f"{entry['month']}-{m:02}" for m in range(1, 13)}:
                    raise ValueError("연간 카드가 12개 월로 구성되지 않았습니다")
        else:
            with path.open(encoding="cp949", newline="") as f:
                consume(f, entry, entry["month"])
    if {x["month"] for x in audits if x["values_read_for_analysis"]} != set(cfg["analysis_months"]):
        raise ValueError("카드 분석 월 구성이 불완전합니다")
    long, excluded = eligible_long(pd.concat(frames, ignore_index=True), stations)
    path = CACHE / "card_panel.parquet"
    long.to_parquet(path, index=False)
    pd.DataFrame(audits).to_csv(OUT / "source_coverage.csv", index=False)
    pd.DataFrame(identities).to_csv(OUT / "station_identity.csv", index=False)
    excluded.to_csv(OUT / "excluded_rows.csv", index=False)
    status = long.groupby(["month", "flow", "status"]).size().rename("cells").reset_index()
    status.to_csv(OUT / "record_status.csv", index=False)
    write_json(OUT / "audit.json", {"completed_at": utcnow(), "source_manifest_sha256": sha256(MANIFEST),
                                   "config_sha256": sha256(CASE / "overnight_auxiliary_config.yaml"),
                                   "code_sha256": sha256(Path(__file__)), "registry_sha256": sha256(REGISTRY),
                                   "panel_path": str(path.relative_to(CASE)), "panel_sha256": sha256(path),
                                   "panel_rows": len(long), "excluded_rows": len(excluded),
                                   "csv_files": {p.name: sha256(p) for p in OUT.glob("*.csv")},
                                   "scope": "2022·2025년은 ID 이력만 확인. 수치 분석은 2023·2024년 서울 면허 버스 카드 기록에 한정."})
