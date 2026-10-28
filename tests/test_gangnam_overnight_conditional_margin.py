"""속도 차이 점수의 미래 실제값 독립성과 개발 기간·분위수 검증을 검사한다."""

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
margin = importlib.import_module("gangnam.overnight_conditional_margin")


def test_margin_uses_prediction_and_threshold_without_future_actual():
    data = pd.DataFrame({"q10": [0., 10.], "q50": [10., 10.], "q90": [20., 10.],
                         "calendar_q20_threshold": [12., 12.], "speed_kmh": [1., 100.]})
    scores, floored = margin.margin_scores(data, .1)
    np.testing.assert_allclose(scores["median_gap"], [2., 2.])
    np.testing.assert_allclose(scores["scaled_median_gap"], [.1, 20.])
    assert floored == 1
    changed = data.assign(speed_kmh=[900., np.nan], label=[0, 1])
    after, _ = margin.margin_scores(changed, .1)
    np.testing.assert_array_equal(after["scaled_median_gap"], scores["scaled_median_gap"])
    with pytest.raises(ValueError, match="교차"):
        margin.margin_scores(data.assign(q10=[11., 10.]), .1)
    with pytest.raises(ValueError, match="유한"):
        margin.margin_scores(data.assign(q50=np.nan), .1)


def test_warmup_rejects_test_rows_even_if_other_months_are_valid():
    base = {"splits": {"calibration": ["2025-03-01", "2025-03-31"], "decision": ["2025-04-01", "2025-04-30"]}}
    dates = pd.to_datetime(["2025-03-01", "2025-04-30", "2025-05-01"]).tz_localize("Asia/Seoul")
    frame = pd.DataFrame({"target_start": dates})
    assert len(margin.warmup_parts(frame.iloc[:2], base)["decision"]) == 1
    with pytest.raises(ValueError, match="3월·4월"):
        margin.warmup_parts(frame, base)
