"""분위수의 학습기 제한·결측 대체·동점 경보·보정 순위·구간 점수를 검증한다."""

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
methods = importlib.import_module("gangnam.overnight_baseline_methods")


def test_empirical_fallback_and_no_test_training():
    train = pd.DataFrame({"link_id": ["a"] * 4, "weekday": [0, 0, 1, 1], "hour": [17] * 4,
                          "speed_kmh": [10., 20., 30., 40.], "split": ["train"] * 4})
    model = methods.empirical_model(train, minimum=3)
    frame = pd.DataFrame({"link_id": ["a", "unknown"], "weekday": [2, 2], "hour": [17, 19]})
    pred, level = methods.empirical_prediction(model, frame)
    np.testing.assert_allclose(pred, [[13, 25, 37], [13, 25, 37]])
    assert level.tolist() == [1, 3]
    train.loc[0, "split"] = "test"
    with pytest.raises(ValueError, match="학습 기간 밖"):
        methods.empirical_model(train, minimum=3)


def test_weekly_missing_values_use_only_training_fallback():
    train = pd.DataFrame({"link_id": ["a"] * 4, "weekday": [0] * 4, "hour": [17] * 4, "speed_kmh": [10., 20., 30., 40.]})
    model = methods.empirical_model(train, minimum=3)
    frame = pd.DataFrame({"link_id": ["a", "a"], "weekday": [0, 0], "hour": [17, 17],
                          "lag1": [1., np.nan], "lag2": [2., np.nan], "lag3": [3., np.nan], "lag4": [np.nan, np.nan]})
    pred, fallback = methods.weekly_prediction(model, frame, ["lag1", "lag2", "lag3", "lag4"])
    np.testing.assert_allclose(pred, [[1.2, 2, 2.8], [13, 25, 37]])
    assert fallback.tolist() == [False, True]


def test_alert_budget_cannot_split_equal_probabilities():
    y, p = [1, 0, 1, 0], [.8, .8, .4, .2]
    none = methods.budget_threshold(y, p, 1, maximum_alerts=1, maximum_fpr=.5)
    assert none["threshold"] > 1 and none["decision_alerts"] == 0
    tied = methods.budget_threshold(y, p, 1, maximum_alerts=2, maximum_fpr=.5)
    assert tied["threshold"] == .8 and tied["decision_alerts"] == 2


def test_finite_sample_rank_and_nonshrinking_expansion():
    target = np.arange(9, dtype=float)
    prediction = np.zeros((9, 3))
    result = methods.calibration_expansion(target, prediction, .8)
    assert result["rank"] == 8 and result["expansion"] == 7
    broad = np.tile([-100., 0., 100.], (9, 1))
    assert methods.calibration_expansion(target, broad)["expansion"] == 0
    with pytest.raises(ValueError, match="표본"):
        methods.calibration_expansion([0], np.zeros((1, 3)), .8)


def test_interval_score_penalizes_both_misses():
    frame = pd.DataFrame({"speed_kmh": [0., 1.5, 3.], "q10": [1.] * 3, "q50": [1.5] * 3, "q90": [2.] * 3})
    losses = methods.interval_losses(frame)
    np.testing.assert_allclose(losses["interval_score_alpha_0.2"], [11, 1, 11])
    expanded = methods.expand_quantiles(frame[methods.QCOLS].to_numpy(), .5)
    np.testing.assert_allclose(expanded, [[.5, 1.5, 2.5]] * 3)
