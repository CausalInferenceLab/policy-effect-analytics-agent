"""학습기 대체값·표본 선택 독립성·거짓 경보 제한과 모델 실행을 검증한다."""

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
models = importlib.import_module("gangnam.overnight_forecast_models")


def test_imputation_never_uses_later_values_and_marks_all_missing():
    train = pd.DataFrame({"link_id": ["A"] * 3, "speed_lag": [1., 3., np.nan], "bus_lag": [np.nan] * 3})
    schema = models.fit_schema(train, list(train))
    later = pd.DataFrame({"link_id": ["A", "A"], "speed_lag": [np.nan, 10000.], "bus_lag": [np.nan, 500.]})
    result = models.transform(later, schema)
    assert result.loc[0, "speed_lag"] == 2.
    assert result.loc[0, "speed_lag__missing"] == 1
    assert result.loc[0, "bus_lag"] == 0.
    assert result.loc[0, "bus_lag__missing"] == 1
    assert schema["all_missing_training_columns"] == ["bus_lag"]


def test_uniform_sample_does_not_depend_on_labels():
    frame = pd.DataFrame({"link_id": ["A"] * 100 + ["B"] * 100, "label_10": [0] * 190 + [1] * 10})
    first = models.uniform_sample(frame, 20, 17)
    frame["label_10"] = 1 - frame.label_10
    second = models.uniform_sample(frame, 20, 17)
    assert first.index.equals(second.index)
    assert first.groupby("link_id").size().to_dict() == {"A": 20, "B": 20}


def test_threshold_respects_fpr_and_does_not_split_tied_scores():
    pytest.importorskip("sklearn")
    labels = np.array([1, 1, 0, 0, 0, 0])
    probability = np.array([.9, .8, .8, .7, .6, .5])
    result = models.choose_threshold(labels, probability, .1)
    alerts = probability >= result["threshold"]
    assert (alerts[labels == 0]).mean() <= .1
    assert (alerts[labels == 1]).mean() == .5
    assert result["threshold"] == .9


def test_no_positive_recall_can_choose_no_alert_threshold():
    pytest.importorskip("sklearn")
    result = models.choose_threshold([1, 0], [.1, .9], 0.)
    assert result["threshold"] > 1
    assert result["decision_recall"] == 0


def test_seasonal_unseen_group_uses_training_link_prior():
    train = pd.DataFrame({"link_id": ["A"] * 4, "weekday": [0] * 4, "hour": [1] * 4, "label_10": [0, 0, 0, 1]})
    model = models.fit_seasonal(train, "label_10", 20)
    later = pd.DataFrame({"link_id": ["A"], "weekday": [6], "hour": [23]})
    assert models.seasonal_probability(model, later)[0] == .25
