"""독립 XML 판독에서 자정 끝 열·0·결측과 잠금 연도를 구분한다."""

import importlib
import sys
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
pytest.importorskip("pandas")
pytest.importorskip("pyarrow")
mod = importlib.import_module("gangnam.deepening_road_raw_check")


def test_xml_reader_preserves_last_hour_and_missing_states(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CASE", tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    path = data / "sample.xlsx"
    header = ["일자", "요일", "도로명", "링크아이디", "시점명", "종점명", "방향", "거리",
              "차선수", "기능유형구분", "도심/외곽구분", "권역구분", *[f"~{h:02}시" for h in range(1, 25)]]
    values = ["20240626", "수", "강남대로", "1.0", "A", "B", "하행", "100", "2", "도로", "외곽", "서초",
              "0", "", "-1", *[str(h) for h in range(3, 24)]]
    columns = [chr(65 + n) for n in range(26)] + ["A" + chr(65 + n) for n in range(10)]
    root = ET.Element(mod.NS + "worksheet")
    sheet = ET.SubElement(root, mod.NS + "sheetData")
    for row_number, row_values in enumerate([header, values], 1):
        row = ET.SubElement(sheet, mod.NS + "row", r=str(row_number))
        for column, value in zip(columns, row_values, strict=True):
            if value == "":
                continue
            cell = ET.SubElement(row, mod.NS + "c", r=f"{column}{row_number}", t="inlineStr")
            ET.SubElement(ET.SubElement(cell, mod.NS + "is"), mod.NS + "t").text = value
    book = f'<workbook xmlns="{mod.NS[1:-1]}" xmlns:r="{mod.REL[1:-1]}"><sheets><sheet name="자료" r:id="rId1"/></sheets></workbook>'
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", book)
        archive.writestr("xl/_rels/workbook.xml.rels", '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr("xl/worksheets/sheet1.xml", ET.tostring(root))
    cfg = dict(locked_year=2026, sentinels=["", "-"])
    rows, audit = mod.parse_source((dict(month="2024-06", path="data/sample.xlsx", sha256=mod.sha256(path)),
                                    ["2024-06-26"], ["1"], cfg))
    assert len(rows) == 24 and audit["selected_link_days"] == 1
    assert [row["source_status"] for row in rows[:3]] == ["nonpositive", "blank_or_sentinel", "nonpositive"]
    assert rows[-1]["hour"] == 23 and rows[-1]["source_speed"] == 23


def test_locked_year_rejected_before_xml_open():
    with pytest.raises(ValueError, match="잠금"):
        mod.parse_source((dict(month="2026-01"), ["2026-01-01"], ["1"], dict(locked_year=2026)))
