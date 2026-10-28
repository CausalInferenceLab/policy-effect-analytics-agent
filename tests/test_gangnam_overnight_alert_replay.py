"""순차 경보의 미래 독립·상한·재발행 대기·결측 소비·연속 사건 경계를 검사한다."""

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
module = importlib.import_module("gangnam.overnight_alert_replay")


def frame(probabilities, start="2025-05-01 00:00"):
    times = pd.date_range(start, periods=len(probabilities), freq="h", tz="Asia/Seoul")
    return pd.DataFrame({"link_id": "a", "origin": times, "target_start": times,
                         "probability": probabilities, "label": 1., "speed_kmh": 8.})


def policy(cap=None, cooldown=0, consecutive=1):
    return {"daily_cap": cap, "cooldown_hours": cooldown, "consecutive_hours": consecutive}


def test_future_probabilities_and_any_outcomes_do_not_change_past_issuance():
    original = frame([.8] * 12)
    altered = original.copy()
    altered.loc[6:, "probability"] = .1
    altered["label"], altered["speed_kmh"] = 0., 50.
    a, b = [module.replay(f, .5, policy(cooldown=3)) for f in [original, altered]]
    pd.testing.assert_series_equal(a.issued.iloc[:6], b.issued.iloc[:6])
    assert a.issued.tolist() == [True, False, False, True, False, False, True, False, False, True, False, False]


def test_cap_across_links_deterministic_ties_and_date_reset_include_unknown_outcomes():
    data = pd.concat([frame([.8, .8], "2025-05-01 23:00").assign(link_id=k) for k in ["c", "a", "b"]])
    data.loc[data.link_id.eq("a"), ["label", "speed_kmh"]] = np.nan
    result = module.replay(data.sample(frac=1, random_state=17), .5, policy(cap=2))
    assert result[result.issued].link_id.tolist() == ["a", "b", "a", "b"]
    assert result[result.issued].groupby(result.origin.dt.date).size().tolist() == [2, 2]
    assert module.metrics(result)["unknown_alerts"] == 2
    assert module.metrics(result)["precision_known"] == 1.


def test_confirmation_resets_on_gap_or_missing_score_and_suppression_does_not_restart_cooldown():
    data = frame([.8, .8, .8, .8, .8, np.nan, .8, .8])
    result = module.replay(data, .5, policy(cooldown=3, consecutive=2))
    assert result.issued.tolist() == [False, True, False, False, True, False, False, True]
    gap = module.replay(frame([.8] * 4).drop(index=1), .5, policy(consecutive=2))
    assert gap.issued.tolist() == [False, False, True]


def test_missing_outcome_breaks_positive_episode_and_invalid_input_is_rejected():
    data = frame([.8] * 4)
    data.loc[1, ["label", "speed_kmh"]] = np.nan
    event = module.episodes(module.replay(data, .5, policy(cap=2)))
    assert event.observed_hours.tolist() == [1, 2]
    assert event.hit.tolist() == [True, False]
    with pytest.raises(ValueError, match="확률"):
        module.replay(data.assign(probability=1.1), .5, policy())
    with pytest.raises(ValueError, match="중복"):
        module.replay(pd.concat([data, data]), .5, policy())
    with pytest.raises(ValueError, match="Asia/Seoul"):
        module.replay(data.assign(origin=data.origin.dt.tz_convert("UTC")), .5, policy())
