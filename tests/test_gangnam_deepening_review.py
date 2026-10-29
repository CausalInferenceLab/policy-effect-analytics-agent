"""원본 없는 공개 검토에서 중복·품질 실패·비유한 수치를 거절하는지 확인한다."""

import importlib
import json
import sys
from pathlib import Path

import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
mod = importlib.import_module("review_deepening")


def test_public_claim_rejects_ambiguous_or_failed_row(tmp_path):
    path = tmp_path / "results/deepening/sample.csv"
    path.parent.mkdir(parents=True)
    claim = dict(id="one", source="results/deepening/sample.csv", where={"group": "a"}, field="value",
                 require={"quality": "True"}, description="검증", unit="수", interpretation="검증")
    path.write_text("group,value,quality\na,1,False\n")
    with pytest.raises(ValueError, match="품질"):
        mod.derive(tmp_path, {"claims": [claim]})
    path.write_text("group,value,quality\na,1,True\na,2,True\n")
    with pytest.raises(ValueError, match="정확히 하나"):
        mod.derive(tmp_path, {"claims": [claim]})


def test_public_json_zero_is_checked_but_boolean_is_not_a_numeric_claim(tmp_path):
    path = tmp_path / "results/deepening/sample.json"
    path.parent.mkdir(parents=True)
    claim = dict(id="one", source="results/deepening/sample.json", keys=["mismatches"], description="검증", unit="수", interpretation="검증")
    path.write_text(json.dumps({"mismatches": 0}))
    assert mod.derive(tmp_path, {"claims": [claim]})[0][0]["value"] == "0"
    path.write_text(json.dumps({"mismatches": False}))
    with pytest.raises(ValueError, match="유한 숫자"):
        mod.derive(tmp_path, {"claims": [claim]})
    claim["expected"] = 0
    path.write_text(json.dumps({"mismatches": 1}))
    with pytest.raises(ValueError, match="필수 검증"):
        mod.derive(tmp_path, {"claims": [claim]})
