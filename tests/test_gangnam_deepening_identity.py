"""역사적 파일의 축약 차원·키 충돌·날짜 잠금·좌표 비교를 검증한다."""

import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
from gangnam.deepening_identity import (
    date_value,
    identifier,
    normalize,
    policy_brackets,
    read_table,
    recorded_changes,
    target_match,
)


def test_csv_trailing_column_requires_empty_values(tmp_path):
    path = tmp_path / "sample.csv"
    path.write_bytes("STDR_DE,NODE_ID,\n20230101,100000001,\n".encode("cp949"))
    header, rows, audit = read_table(path)
    assert header == ["STDR_DE", "NODE_ID"] and len(rows) == 1
    assert audit["trailing_blank_columns"] == 1
    path.write_text("STDR_DE,NODE_ID,\n20230101,100000001,unexpected\n")
    with pytest.raises(ValueError, match="이름 없는 열"):
        read_table(path)


def test_xlsx_reads_full_xml_despite_false_a1_dimension(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "full.xlsx"
    book = openpyxl.Workbook()
    book.active.append(["STDR_DE", "ROUTE_ID"])
    book.active.append(["20230101", "100100019"])
    book.active.append(["20230201", "100100019"])
    book.save(path)
    corrupt = tmp_path / "dimension.xlsx"
    with ZipFile(path) as source, ZipFile(corrupt, "w") as target:
        for name in source.namelist():
            value = source.read(name)
            if name == "xl/worksheets/sheet1.xml":
                value = value.replace(b'ref="A1:B3"', b'ref="A1"')
            target.writestr(name, value)
    header, rows, audit = read_table(corrupt)
    assert header == ["STDR_DE", "ROUTE_ID"] and len(rows) == 2
    assert audit["declared_rows"] == 1 and audit["actual_rows"] == 3


def test_ids_and_dates_are_not_silently_coerced():
    assert identifier("1001", 5) == "01001"
    assert identifier("16614A", 5) == "16614A"
    for value in ("nan", "1.25", "12-34"):
        with pytest.raises(ValueError):
            identifier(value, 5)
    assert date_value("20240229", [2024]) == "2024-02-29"
    for value in ("20260201", "20240230"):
        with pytest.raises(ValueError):
            date_value(value, [2023, 2024, 2025])


def test_snapshot_date_locked_before_coordinate_values():
    entry = {"title": "서울시버스정류소위치정보(20260101).xlsx", "id": "test", "kind": "stop_positions"}
    with pytest.raises(ValueError, match="허용 범위 밖"):
        normalize(["NODE_ID", "ARS_ID", "정류소명", "X좌표", "Y좌표"],
                  [["121000011", "22011", "강남역", "must_not_parse", "37.5"]], entry, [2024, 2025])


def test_duplicate_and_missing_keys_never_look_like_matches():
    row = {"node": "121000011", "ars": "22011"}
    assert target_match([row, row], "node", row["node"])[0] == "duplicate_key"
    assert target_match([row], "node", "other")[0] == "absent_from_catalog"
    assert target_match([row], "node", row["node"], "22009")[0] == "ars_mismatch"


def test_recorded_coordinates_do_not_imply_physical_distance_or_fill_gaps():
    base = {"kind": "stop_positions", "target_node": "121000011", "target_ars": "22011",
            "target_group": "central_south", "match_status": "matched", "x": 127.0, "y": 37.5,
            "name": "강남역", "type": "중앙차로"}
    rows = [dict(base, date="2024-04-01", source_id="a"),
            dict(base, date="2024-08-12", source_id="b", match_status="absent_from_catalog"),
            dict(base, date="2024-09-03", source_id="c", x=127.0001),
            dict(base, date="2024-10-02", source_id="d", x=127.000100001)]
    result = recorded_changes(rows, 1e-7)
    assert len(result) == 3 and not result[0]["comparable"] and not result[1]["comparable"]
    assert result[0]["days_between_records"] == 133
    assert not result[2]["coordinate_record_changed"]
    assert all(not any("meter" in k or "distance" in k for k in r) for r in result)


def test_policy_bracket_uses_observed_dates_without_inventing_june_location():
    base = {"kind": "stop_positions", "target_node": "121000011", "target_ars": "22011",
            "target_group": "central_south", "match_status": "matched", "x": 127.0, "y": 37.5,
            "name": "강남역", "type": "중앙차로"}
    rows = [dict(base, date="2024-04-01", source_id="a"),
            dict(base, date="2024-08-12", source_id="b", match_status="absent_from_catalog"),
            dict(base, date="2024-08-12", source_id="c", kind="median_stops", x=127.0001),
            dict(base, date="2024-09-03", source_id="d", x=127.0001)]
    result = policy_brackets(rows, "2024-06-29", 1e-7)[0]
    assert result["before_date"] == "2024-04-01" and result["after_source_id"] == "c"
    assert result["days_between_records"] == 133 and result["coordinate_record_changed"]
    assert not result["same_catalog_kind"] and not result["physical_change_date_verified"]
