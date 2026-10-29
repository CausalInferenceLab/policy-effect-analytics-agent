"""같은 평가 시계와 미관측 정답 보존을 검사한다."""

import importlib
import sys
from pathlib import Path

import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")
pytest.importorskip("joblib")
pytest.importorskip("threadpoolctl")
mod = importlib.import_module("gangnam.deepening_archive_evaluate")


def test_common_model_ready_time_filters_origin_not_target_and_keeps_unknown_target():
    dates = pd.date_range("2025-05-11", periods=24, freq="h", tz="Asia/Seoul")
    frame = pd.DataFrame(dict(link_id="1", target_start=dates, origin=dates - pd.Timedelta(hours=2), speed_kmh=12.))
    frame.loc[3, "speed_kmh"] = np.nan
    cfg = dict(primary_links=["1"], timezone="Asia/Seoul", splits={"summer": ["2025-05-11", "2025-05-11"]},
               evaluation_origin_not_before="2025-05-11T00:00:00+09:00")
    actual = mod.evaluation_rows(frame, cfg, "summer", 3)
    assert len(actual) == 22 and actual.target_start.iloc[0].hour == 2
    assert actual.speed_kmh.isna().sum() == 1
    with pytest.raises(ValueError, match="시간 격자"):
        mod.evaluation_rows(frame.iloc[:-1], cfg, "summer", 3)


def test_metrics_distinguish_predictable_clock_from_observed_actual_values():
    frame = pd.DataFrame(dict(speed_kmh=[10., np.nan], q10=[8., 8.], q50=[11., 11.], q90=[12., 12.], raw_crossing=[0., 0.]))
    measured = mod.metrics(frame)
    assert measured["expected_rows"] == 2
    assert measured["scored_rows"] == 1
    assert measured["missing_target_rows"] == 1 and measured["missing_prediction_rows"] == 0
    assert measured["median_mae"] == 1 and measured["coverage"] == 1
