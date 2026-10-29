"""도로 보간점의 키·좌표 정밀도와 현재 표준링크 대응을 비교한다."""

import json
import re

import numpy as np
import pandas as pd
from openpyxl import load_workbook

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .deepening_geometry_data import MANIFEST, OUT, verified


def identifier(value):
    text = str(value).removesuffix(".0")
    if not re.fullmatch(r"\d{10}", text):
        raise ValueError("10자리 링크 ID 형식이 다릅니다")
    return text


def validate_mapping_sequence(data):
    """비어 있거나 중복된 순서를 그대로 표시하고 임의의 연결 순서를 만들지 않는다."""
    data = data.copy()
    data["sequence"] = pd.to_numeric(data.sequence, errors="raise")
    known = data.sequence.notna()
    if data.loc[known, "sequence"].le(0).any() or not data.loc[known, "sequence"].eq(np.floor(data.loc[known, "sequence"])).all():
        raise ValueError("표준링크의 알려진 순번이 양의 정수가 아닙니다")
    conflict = known & data.duplicated(["link_id", "sequence"], keep=False)
    data["order_state"] = np.select([~known, conflict], ["missing", "repeated_known_order"], default="known_unique_order")
    data["sequence"] = data.sequence.astype("Int64")
    return data


def read_table(entry):
    verified(entry)
    book = load_workbook(CASE / entry["path"], read_only=True, data_only=True)
    try:
        if len(book.worksheets) != 1:
            raise ValueError("도로 형상 시트 수가 예상과 다릅니다")
        sheet = book.worksheets[0]
        sheet.reset_dimensions()
        rows = sheet.values
        header = list(next(rows))
        data = pd.DataFrame((row for row in rows if any(value is not None for value in row)), columns=header)
    finally:
        book.close()
    if header == ["LINK_ID", "VER_SEQ", "GRS80TM_X", "GRS80TM_Y"]:
        data.columns = ["link_id", "sequence", "x", "y"]
        data["link_id"] = data.link_id.map(identifier)
        for col in ["sequence", "x", "y"]:
            data[col] = pd.to_numeric(data[col], errors="raise")
        if not np.isfinite(data[["sequence", "x", "y"]]).all().all():
            raise ValueError("도로 좌표·순번 공란 또는 비유한 값")
        if data.sequence.le(0).any() or not data.sequence.eq(np.floor(data.sequence)).all():
            raise ValueError("보간점 순번은 양의 정수여야 합니다")
        if data.duplicated(["link_id", "sequence"]).any():
            raise ValueError("도로 보간점 ID·순번 중복")
        data["sequence"] = data.sequence.astype(int)
    elif header == ["서비스링크", "표준링크순서", "표준링크아이디"]:
        data.columns = ["link_id", "sequence", "standard_link_id"]
        data["link_id"] = data.link_id.map(identifier)
        data["standard_link_id"] = data.standard_link_id.map(identifier)
        data = validate_mapping_sequence(data)
    else:
        raise ValueError("도로 형상·대응 헤더 변경")
    return data, dict(id=entry["id"], title=entry["title"], rows=len(data), links=data.link_id.nunique(),
                       columns=header, path=entry["path"], sha256=entry["sha256"])


def compare_vertices(before, after):
    merged = before.merge(after, on=["link_id", "sequence"], how="outer", suffixes=("_2022", "_2025"),
                          validate="one_to_one", indicator=True)
    merged["both_versions"] = merged._merge.eq("both")
    for coord in ["x", "y"]:
        a, b = merged[coord + "_2022"], merged[coord + "_2025"]
        merged[coord + "_difference"] = b - a
        merged[coord + "_exact"] = a.eq(b) & merged.both_versions
        merged[coord + "_rounding_compatible"] = b.eq(np.rint(a)) & merged.both_versions
    merged["exact_coordinates"] = merged.x_exact & merged.y_exact
    merged["rounding_compatible"] = merged.x_rounding_compatible & merged.y_rounding_compatible
    merged["record_state"] = merged._merge.astype(str)
    return merged.drop(columns="_merge")


