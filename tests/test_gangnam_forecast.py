"""공개 지연·누수·공정한 예측 비교와 작은 CPU 학습을 검증한다."""

import copy
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

CASE = Path(
    os.environ.get(
        "GANGNAM_CASE", Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
    )
)
sys.path.insert(0, str(CASE))
import forecast as model  # noqa: E402
from _shared import config  # noqa: E402


def test_release_boundary_is_based_on_origin_not_target():
    targets = pd.date_range("2025-03-11 00:00", periods=4, freq="h", tz="Asia/Seoul")
    releases = pd.Series([targets[0]], index=["2025-01"])
    clock, choices, _ = model.publication_clock(targets, 3, releases, [1, 3])
    assert clock.publication_cursor.tolist() == [0, 0, 1, 1]
    assert choices[(0, 1)] == () and choices[(1, 3)] == ("2025-01",)


def test_archive_lags_hide_unreleased_values():
    index = pd.date_range("2025-01-01", periods=24 * 80, freq="h", tz="Asia/Seoul")
    series = pd.Series(20.0, index=index)
    targets = pd.DatetimeIndex(["2025-03-10 23:00", "2025-03-11 00:00"], tz="Asia/Seoul")
    releases = pd.Series([pd.Timestamp("2025-03-11", tz="Asia/Seoul")], index=["2025-01"])
    values, available = model.lag_values(series, targets, 1, 24 * 56, releases)
    assert np.isnan(values[0]) and values[1] == 20 and available.tolist() == [0, 1]
    with pytest.raises(ValueError, match="발행 시각"):
        model.lag_values(series, targets, 3, 1, releases)


def test_imputation_is_trained_without_tuning_values():
    train = pd.DataFrame(dict(link_id=["a", "a"], value=[2.0, 4.0], empty=[np.nan, np.nan]))
    schema = model.fit_schema(train, ["link_id", "value", "empty"])
    evaluation = pd.DataFrame(dict(link_id=["a"], value=[np.nan], empty=[1000.0]))
    result = model.transform(evaluation, schema)
    assert result.value.iloc[0] == 3 and result.value__missing.iloc[0] == 1
    assert schema["medians"]["empty"] == 0 and schema["all_missing_training_columns"] == ["empty"]


def test_prediction_pairing_requires_same_observations():
    data = pd.DataFrame(
        dict(
            link_id=["a", "b"],
            target_start=pd.date_range("2025-01-01", periods=2, tz="Asia/Seoul"),
            speed_kmh=[10.0, 20.0],
            label=[0, 0],
            q10=[5.0, 15.0],
            q50=[10.0, 20.0],
            q90=[15.0, 25.0],
        )
    )
    assert len(model.align_predictions(data, data.iloc[::-1])) == 2
    wrong = data.copy()
    wrong.loc[0, "speed_kmh"] = 11
    with pytest.raises(ValueError, match="관측 속도"):
        model.align_predictions(data, wrong)
    with pytest.raises(ValueError, match="중복"):
        model.align_predictions(pd.concat([data, data]), data)


def test_interval_score_penalizes_narrow_misses():
    frame = pd.DataFrame(
        dict(speed_kmh=[5.0, 15.0], q10=[0.0, 0.0], q50=[5.0, 5.0], q90=[10.0, 10.0])
    )
    losses = model.interval_losses(frame)
    assert losses["interval_score_alpha_0.2"].tolist() == [10.0, 60.0]
    assert losses["coverage"].tolist() == [1.0, 0.0]
    assert losses["median_mae"].tolist() == [0.0, 10.0]


def test_uniform_sampling_keeps_per_link_budget_and_seed():
    frame = pd.DataFrame(dict(link_id=["a"] * 10 + ["b"] * 3, speed_kmh=np.arange(13)))
    first = model.uniform_sample(frame, 5, 17)
    pd.testing.assert_frame_equal(first, model.uniform_sample(frame, 5, 17))
    assert first.groupby("link_id").size().to_dict() == {"a": 5, "b": 3}


def test_cpu_quantile_training_smoke():
    pytest.importorskip("catboost")
    cfg = copy.deepcopy(config()["forecast"])
    cfg["training"]["maximum_rows_per_link"] = 60
    cfg["models"]["catboost_quantile"].update(iterations=12, depth=2, early_stopping_rounds=4)
    hours = pd.date_range("2023-01-01", periods=240, freq="h", tz="Asia/Seoul")
    frame = pd.DataFrame(
        dict(
            link_id="a",
            hour=hours.hour,
            weekday=hours.dayofweek,
            month=hours.month,
            weekend=(hours.dayofweek >= 5).astype(int),
            korean_public_holiday=0,
            speed_kmh=20 + np.sin(np.arange(240) / 24),
        )
    )
    fitted = model.fit_quantile(2, frame.iloc[:180], frame.iloc[180:], model.CALENDAR, cfg, 17)
    q, crossing = model.ordered_predictions(model.predict_quantiles(fitted, frame.iloc[180:], 2))
    assert fitted["training_rows"] == 60 and 1 <= fitted["iterations"] <= 12
    assert q.shape == (60, 3) and np.isfinite(q).all() and (np.diff(q, axis=1) >= 0).all()
    assert crossing.shape == (60,)
