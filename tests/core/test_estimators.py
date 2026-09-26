import numpy as np
import pandas as pd
import pytest

from core.adapters import simulate_panel
from core.estimators import apply_abstention, did, event_study, its, placebo_time

KW = dict(y="y", unit="region_id", time="year", group_col="treated", treat_time=2016)
RULES = [
    {"when": "pretrend_rejected", "verdict": "not_identified"},
    {"when": "staggered_adoption", "verdict": "not_identified"},
    {"when": "few_clusters", "verdict": "conditional"},
]


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_did_recovers_true_effect(seed):
    df = simulate_panel(effect=-5.0, seed=seed)
    r = did(df, **KW)
    assert r.ci_low <= -5.0 <= r.ci_high
    assert r.warnings == [] and r.n_clusters == 80


def test_event_study_clean_passes_pretrend():
    r = event_study(simulate_panel(effect=-5.0, seed=3), **KW)
    assert r.assumptions_checked["parallel_pretrends"]["passed"]
    assert r.ci_low <= -5.0 <= r.ci_high
    assert apply_abstention(r, RULES).verdict == "identified"
    assert set(r.extra["coefs"]["rel_time"]) == set(range(-4, 4))


def test_pretrend_violation_triggers_warning_and_abstention():
    df = simulate_panel(effect=0.0, pretrend_slope=1.5, seed=4)
    r = event_study(df, **KW)
    assert r.assumptions_checked["parallel_pretrends"]["p_value"] < 0.1
    assert "pretrend_rejected" in r.triggers
    assert apply_abstention(r, RULES).verdict == "not_identified"
    assert not r.identified
    assert not placebo_time(df, **KW)["passed"]


def test_few_clusters_warning():
    r = did(simulate_panel(n_units=12, n_treated=5, seed=5), **KW)
    assert "few_clusters" in r.triggers
    assert apply_abstention(r, RULES).verdict == "conditional"


def test_staggered_adoption_warning():
    df = simulate_panel(staggered=True, seed=6)
    r = did(
        df, y="y", unit="region_id", time="year", group_col="treated", first_treat_col="first_treat"
    )
    assert "staggered_adoption" in r.triggers
    assert apply_abstention(r, RULES).verdict == "not_identified"


def test_its_recovers_level_change():
    rng = np.random.default_rng(7)
    t = np.arange(48)
    y = 100 + 0.3 * t - 8.0 * (t >= 30) + rng.normal(0, 1, 48)
    r = its(pd.DataFrame({"m": t, "y": y}), "y", "m", treat_time=30)
    assert r.ci_low <= -8.0 <= r.ci_high
    assert any("통제집단" in w for w in r.warnings)
