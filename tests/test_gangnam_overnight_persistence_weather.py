"""추가 연도의 기상 밴드가 빠진 시간을 무강수나 완전 기온으로 처리하지 않는지 확인한다."""

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
weather = importlib.import_module("gangnam.overnight_persistence_weather_data")


def test_incomplete_weather_band_remains_unknown_and_zero_is_valid():
    data = pd.DataFrame({"station": [401] * 3, "date": ["2025-07-08"] * 3, "hour": [17, 18, 19],
                         "precipitation_1h_mm": [0., 0., np.nan], "temperature_c": [25., 26., 27.]})
    row = weather.daily_bands(data, {"evening": [17, 18, 19]}, [0]).iloc[0]
    assert row.rain_group == "unknown" and pd.isna(row.precipitation_mm)
    assert row.temperature_c == 26.
    data.loc[2, "precipitation_1h_mm"] = 0.
    row = weather.daily_bands(data, {"evening": [17, 18, 19]}, [0]).iloc[0]
    assert row.rain_group == "lt1mm" and row.precipitation_mm == 0.
    row = weather.daily_bands(data.iloc[:2], {"evening": [17, 18, 19]}, [0]).iloc[0]
    assert pd.isna(row.temperature_c) and row.rain_group == "unknown"
