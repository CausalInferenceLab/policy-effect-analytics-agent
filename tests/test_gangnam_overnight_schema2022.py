"""2022 원본의 뒤쪽 행 손상·잘못된 날짜·빈 파일을 성공으로 처리하지 않는지 검사한다."""

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
audit = importlib.import_module("gangnam.overnight_2022_audit")


def test_later_row_width_mismatch_is_not_hidden_by_good_first_row():
    result = audit.audit_reader(iter([["기준_날짜", "x"], ["20220520", "1"], ["20220521", "2", "extra"]]), ["기준_날짜", "x"])
    assert result["status"] == "row_width_mismatch"
    assert not result["structurally_usable"]
    assert result["row_width_counts"] == {2: 1, 3: 1}


def test_bad_calendar_date_and_empty_file_are_distinct_failures():
    invalid = audit.audit_reader(iter([["기준_날짜"], ["20220230"]]), ["기준_날짜"])
    empty = audit.audit_reader(iter([["기준_날짜"]]), ["기준_날짜"])
    assert invalid["status"] == "invalid_dates"
    assert invalid["dates"] == {}
    assert empty["status"] == "empty"
    assert not empty["structurally_usable"]


def test_damaged_header_does_not_silently_become_known_column():
    result = audit.audit_reader(iter([['?"기준_날짜"', "x"], ["20220520", "1"]]), ["기준_날짜", "x"])
    assert result["status"] == "header_mismatch"
    assert result["invalid_date_rows"] == 1
