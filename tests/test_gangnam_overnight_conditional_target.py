"""달력 조건 저속의 학습기 제한·대체 순서·엄격 경계·결측 보존을 검사한다."""

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
module = importlib.import_module("gangnam.overnight_conditional_target")


def configuration():
    return {"threshold_training": ["2023-01-01", "2024-12-31"], "quantile": .2, "quantile_interpolation": "linear",
            "minimum_threshold_observations": 2, "threshold_groups": list(module.LEVELS), "target_name": "label_calendar_q20"}


def training():
    return pd.DataFrame({"link_id": ["a", "a"], "target_start": pd.to_datetime(["2024-01-01 17:00", "2024-01-08 17:00"]),
                         "speed_kmh": [10., 20.], "split": "train"})


def test_hierarchy_strict_threshold_and_missing_outcomes():
    cfg = configuration()
    table = module.fit_thresholds(training(), cfg)
    targets = pd.DataFrame({"link_id": ["a"] * 4, "speed_kmh": [12., 11., 11., np.nan],
                           "target_start": pd.to_datetime(["2025-01-06 17:00", "2025-01-07 17:00", "2025-01-07 18:00", "2025-01-13 17:00"])})
    result = module.attach(targets, table, cfg)
    assert result.calendar_q20_threshold.eq(12.).all()
    assert result.calendar_q20_threshold_level.tolist() == ["link_weekday_hour", "link_hour", "link", "link_weekday_hour"]
    assert result.label_calendar_q20.iloc[:3].tolist() == [0., 1., 1.]
    assert pd.isna(result.label_calendar_q20.iloc[3])
    with pytest.raises(ValueError, match="없는 링크"):
        module.attach(targets.assign(link_id="new"), table, cfg)


def test_future_or_calibration_period_cannot_fit_thresholds():
    cfg = configuration()
    with pytest.raises(ValueError, match="학습 기간"):
        module.fit_thresholds(training().assign(target_start=pd.Timestamp("2025-01-01")), cfg)
    with pytest.raises(ValueError, match="학습 외"):
        module.fit_thresholds(training().assign(split="calibration"), cfg)
