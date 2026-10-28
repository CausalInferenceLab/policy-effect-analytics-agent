"""기상 결측을 공통 표본 보존율의 분모에서 숨기지 않는지 검사한다."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))

from gangnam.overnight_weather_analysis import comparison  # noqa: E402


def test_weather_missing_days_remain_in_retention_denominator():
    dates = pd.date_range("2024-01-01", periods=60).strftime("%Y-%m-%d").tolist()
    d = pd.DataFrame({"date": dates, "index": [100.] * 30 + [110.] * 30,
                      "rain": ["lt1mm"] * 20 + [np.nan] * 10 + ["lt1mm"] * 30})
    cfg = {"minimum_days_per_stratum": 2, "minimum_common_days": 20, "minimum_retained_fraction": .8}
    result, _ = comparison(d, dates[:30], dates[30:], ["rain"], cfg)
    assert result["before_total"] == 20
    assert result["before_used"] == 20
    assert result["before_bus_valid_days"] == 30
    assert result["before_retained_of_bus"] == pytest.approx(2 / 3)
    assert not result["support_pass"]


def test_one_sided_rain_stratum_is_excluded_and_reported():
    dates = pd.date_range("2024-01-01", periods=60).strftime("%Y-%m-%d").tolist()
    d = pd.DataFrame({"date": dates, "index": [100.] * 30 + [110.] * 30,
                      "rain": ["lt1mm"] * 30 + ["lt1mm"] * 24 + ["ge1mm"] * 6})
    cfg = {"minimum_days_per_stratum": 2, "minimum_common_days": 20, "minimum_retained_fraction": .8}
    result, strata = comparison(d, dates[:30], dates[30:], ["rain"], cfg)
    assert result["after_used"] == 24
    assert result["support_pass"]
    assert strata.rain.tolist() == ["lt1mm"]
    assert result["change_pct"] == pytest.approx(10.)
