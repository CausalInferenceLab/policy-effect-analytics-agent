"""공개 수치 검증의 중복 선택·보류·변조·사례 밖 경로 거부를 검사한다."""

import importlib.util
import json
from pathlib import Path

import pytest

location = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024/review_overnight.py"
spec = importlib.util.spec_from_file_location("gangnam_public_review", location)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def sample(tmp_path):
    source = tmp_path / "results/overnight/example.csv"
    source.parent.mkdir(parents=True)
    source.write_text("key,value,quality_pass\na,1.5,True\n", encoding="utf-8")
    claim = {"id": "a", "source": "results/overnight/example.csv", "where": {"key": "a"},
             "require": {"quality_pass": "True"}, "field": "value", "unit": "%", "description": "검증 예시", "interpretation": "기술 비교"}
    payload = {"claims": [claim]}
    (tmp_path / module.SPEC).write_text(json.dumps(payload), encoding="utf-8")
    return source, payload


def test_public_summary_detects_changed_values(tmp_path):
    source, _ = sample(tmp_path)
    result = module.review(tmp_path, write=True)
    assert result["claims"] == 1 and module.review(tmp_path) == result
    source.write_text("key,value,quality_pass\na,9.0,True\n", encoding="utf-8")
    with pytest.raises(ValueError, match="다릅니다"):
        module.review(tmp_path)


@pytest.mark.parametrize("rows,message", [("a,1.5,True\na,2.0,True\n", "1개"),
                                          ("a,1.5,False\n", "보류"), ("a,nan,True\n", "숫자")])
def test_ambiguous_failed_or_nonfinite_claim_is_rejected(tmp_path, rows, message):
    source, payload = sample(tmp_path)
    source.write_text("key,value,quality_pass\n" + rows, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        module.derive(tmp_path, payload)


def test_path_escape_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="사례 밖"):
        module.local_path(tmp_path, "../outside.csv")
