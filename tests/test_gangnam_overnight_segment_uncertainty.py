"""동일 주 가중치 공유·결측 분모 보존·동시 범위 최대 통계량의 성질을 검사한다."""

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
uncertainty = importlib.import_module("gangnam.overnight_segment_uncertainty")


def test_joint_week_weights_preserve_identical_series_and_missing_denominator():
    dates = pd.date_range("2025-05-05", periods=4, freq="7D").strftime("%Y-%m-%d").tolist()
    data = pd.DataFrame({"date": dates * 2, "group": ["a"] * 4 + ["b"] * 4, "index": [1., 3., np.nan, 5.] * 2})
    actual, draws, support = uncertainty.joint_period_samples(data, {"p": dates}, ["a", "b"], 400, 17, 2)
    np.testing.assert_array_equal(actual["p"], [3., 3.])
    np.testing.assert_array_equal(draws["p"][:, 0], draws["p"][:, 1])
    assert support.valid_days.tolist() == [3, 3]
    assert support.expected_days.tolist() == [4, 4]


def test_maximum_band_keeps_duplicate_contrasts_and_constant_series():
    samples = np.array([[-2., .1], [-1., .2], [0., .3], [1., 4.], [2., -.5]])
    base = uncertainty.simultaneous_band(np.zeros(2), samples, .95)
    duplicated = uncertainty.simultaneous_band(np.zeros(3), np.column_stack([samples, samples[:, 0]]), .95)
    assert duplicated["critical"] == base["critical"]
    centered = np.abs(samples / samples.std(axis=0, ddof=1))
    assert base["critical"] >= np.max(np.quantile(centered, .95, axis=0))
    constant = uncertainty.simultaneous_band(np.array([.2]), np.full((10, 1), .2), .95)
    np.testing.assert_array_equal(constant["lower_log"], [.2])
    np.testing.assert_array_equal(constant["upper_log"], [.2])
