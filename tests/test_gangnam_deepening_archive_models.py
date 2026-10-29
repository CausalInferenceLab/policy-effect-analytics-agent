"""월별 파일 모형의 개발 분할과 정답을 쓰지 않는 분위수 처리를 검사한다."""

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
mod = importlib.import_module("gangnam.deepening_archive_models")


def test_development_date_must_match_split_name_and_target_must_be_finite():
    cfg = dict(primary_links=["1"], splits={"train": ["2023-01-01", "2024-12-31"], "tuning": ["2025-01-01", "2025-02-28"]})
    frame = pd.DataFrame(dict(link_id=["1", "1"], target_start=pd.to_datetime(["2024-01-01", "2025-01-01"], utc=True),
                              split=["train", "tuning"], speed_kmh=[10., 11.]))
    train, tune = mod.development_parts(frame, cfg)
    assert len(train) == len(tune) == 1
    frame.loc[1, "target_start"] = pd.Timestamp("2025-05-01", tz="UTC")
    with pytest.raises(ValueError, match="분할·날짜"):
        mod.development_parts(frame, cfg)


def test_quantile_rearrangement_is_independent_of_targets_and_reports_crossing():
    q = np.array([[9., 4., 7.], [2., 4., 8.]])
    ordered, crossing = mod.ordered_predictions(q)
    np.testing.assert_array_equal(ordered, [[4., 7., 9.], [2., 4., 8.]])
    assert crossing.tolist() == [True, False]
    np.testing.assert_array_equal(q[0], [9., 4., 7.])
    with pytest.raises(ValueError, match="유한"):
        mod.ordered_predictions([[1., np.nan, 3.]])
