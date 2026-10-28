"""지하철 원본의 전체 행 구조·기간 격리와 공개 월 필터 명세를 검사한다."""

import csv
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
module = importlib.import_module("gangnam.overnight_subway_data")


def test_csv_validates_nonselected_rows_and_never_accepts_another_month(tmp_path):
    path = tmp_path / "daily.csv"
    header = ["사용일자", "노선명", "역명", "승차총승객수", "하차총승객수", "등록일자"]
    rows = [["20240501", "2호선", "강남", "0", "5", "20240504"], ["20240501", "1호선", "서울역", "1", "2", "20240504"]]
    def write(values):
        with path.open("w", encoding="cp949", newline="") as f:
            csv.writer(f).writerows([header, *values])
    write(rows)
    assert module.validate(path, "2024-05", "daily")["rows"] == 2
    write([rows[0], rows[1][:-1]])
    with pytest.raises(ValueError, match="행 폭"):
        module.validate(path, "2024-05", "daily")
    write([rows[0], ["20260601", *rows[1][1:]]])
    with pytest.raises(ValueError, match="실제 기간"):
        module.validate(path, "2024-05", "daily")
    with pytest.raises(ValueError, match="잠금"):
        module.validate(path, "2026-05", "daily")


def test_hourly_columns_require_complete_nonoverlapping_hours():
    header = ["사용월", "호선명", "지하철역"] + [f"{h:02}시-{(h+1)%24:02}시 {flow}인원" for h in range(24) for flow in ["승차", "하차"]]
    assert len(module.columns(header, "hourly_month")["hours"]) == 48
    with pytest.raises(ValueError, match="24시간"):
        module.columns(header[:-1], "hourly_month")
    bad = header.copy()
    bad[3] = "00시-02시 승차인원"
    with pytest.raises(ValueError, match="범위"):
        module.columns(bad, "hourly_month")


def test_sheet_request_preserves_public_form_and_adds_only_month_filter():
    values = {"srvType": "S", "infId": "OA-12252", "serviceKind": "0", "pageNo": "1", "ssUserId": "SAMPLE_VIEW", "strWhere": "", "strOrderby": "USE_MM DESC"}
    form = '<form name="frmSheet">' + ''.join(f'<input name="{k}" value="{v}">' for k,v in values.items()) + '<option value="USE_MM">사용월</option></form>'
    result = module.sheet_request(form, "2024-05")
    assert result["filterCol"] == "USE_MM" and result["txtFilter"] == "202405" and result["strWhere"] == ""
    with pytest.raises(ValueError, match="필터"):
        module.sheet_request(form.replace("USE_MM", "USE_YEAR"), "2024-05")
