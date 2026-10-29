"""전환 회귀의 날짜 중심화·동일 관측 표본·자료 품질 문턱을 검사한다."""

import importlib
import sys
from pathlib import Path

import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")
mod = importlib.import_module("gangnam.deepening_transition")


def configuration():
    return dict(specifications=["weekday_level", "weekday_trend_level", "weekday_trend_level_slope"],
        minimum_observed_days_each_side=20, minimum_observed_fraction=.8)


def frame():
    dates = pd.bdate_range("2024-05-20", "2024-08-16")
    days = (dates - pd.Timestamp("2024-06-29")).days.to_numpy()
    values = 20 + .03 * days - 4 * (days >= 0) + .1 * np.maximum(days, 0) + .2 * dates.dayofweek.to_numpy()
    return pd.DataFrame(dict(date=dates.strftime("%Y-%m-%d"), index=values))


def test_centered_post_time_recovers_level_and_slope_at_event():
    result, predictions = mod.fit_description(frame(), "2024-06-29", "weekday_trend_level_slope", configuration())
    assert result["quality_pass"]
    assert result["level_kmh"] == pytest.approx(-4)
    assert result["pre_slope_kmh_per_day"] == pytest.approx(.03)
    assert result["slope_change_kmh_per_day"] == pytest.approx(.1)
    assert result["day30_shift_kmh"] == pytest.approx(-1)
    assert np.abs(predictions.residual).max() < 1e-10


def test_missing_weather_does_not_shrink_retention_denominator():
    full = frame()
    complete = full[full.date.ge("2024-06-20")].copy()
    result, _ = mod.fit_description(complete, "2024-06-29", "weekday_trend_level", configuration(), denominator=full)
    assert not result["quality_pass"]
    assert result["retained_before"] < .3
    with pytest.raises(ValueError, match="날짜 중복"):
        mod.fit_description(pd.concat([full, full.iloc[:1]]), "2024-06-29", "weekday_level", configuration())


def test_locked_year_or_changed_event_is_rejected():
    cfg = dict(years=[2023, 2024, 2025], locked_year=2026, start_month_day="05-20", event_month_day="06-29", end_month_day="08-16")
    mod.validate(cfg)
    with pytest.raises(ValueError, match="잠금"):
        mod.validate({**cfg, "years": [2024, 2025, 2026]})
    with pytest.raises(ValueError, match="고정 전환"):
        mod.validate({**cfg, "event_month_day": "07-15"})
