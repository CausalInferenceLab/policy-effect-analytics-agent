"""저속 구간의 자정·결측·발행 시점과 정답을 보지 않는 재알림 규칙을 검사한다."""

import importlib
import sys
from pathlib import Path

import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")
pytest.importorskip("pyarrow")
mod = importlib.import_module("gangnam.deepening_episode")


def panel(labels, horizon=1):
    dates = pd.date_range("2025-05-01 22:00", periods=len(labels), freq="h", tz="Asia/Seoul")
    return pd.DataFrame(dict(link_id="1", target_start=dates, origin=dates - pd.Timedelta(hours=horizon - 1),
        speed_kmh=10.0, label=labels, probability=.8, saved_prediction=True))


def test_midnight_does_not_split_but_unknown_hour_censors_both_sides():
    frame = panel([0, 1, 1, np.nan, 1, 0, 1])
    catalog, assignments = mod.identify_episodes(frame, "test")
    assert catalog.observed_hours.tolist() == [2, 1, 1]
    assert catalog.left_censored.tolist() == [False, True, False]
    assert catalog.right_censored.tolist() == [True, False, True]
    assert assignments.iloc[1] == assignments.iloc[2]
    assert pd.isna(assignments.iloc[3])
    assert catalog.start.iloc[0].day == 1 and catalog.last_positive.iloc[0].day == 2


def test_advance_credit_uses_origin_not_target_membership_alone():
    frame = panel([0, 1, 1, 1, 0], horizon=3)
    frame["probability"] = [0, 0, .8, .8, 0]
    catalog, frame["episode_id"] = mod.identify_episodes(frame, "test")
    result, alerts, _ = mod.assess(frame, catalog, .5, 0, 1, 1)
    assert alerts["class"].tolist() == ["advance", "at_onset"]
    assert result["advance_recall"] == 1
    assert result["median_first_issue_minus_onset_hours"] == -1
    frame["origin"] = frame.target_start
    result, alerts, _ = mod.assess(frame, catalog, .5, 0, 1, 1)
    assert alerts["class"].tolist() == ["ongoing", "ongoing"]
    assert result["advance_recall"] == result["onset_recall"] == 0


def test_cooldown_uses_last_issue_across_midnight_and_does_not_read_labels():
    frame = panel([0, 1, 0, 1, 1, 0, 1])
    result = mod.notification_mask(frame.drop(columns="label"), .5, 3)
    assert result.tolist() == [True, False, False, True, False, False, True]
    changed = frame.assign(label=1 - frame.label)
    assert result.equals(mod.notification_mask(changed, .5, 3))
    assert mod.notification_mask(frame, 1.1, 3).sum() == 0


def test_missing_saved_predictions_remain_unknown_on_complete_clock():
    frame = panel([0, 1, 1, 0]).drop(columns="saved_prediction")
    frame = frame.iloc[[0, 2, 3]]
    full = mod.complete_panel(frame, ["1"], "2025-05-01 22:00", "2025-05-02 02:00", 1)
    assert len(full) == 4
    assert pd.isna(full.label.iloc[1]) and pd.isna(full.probability.iloc[1])
    catalog, _ = mod.identify_episodes(full, "test")
    assert catalog.left_censored.tolist() == [True]
    with pytest.raises(ValueError, match="시각의 차이"):
        mod.complete_panel(frame, ["1"], "2025-05-01 22:00", "2025-05-02 02:00", 3)


def test_episode_length_filter_does_not_change_point_metrics_or_restore_unknown_start():
    frame = panel([1, 1, 0, 1, 0, 1, 1, 0])
    catalog, frame["episode_id"] = mod.identify_episodes(frame, "test")
    a, _, _ = mod.assess(frame, catalog, .5, 0, 1, 1)
    b, _, _ = mod.assess(frame, catalog, .5, 0, 2, 1)
    assert (a["episodes"], b["episodes"]) == (3, 2)
    assert (a["known_onset_episodes"], b["known_onset_episodes"]) == (2, 1)
    assert a["point_precision"] == b["point_precision"]
    assert b["advance_recall"] == 0


def test_no_positive_episode_keeps_undefined_recall_and_counts_false_alerts():
    frame = panel([0, 0, 0])
    catalog, frame["episode_id"] = mod.identify_episodes(frame, "test")
    measured, alerts, _ = mod.assess(frame, catalog, .5, 0, 1, 1)
    assert measured["episodes"] == measured["true_alerts"] == 0
    assert measured["false_alerts"] == 3
    assert np.isnan(measured["onset_recall"])
    assert alerts["class"].eq("false_point_alert").all()
