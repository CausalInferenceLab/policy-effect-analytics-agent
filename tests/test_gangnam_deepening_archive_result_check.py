"""독립 예측 점수 검증에서 구간 경계·다른 정답·관측 공백을 검사한다."""

import importlib
import sys
from pathlib import Path

import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")
mod = importlib.import_module("gangnam.deepening_archive_result_check")


def test_interval_boundaries_and_violations_have_distinct_penalties():
    frame = pd.DataFrame(dict(speed_kmh=[2., 4., 1., 6.], q10=2., q50=3., q90=4.))
    actual = mod.loss_table(frame)
    assert actual.coverage.tolist() == [1., 1., 0., 0.]
    assert actual["interval_score_alpha_0.2"].tolist() == [2., 2., 12., 22.]
    bad = frame.copy()
    bad.loc[0, "q50"] = 5.
    with pytest.raises(ValueError, match="정렬되지"):
        mod.loss_table(bad)
    bad = frame.copy()
    bad.loc[0, "speed_kmh"] = np.inf
    with pytest.raises(ValueError, match="유한한"):
        mod.loss_table(bad)


def test_independent_pair_rejects_different_truth_or_missing_clock():
    times = pd.date_range("2025-05-11", periods=15, freq="D", tz="Asia/Seoul")
    frame = pd.DataFrame(dict(link_id="1", target_start=times, origin=times, speed_kmh=3., q10=2., q50=3., q90=4.))
    cfg = dict(week_bootstrap_seed=17, week_bootstrap_draws=20, minimum_weeks_for_interval=8,
        metrics=["median_mae", "coverage"])
    check = mod.independent_pair(frame, frame.iloc[::-1], cfg)
    assert check["median_mae"]["difference"] == check["median_mae"]["low"] == check["median_mae"]["high"] == 0
    assert not check["median_mae"]["quality_pass"]
    with pytest.raises(ValueError, match="표본 불일치"):
        mod.independent_pair(frame, frame.iloc[:-1], cfg)
    bad = frame.copy()
    bad.loc[0, "speed_kmh"] = 4.
    with pytest.raises(AssertionError):
        mod.independent_pair(frame, bad, cfg)
