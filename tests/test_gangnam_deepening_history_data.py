"""과거 파일 목록의 폼 구분·중복과 잠금 연도 차단을 확인한다."""

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
module = importlib.import_module("gangnam.deepening_history_data")


def test_file_form_does_not_use_api_sequence_and_duplicate_links_are_one_file():
    html = '''<form id="frmApiDown"><input name="infSeq" value="99"></form>
    <form id="frmFile"><input name="infId" value="OA-15067"><input name="infSeq" value="2"></form>
    <span title="2024년1~4월.csv" onclick="javascript:downloadFile('25');">목록</span>
    <a title="2024년1~4월.csv" href="javascript:downloadFile('25');">내려받기</a>'''
    form, files = module.parse_catalog(html, "OA-15067")
    assert form["infSeq"] == "2" and files == {"2024년1~4월.csv": "25"}
    with pytest.raises(ValueError, match="다른 다운로드"):
        module.parse_catalog(html + '<span title="2024년1~4월.csv" onclick="downloadFile(\'26\')">다름</span>', "OA-15067")


def test_service_error_and_path_in_title_are_rejected():
    with pytest.raises(ValueError, match="서비스 오류"):
        module.parse_catalog("<html>서비스 지연이 발생하고 있습니다</html>", "OA-15067")
    with pytest.raises(ValueError, match="경로"):
        module.parse_catalog('<span title="../2024.csv" onclick="downloadFile(\'1\')">파일</span>', "OA-15067")


def test_only_declared_years_and_explicit_metadata_are_selected():
    cfg = {"metadata_title_prefix": "컬럼정의", "allowed_data_extensions": [".csv", ".xlsx"],
           "years": [2023, 2024, 2025], "locked_outcome_years": [2026]}
    assert module.selected_title("서울시버스정류소(20240812).xlsx", cfg) == (True, False)
    assert module.selected_title("2023년각월.csv", cfg) == (True, False)
    assert module.selected_title("서울시버스정류소(20261029).xlsx", cfg) == (False, False)
    assert module.selected_title("2025~2026년.csv", cfg) == (False, False)
    assert module.selected_title("최신.csv", cfg) == (False, False)
    assert module.selected_title("컬럼정의_정류소.xlsx", cfg) == (True, True)
def test_request_replay_preserves_timestamp_and_rejects_changes(tmp_path):
    from gangnam.deepening_history_data import preserve_requests

    path = tmp_path / "requests.json"
    payload = {"configuration": {"years": [2023, 2024, 2025]}, "inputs": {}, "requests": []}
    preserve_requests(path, payload)
    before = path.read_bytes()
    preserve_requests(path, payload)
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="기존"):
        preserve_requests(path, {**payload, "requests": [{"id": "changed"}]})