def run():
    manifest = json.loads(MANIFEST.read_text())
    if len(manifest["files"]) != 3:
        raise ValueError("형상 비교의 고정 원본 수 불일치")
    tables, audits = {}, []
    for entry in manifest["files"]:
        frame, audit = read_table(entry)
        tables[entry["id"]] = frame
        audits.append(audit)
    before, after, mapping = tables["OA-15060_2"], tables["OA-15060_3"], tables["OA-15061_4"]
    paired = compare_vertices(before, after)
    cfg = read_yaml("deepening_road_config.yaml")
    labels = {link: group for group, spec in cfg["groups"].items() for link in spec["links"]}
    summaries = []
    for link, group in labels.items():
        d = paired[paired.link_id.eq(link)]
        matches = mapping[mapping.link_id.eq(link)]
        summaries.append(dict(group=group, link_id=link, vertices_2022=int(d.x_2022.notna().sum()),
            vertices_2025=int(d.x_2025.notna().sum()), matched_vertices=int(d.both_versions.sum()),
            exact_coordinate_pairs=int(d.exact_coordinates.sum()), rounding_compatible_pairs=int(d.rounding_compatible.sum()),
            maximum_abs_x_difference=float(d.x_difference.abs().max()), maximum_abs_y_difference=float(d.y_difference.abs().max()),
            standard_mapping_rows=len(matches), missing_standard_order_rows=int(matches.sequence.isna().sum()),
            repeated_standard_order_rows=int(matches.order_state.eq("repeated_known_order").sum()),
            standard_links=";".join(matches.sort_values("sequence").standard_link_id)))
    target_vertices = paired[paired.link_id.isin(labels)].copy()
    target_vertices["group"] = target_vertices.link_id.map(labels)
    target_mapping = mapping[mapping.link_id.isin(labels)].copy()
    target_mapping["group"] = target_mapping.link_id.map(labels)
    outputs = {"selected_link_summary.csv": pd.DataFrame(summaries), "selected_vertices.csv": target_vertices,
               "selected_standard_mapping.csv": target_mapping,
               "mapping_order_issues.csv": mapping[mapping.order_state.ne("known_unique_order")]}
    for name, frame in outputs.items():
        frame.to_csv(OUT / name, index=False, lineterminator="\n")
    write_json(OUT / "audit.json", dict(completed_at=utcnow(), code_sha256=sha256(__file__),
        source_manifest_sha256=sha256(MANIFEST), selection_config_sha256=sha256(CASE / "deepening_road_config.yaml"),
        files=audits, overall=dict(keys=len(paired), matched_keys=int(paired.both_versions.sum()),
          only_2022=int(paired.record_state.eq("left_only").sum()), only_2025=int(paired.record_state.eq("right_only").sum()),
          exact_coordinate_pairs=int(paired.exact_coordinates.sum()), rounding_compatible_pairs=int(paired.rounding_compatible.sum()),
          exact_or_rounding_compatible_pairs=int((paired.exact_coordinates | paired.rounding_compatible).sum()),
          coordinates_2025_all_integer=bool(after[["x", "y"]].eq(np.floor(after[["x", "y"]])).all().all()),
          mapping_missing_order_rows=int(mapping.sequence.isna().sum()),
          mapping_services_with_missing_order=int(mapping.loc[mapping.sequence.isna(), "link_id"].nunique()),
          mapping_repeated_known_order_rows=int(mapping.order_state.eq("repeated_known_order").sum()),
          standard_link_ids_shared_by_multiple_service_links=int(mapping.groupby("standard_link_id").link_id.nunique().gt(1).sum())),
        target_links=len(labels), selected_vertex_rows=len(target_vertices), selected_mapping_rows=len(target_mapping),
        outputs={name: sha256(OUT / name) for name in outputs}, limitations=[
          "GRS80TM_X/Y header alone does not identify projection parameters; no distance or geographic overlay calculated",
          "2025 publication and rounding compatibility do not establish geometry validity in 2024",
          "2025 mapping is not a historical change log; no construction exposure inferred"] ))
    print(f"보간점 {len(paired):,}개 키 대조, 지정 링크 {len(labels)}개·보간점 {len(target_vertices)}행", flush=True)
