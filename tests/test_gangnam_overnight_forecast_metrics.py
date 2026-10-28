"""동점 확률의 AP·AUC, 주 공동 재표집과 교차 분위수의 실패 처리를 검증한다."""

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
metrics = importlib.import_module("gangnam.overnight_forecast_metrics")


def test_weighted_tied_scores_match_reference_metrics():
    sklearn = pytest.importorskip("sklearn.metrics")
    y = np.array([1, 0, 1, 0, 1, 0])
    p = np.array([.9, .8, .8, .4, .3, .3])
    weights = np.array([[1, 1, 2, 2, 3, 3], [0, 0, 1, 2, 3, 4]])
    result = metrics.weighted_probability_metrics(y, p, weights, .5, [3, 2])
    for i, w in enumerate(weights):
        assert result["average_precision"][i] == pytest.approx(sklearn.average_precision_score(y, p, sample_weight=w))
        assert result["roc_auc"][i] == pytest.approx(sklearn.roc_auc_score(y, p, sample_weight=w))
        assert result["brier"][i] == pytest.approx(sklearn.brier_score_loss(y, p, sample_weight=w))


def test_no_event_draws_remain_undefined_instead_of_perfect():
    result = metrics.weighted_probability_metrics([1, 0], [.8, .2], [[0, 2]], .9, [1])
    assert np.isnan(result["average_precision"][0])
    assert np.isnan(result["roc_auc"][0])
    assert np.isnan(result["recall"][0])
    assert np.isnan(result["precision"][0])
    assert result["false_positive_rate"][0] == 0.


def test_week_blocks_share_codes_across_links_and_use_local_dates():
    timestamps = pd.Series(pd.to_datetime(["2025-05-04 23:00+09:00", "2025-05-04 23:00+09:00", "2025-05-05 00:00+09:00"]))
    codes, names, days = metrics.week_structure(timestamps)
    assert codes.tolist() == [0, 0, 1]
    assert len(names) == 2
    assert days.tolist() == [1, 1]


def test_crossed_intervals_are_not_sorted_into_apparent_coverage():
    frame = pd.DataFrame({"speed_kmh": [5.], "q10": [6.], "q50": [5.], "q90": [4.]})
    losses = metrics.quantile_losses(frame)
    assert losses["coverage"][0] == 0
    assert losses["crossing_fraction"][0] == 1
    assert losses["width"][0] == -2


def test_cluster_bootstrap_retains_counts_and_is_deterministic():
    index = pd.date_range("2025-05-01", periods=30, freq="D", tz="Asia/Seoul")
    frame = pd.DataFrame({"target_start": index, "label": np.arange(30) % 2, "probability": np.where(np.arange(30) % 2, .8, .2)})
    first, info = metrics.probability_bootstrap(frame, .5, draws=25, seed=17)
    second, _ = metrics.probability_bootstrap(frame, .5, draws=25, seed=17)
    assert first == second
    assert info["draws"] == 25
    assert all(x["valid_draws"] + x["invalid_draws"] == 25 for x in first)
    ap = next(x for x in first if x["metric"] == "average_precision")
    assert ap["low"] == ap["high"] == 1.
