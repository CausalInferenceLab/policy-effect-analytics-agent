"""서울 공개 보조 자료의 실제 월·파일 서비스 번호·잠금 연도 처리를 검증한다."""

import importlib
import sys
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
data = importlib.import_module("gangnam.overnight_auxiliary_data")


def test_download_form_uses_dataset_specific_service_number():
    html = '''<form name="frmApiDown"><input name="infSeq" value="2"></form>
    <form name="frmFile"><input name="infId" value="OA-21221"><input name="infSeq" value="1"></form>
    <span title="example.zip" onclick="downloadFile('2405');">example.zip</span>'''
    assert data.download_request(html, "OA-21221", "example.zip") == {
        "infId": "OA-21221", "infSeq": "1", "seq": "2405", "seqNo": ""}
    with pytest.raises(ValueError, match="불일치"):
        data.download_request(html, "OA-21222", "example.zip")


def test_card_file_cannot_masquerade_as_another_month(tmp_path):
    path = tmp_path / "card.csv"
    pd.DataFrame({"사용년월": ["202404", "202405"], "노선번호": ["1", "2"],
                  "표준버스정류장ID": ["100", "200"], "버스정류장ARS번호": ["01001", "01002"]}).to_csv(
        path, index=False, encoding="cp949")
    with pytest.raises(ValueError, match="실제 월"):
        data.card_validate(path, "2024-05")


def test_locked_card_and_transfer_requests_are_rejected():
    cfg = data.read_yaml("overnight_auxiliary_config.yaml")
    assert len(data.requests_config(cfg)) == 21
    for key in ("card", "transfer_probe"):
        bad = deepcopy(cfg)
        if key == "card":
            bad[key]["identity_only_months"].append("2026-01")
        else:
            bad[key]["months"].append("2026-01")
        with pytest.raises(ValueError, match="잠금"):
            data.requests_config(bad)
