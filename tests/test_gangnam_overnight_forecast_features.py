"""미래 관측 누출·불연속 시간 격자·시험기 링크 재선택을 막는 특징 검증."""

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
features = importlib.import_module("gangnam.overnight_forecast_features")


@pytest.mark.parametrize("horizon", [1, 3])
def test_unavailable_observations_cannot_change_features(horizon):
    cfg = features.read_yaml("overnight_forecast_config.yaml")
    index = pd.date_range("2024-01-01", periods=800, freq="h", tz="Asia/Seoul")
    series = pd.Series(np.arange(800, dtype=float), index=index)
    target = 750
    origin = target - horizon + 1
    changed = series.copy()
    changed.iloc[origin - 1:] = 999999.
    a = features.speed_features(series, horizon, cfg).iloc[target]
    b = features.speed_features(changed, horizon, cfg).iloc[target]
    pd.testing.assert_series_equal(a, b)
    assert a.speed_origin_lag_2 == series.iloc[origin - 2]


def test_missing_hour_cannot_shrink_real_time_lag():
    cfg = features.read_yaml("overnight_forecast_config.yaml")
    series = pd.Series(1., index=pd.date_range("2024-01-01", periods=30, freq="h"))
    series.iloc[27] = np.nan
    assert pd.isna(features.speed_features(series, 1, cfg).iloc[29].speed_origin_lag_2)
    with pytest.raises(ValueError, match="격자"):
        features.speed_features(series.dropna(), 1, cfg)


def test_future_metadata_or_coverage_does_not_reselect_links():
    cfg = features.read_yaml("overnight_forecast_config.yaml")
    cfg["primary_links"] = ["A"]
    cfg["splits"]["train"] = ["2024-12-30", "2024-12-31"]
    index = pd.date_range("2024-12-30", "2025-01-02 23:00", freq="h", tz="Asia/Seoul")
    matrix = pd.DataFrame({"A": 20.}, index=index)
    row = {"링크아이디": "A", "도로명": "강남대로", "시점명": "가", "종점명": "나", "방향": "상행", "거리": 100}
    entries = [{"month": "2024-12", "metadata": [row]}, {"month": "2025-01", "metadata": [{**row, "거리": 200}]}]
    chosen, _ = features.select_links(matrix, entries, cfg)
    altered = matrix.copy()
    altered.loc["2025-01":, "A"] = np.nan
    assert chosen == features.select_links(altered, entries, cfg)[0]
    masked, exclusions = features.mask_changed_metadata(matrix, entries, chosen, cfg)
    assert masked.loc["2024-12", "A"].notna().all()
    assert masked.loc["2025-01", "A"].isna().all()
    assert exclusions[0]["masked_observed_hours"] == 48


def test_feature_sets_exclude_targets_and_timestamps():
    columns = [*features.CALENDAR, "speed_origin_lag_2", "speed_weekly_lag_168", "speed_kmh",
               "label_10", "label_q20", "target_start", "origin", "split", "bus_north_trips"]
    sets = features.feature_sets(pd.DataFrame(columns=columns))
    for selected in sets.values():
        assert not set(selected) & {"speed_kmh", "label_10", "label_q20", "target_start", "origin", "split"}
    assert "bus_north_trips" not in sets["recent_road_assumption"]
    assert "bus_north_trips" in sets["delayed_bus_ablation"]
