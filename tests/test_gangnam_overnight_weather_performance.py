"""기상 결측과 시간대 오류가 예측 표본 또는 건조 집단에 섞이지 않는지 검사한다."""

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
weather = importlib.import_module("gangnam.overnight_weather_performance")


def test_weather_join_keeps_missing_and_exact_zero_distinct():
    timestamps = pd.date_range("2025-05-01", periods=3, freq="h", tz="Asia/Seoul")
    forecasts = pd.DataFrame({"target_start": timestamps, "speed_kmh": [10., 15., 20.]})
    met = pd.DataFrame({"station": [401, 401], "datetime_local": ["2025-05-01 00:00:00", "2025-05-01 01:00:00"],
                        "temperature_c": [30., np.nan], "precipitation_1h_mm": [0., .5]})
    result = weather.join_weather(forecasts, met, 401, 30)
    assert len(result) == 3
    assert result.rain_group.tolist() == ["dry", "wet", "unknown"]
    assert result.heat_group.tolist() == ["at_least_30", "unknown", "unknown"]
    np.testing.assert_array_equal(result.speed_kmh, forecasts.speed_kmh)


def test_weather_join_rejects_duplicate_time_and_ambiguous_zone():
    frame = pd.DataFrame({"target_start": pd.date_range("2025-05-01", periods=1, tz="Asia/Seoul")})
    met = pd.DataFrame({"station": [401, 401], "datetime_local": ["2025-05-01"] * 2,
                        "temperature_c": [20., 21.], "precipitation_1h_mm": [0., 0.]})
    with pytest.raises(ValueError, match="중복"):
        weather.join_weather(frame, met, 401, 30)
    with pytest.raises(ValueError, match="Asia/Seoul"):
        weather.join_weather(frame.assign(target_start=frame.target_start.dt.tz_convert("UTC")), met.iloc[:1], 401, 30)
    with pytest.raises(ValueError, match="음수"):
        weather.weather_groups(met.assign(precipitation_1h_mm=-1.), 30)
