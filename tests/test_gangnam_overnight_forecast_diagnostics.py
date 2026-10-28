"""짝 비교 표본 불일치·동일 예측 차이·관측 공백과 확률 구간의 보존을 검증한다."""

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
diagnostics = importlib.import_module("gangnam.overnight_forecast_diagnostics")


def example():
    return pd.DataFrame({"link_id": ["a"] * 20, "target_start": pd.date_range("2025-05-01", periods=20, tz="Asia/Seoul"),
                         "label": np.arange(20) % 2, "speed_kmh": np.where(np.arange(20) % 2, 8., 15.),
                         "probability": np.where(np.arange(20) % 2, .8, .2)})


def test_pairing_rejects_missing_rows_and_changed_labels():
    left = example()
    with pytest.raises(ValueError, match="표본 또는 목표"):
        diagnostics.align_predictions(left, left.iloc[:-1])
    right = left.copy()
    right.loc[0, "label"] = 1
    with pytest.raises(ValueError, match="표본 또는 목표"):
        diagnostics.align_predictions(left, right)


def test_identical_predictions_have_zero_paired_difference_despite_order():
    left = example()
    result = diagnostics.paired_comparison(left, left.iloc[::-1], .5, .5, draws=25)
    assert all(x["difference"] == x["low"] == x["high"] == 0 for x in result)


def test_positive_episodes_do_not_bridge_missing_hour_or_link():
    frame = pd.DataFrame({"link_id": ["a", "a", "a", "b"], "label": [1] * 4, "speed_kmh": [8, 7, 6, 5],
        "target_start": pd.to_datetime(["2025-05-01 01:00+09:00", "2025-05-01 02:00+09:00", "2025-05-01 04:00+09:00", "2025-05-01 05:00+09:00"])})
    result = diagnostics.positive_episodes(frame)
    assert result.observed_hours.tolist() == [2, 1, 1]
    assert result.minimum_speed.tolist() == [7, 6, 5]


def test_probability_bins_include_zero_one_and_keep_empty_bins():
    result = diagnostics.reliability(pd.DataFrame({"label": [0, 1], "probability": [0., 1.]}))
    assert result.rows.sum() == 2
    assert result.events.sum() == 1
    assert result.observed_rate.isna().sum() == len(result) - 2
