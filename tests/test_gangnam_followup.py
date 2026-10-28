"""후속 탐색의 중복 격리·사전 표본 선택·관측률 관문·도로 가중치를 검증한다."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))

from gangnam.followup import (  # noqa: E402
    bootstrap_change,
    clean_duplicates,
    fixed_index,
    road_daily,
    summarize_daily,
)


def test_conflicting_duplicates_are_quarantined_not_averaged():
    d = pd.DataFrame({"key": ["a", "a", "b", "b", "c"], "value": [3, 3, 4, 40, np.nan]})
    clean, audit = clean_duplicates(d, ["key"])
    assert clean.key.tolist() == ["a", "c"]
    assert audit == {"identical_removed": 1, "conflicting_rows_quarantined": 2, "conflicting_keys": 1}
    with pytest.raises(ValueError, match="결측"):
        clean_duplicates(pd.DataFrame({"key": [None], "value": [1]}), ["key"])


def test_post_values_and_new_routes_cannot_choose_pre_cohort():
    d = pd.DataFrame({"date": ["a", "b", "c", "d", "c", "d"],
                      "route": ["old"] * 4 + ["new"] * 2, "value": [10, 10, 5, 5, 1000, 1000]})
    daily, chosen = fixed_index(d, ["a", "b"], ["c", "d"], ["route"])
    assert chosen.route.tolist() == ["old"]
    assert daily["index"].tolist() == [100, 100, 50, 50]
    changed = d.copy()
    changed.loc[changed.date.isin(["c", "d"]), "value"] *= 100
    _, again = fixed_index(changed, ["a", "b"], ["c", "d"], ["route"])
    pd.testing.assert_frame_equal(chosen, again)


def test_unitless_index_is_invariant_to_fixed_units():
    d = pd.DataFrame({"date": ["a", "b", "c"], "route": ["r"] * 3, "value": [10., 20., 30.]})
    a, _ = fixed_index(d, ["a", "b"], ["c"], ["route"])
    b, _ = fixed_index(d.assign(value=d.value * 60), ["a", "b"], ["c"], ["route"])
    pd.testing.assert_frame_equal(a, b)


def test_missing_post_service_is_not_zero_travel_time():
    d = pd.DataFrame({"date": ["a", "b", "c", "a", "b"], "route": ["x"] * 3 + ["y"] * 2,
                      "value": [10, 10, 10, 20, 20]})
    daily, chosen = fixed_index(d, ["a", "b"], ["c"], ["route"])
    assert len(chosen) == 2
    assert daily.loc[daily.date.eq("c"), "coverage"].item() == .5
    assert np.isnan(daily.loc[daily.date.eq("c"), "index"].item())


def test_repeated_segment_must_be_resolved_before_index():
    d = pd.DataFrame({"date": ["a", "a"], "route": ["x", "x"], "value": [5, 6]})
    with pytest.raises(ValueError, match="중복"):
        fixed_index(d, ["a"], ["b"], ["route"])


def test_common_recording_is_explicit_survivor_sensitivity():
    d = pd.DataFrame({"date": ["a", "b", "c", "a", "b"], "route": ["x"] * 3 + ["y"] * 2,
                      "value": [10, 10, 5, 20, 20]})
    _, original = fixed_index(d, ["a", "b"], ["c"], ["route"])
    daily, survivor = fixed_index(d, ["a", "b"], ["c"], ["route"], common_coverage=True)
    assert len(original) == 2 and survivor.route.tolist() == ["x"]
    assert daily.loc[daily.date.eq("c"), "index"].item() == 50


def test_quality_gate_rejects_different_coverage_despite_many_days():
    cfg = {"minimum_common_days": 2, "maximum_coverage_gap": .1, "bootstrap": {"seed": 7, "draws": 100}}
    d = pd.DataFrame({"date": ["a", "b", "c", "d"], "index": [100, 100, 50, 50], "coverage": [1, 1, .8, .8]})
    result = summarize_daily(d, ["a", "b"], ["c", "d"], cfg)
    assert not result["quality_pass"]
    assert result["change"] == -50


def test_road_weights_are_fixed_by_length_and_pre_availability():
    d = pd.DataFrame({"date": ["a", "a", "b", "b", "b"], "link_id": ["x", "y", "x", "y", "new"],
                      "hour": [17] * 5, "speed_kmh": [10, 20, 10, 30, 1000], "length": [1, 3, 1, 3, 100]})
    daily, links = road_daily(d, ["a"], ["b"], {"minimum_coverage": .8})
    assert links == 2
    assert daily["index"].tolist() == [17.5, 25]
    assert daily.coverage.tolist() == [1, 1]


def test_bootstrap_is_reproducible_and_handles_empty_series():
    a = bootstrap_change([10, 20, 30], [15, 25, 35], seed=41, draws=500)
    assert a == bootstrap_change([10, 20, 30], [15, 25, 35], seed=41, draws=500)
    assert a[0] < 5 < a[1]
    assert bootstrap_change([], [1, 2]) == [None, None]
