"""오차 보정의 미래 누출·공개 지연 경계·표본 부족 대체와 구간 확장을 검사한다."""

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
module = importlib.import_module("gangnam.overnight_interval_methods")


def frame(start, count):
    target = pd.date_range(start, periods=count, freq="h")
    return pd.DataFrame({"link_id": "a", "target_start": target, "origin": target,
                         "speed_kmh": 10., "q10": 9., "q50": 10., "q90": 11.})


def test_future_and_not_yet_released_targets_cannot_change_earlier_intervals():
    static = frame("2025-03-01", 80)
    warmup = frame("2025-04-01", 80)
    target = frame("2025-05-01", 100)
    cfg = {"minimum_group_scores": 4, "target_coverage": .8, "rolling_days": 28}
    variant = {"mode": "rolling", "grouping": "global", "delay_hours": 24}
    first = module.adjust(target, static, warmup, cfg, variant)
    altered = target.copy()
    altered.loc[altered.index >= 50, "speed_kmh"] = 1000.
    second = module.adjust(altered, static, warmup, cfg, variant)
    # 50번째 실제값은 74번째 원점에서야 공개된다.
    np.testing.assert_array_equal(first.expansion.iloc[:74], second.expansion.iloc[:74])
    assert second.expansion.iloc[-1] > first.expansion.iloc[-1]
    assert (second.latest_label_available_at <= second.origin).all()


def test_release_boundary_is_inclusive_and_group_fallback_is_recorded():
    static = frame("2025-03-01", 80)
    warmup = frame("2025-04-28", 80)
    target = frame("2025-05-02", 2).assign(link_id="b")
    cfg = {"minimum_group_scores": 4, "target_coverage": .8, "rolling_days": 28}
    result = module.adjust(target, static, warmup, cfg, {"mode": "rolling", "grouping": "link_band", "delay_hours": 24})
    assert result.calibration_source.eq("rolling_global").all()
    assert result.calibration_scores.tolist() == [73, 74]
    assert result.latest_label_available_at.equals(result.origin)


def test_finite_rank_expansion_does_not_shrink_and_rejects_crossing():
    assert module.expansion([-2., -1., 0., 1.], .8) == 1.
    assert module.expansion([-5., -4., -3., -2., -1.], .8) == 0.
    with pytest.raises(ValueError, match="부족"):
        module.expansion([1.], .8)
    with pytest.raises(ValueError, match="교차"):
        module.scores(frame("2025-03-01", 3).assign(q10=20.))
    with pytest.raises(ValueError, match="공개"):
        module.adjust(frame("2025-03-01", 10), frame("2025-04-01", 10), frame("2025-02-01", 10),
                      {"minimum_group_scores": 4, "target_coverage": .8, "rolling_days": 28},
                      {"mode": "static", "grouping": "global", "delay_hours": 2})


def test_explicit_seoul_timezone_preserves_hour_groups_and_release_boundary():
    static, warmup, target = frame("2025-03-01", 80), frame("2025-04-28", 80), frame("2025-05-02", 2)
    cfg = {"minimum_group_scores": 4, "target_coverage": .8, "rolling_days": 28}
    variant = {"mode": "rolling", "grouping": "link_band", "delay_hours": 24}
    plain = module.adjust(target, static, warmup, cfg, variant)
    for part in [static, warmup, target]:
        for key in ["target_start", "origin"]:
            part[key] = part[key].dt.tz_localize("Asia/Seoul")
    aware = module.adjust(target, static, warmup, cfg, variant)
    np.testing.assert_array_equal(plain.expansion, aware.expansion)
    np.testing.assert_array_equal(plain.calibration_scores, aware.calibration_scores)
    assert str(aware.latest_label_available_at.dt.tz) == "Asia/Seoul"
    assert (aware.latest_label_available_at <= aware.origin).all()
