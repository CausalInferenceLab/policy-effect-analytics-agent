"""부분 관측·월내 속성 전환을 전체 기간 불변으로 오인하지 않는지 검사한다."""

import importlib
import sys
from pathlib import Path

import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
pytest.importorskip("pandas")
mod = importlib.import_module("gangnam.deepening_metadata")
FIELDS = ["거리", "차선수"]


def record(**updates):
    return {"거리": 100, "차선수": 4, "observed_from": "2024-02-01", "observed_to": "2024-02-29", "days": 29, **updates}


def test_incomplete_and_changed_months_are_not_full_invariant_months():
    assert mod.summarize_month([record()], "2024-02", FIELDS)["single_variant_full_month"]
    assert not mod.summarize_month([record(days=28)], "2024-02", FIELDS)["single_variant_full_month"]
    result = mod.summarize_month([record(observed_to="2024-02-14", days=14), record(차선수=5, observed_from="2024-02-15", days=15)], "2024-02", FIELDS)
    assert result["recorded_fraction"] == 1
    assert result["variants"] == 2
    assert not result["single_variant_full_month"]
    assert mod.summarize_month([], "2024-02", FIELDS)["recorded_fraction"] == 0


def test_invalid_metadata_days_and_duplicate_signatures_fail():
    with pytest.raises(ValueError, match="일수"):
        mod.summarize_month([record(days=30)], "2024-02", FIELDS)
    with pytest.raises(ValueError, match="중복"):
        mod.summarize_month([record(days=1), record(days=2)], "2024-02", FIELDS)
    with pytest.raises(ValueError, match="월 밖"):
        mod.summarize_month([record(observed_to="2024-03-01")], "2024-02", FIELDS)
