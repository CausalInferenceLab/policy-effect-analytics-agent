"""요금 시점 민감도가 사전 창과 기존 설정을 변경하지 않는지 검증한다."""

import importlib
import sys
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
fare = importlib.import_module("gangnam.overnight_fare_trim")


def test_trim_retains_pre_periods_and_does_not_mutate(monkeypatch):
    base = {"periods": {"pre2023": ["2023-05-20", "2023-06-28"], "post2023": ["2023-07-08", "2023-08-16"],
                        "pre2024": ["2024-05-20", "2024-06-28"], "post2024": ["2024-07-08", "2024-08-16"]}}
    original = deepcopy(base)
    def dates(cfg, source):
        return {k: [str(d.date()) for d in pd.date_range(a, b) if str(d.date()) in source]
                for k, (a, b) in cfg["periods"].items()}
    monkeypatch.setattr(fare, "period_dates", dates)
    source = {str(d.date()) for d in pd.date_range("2023-01-01", "2024-12-31")} - {"2023-08-10"}
    result = fare.trim_periods(base, {"post2023_end": "2023-08-11", "post2024_end": "2024-08-11"}, source)
    assert base == original
    assert result["pre2023"] == dates(base, source)["pre2023"]
    assert result["pre2024"] == dates(base, source)["pre2024"]
    assert result["post2023"][-1] == "2023-08-11"
    assert "2023-08-10" not in result["post2023"]
    with pytest.raises(ValueError, match="줄이는 범위"):
        fare.trim_periods(base, {"post2023_end": "2023-08-17", "post2024_end": "2024-08-11"}, source)
