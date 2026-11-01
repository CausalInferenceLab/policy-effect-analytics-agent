"""민감도 분석에서 표본·날짜 경계·검정 한계가 유지되는지 확인한다."""

from __future__ import annotations

import importlib.util
import json
import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from core.schema.plan import load_plan

HERE = Path(__file__).resolve().parent


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetch = load_module("sensitivity_fetch", HERE / "fetch.py")
with patch.dict(sys.modules, {"fetch": fetch}):
    sensitivity = load_module("case_sensitivity", HERE / "sensitivity.py")


def fixture():
    stamps = [
        "2019-06-23 06:00",
        "2019-06-23 23:00",
        "2019-12-10 06:00",
        "2019-12-10 23:00",
        "2020-01-19 23:00",
        "2020-01-20 00:00",
        "2020-01-31 23:00",
        "2020-02-01 00:00",
        "2021-01-01 06:00",
        "2021-01-01 23:00",
    ]
    rows = []
    for code in sorted(fetch.TREATED | set(fetch.CONTROL_STATIONS)):
        for stamp in stamps:
            when = pd.Timestamp(stamp, tz="Asia/Seoul")
            rows.append(
                {
                    "station_id": code,
                    "datetime": when,
                    "hour_idx": int((when - fetch.ORIGIN) / pd.Timedelta(hours=1)),
                    "hour": when.hour,
                    "treated": int(code in fetch.TREATED),
                    "no2": 0.02,
                }
            )
    return pd.DataFrame(rows)


class SensitivityTests(unittest.TestCase):
    def test_core_controls_keep_identical_times_and_treated_sites(self):
        full = fixture()
        sample = sensitivity.select_scenario(full, "core_controls")
        self.assertEqual(
            set(sample.station_id), fetch.TREATED | set(fetch.SENSITIVITY_CONTROL_STATIONS)
        )
        self.assertEqual(set(sample.hour_idx), set(full.hour_idx))
        self.assertEqual(set(sample.loc[sample.treated.eq(1), "station_id"]), fetch.TREATED)
        self.assertTrue(sample.groupby("hour_idx").station_id.nunique().eq(6).all())

    def test_cutoff_dates_include_last_hour_and_preserve_pre_period(self):
        full = fixture()
        pre = set(full.loc[full.hour_idx.lt(25542), "hour_idx"])
        for key, last in [
            ("post_to_20200119", "2020-01-19 23:00"),
            ("post_to_20200131", "2020-01-31 23:00"),
        ]:
            with self.subTest(key=key):
                sample = sensitivity.select_scenario(full, key)
                self.assertEqual(sample.datetime.max(), pd.Timestamp(last, tz="Asia/Seoul"))
                self.assertEqual(set(sample.loc[sample.hour_idx.lt(25542), "hour_idx"]), pre)
                pd.testing.assert_series_equal(sample.hour_idx, full.loc[sample.index, "hour_idx"])

    def test_excluding_2020_keeps_2019_and_2021_without_reindexing(self):
        full = fixture()
        sample = sensitivity.select_scenario(full, "exclude_2020")
        self.assertEqual(set(sample.datetime.dt.year), {2019, 2021})
        pd.testing.assert_series_equal(sample.hour_idx, full.loc[sample.index, "hour_idx"])

    def test_validation_requires_same_times_not_just_equal_row_counts(self):
        full = fixture()
        plan = load_plan(HERE / "plan.yaml")
        stations = fetch.TREATED | set(fetch.CONTROL_STATIONS)
        sensitivity.validate_sample(full, plan, stations)
        broken = full.copy()
        broken.loc[broken.index[0], "hour_idx"] = 100  # 행 수가 같아도 관측시점 집합이 다르다.
        with self.assertRaisesRegex(ValueError, "공통 관측시간"):
            sensitivity.validate_sample(broken, plan, stations)
        missing = full.copy()
        missing.loc[missing.index[0], "no2"] = float("nan")
        with self.assertRaisesRegex(ValueError, "공통 관측시간"):
            sensitivity.validate_sample(missing, plan, stations)

    def test_six_assignments_are_not_reported_as_resolvable_tests(self):
        result = {
            "estimate": -0.001,
            "ci_low": -math.inf,
            "ci_high": math.inf,
            "p_value": 1.0,
            "n_obs": 100,
            "n_clusters": 6,
            "verdict": "conditional",
            "assumptions_checked": {
                "ri_assignments": 6,
                "parallel_pretrends": {"p_value": 1.0},
                "placebo_time": {"p_value": 1.0},
                "placebo_window": {"p_value": 1.0},
            },
            "extra": {"coefs": [{"rel_time": -23}, {"rel_time": 1}, {"rel_time": 12}]},
        }
        summary = sensitivity.summarise("core_controls", "핵심 4곳", result, 0.05, 0.10)
        self.assertEqual(summary["ci_kind"], "unbounded")
        self.assertFalse(summary["effect_test_resolvable"])
        self.assertFalse(summary["diagnostic_tests_resolvable"])
        self.assertAlmostEqual(summary["p_min"], 1 / 7)
        clean = sensitivity.clean_json(summary)
        self.assertIsNone(clean["ci_low"])
        self.assertIsNone(clean["ci_high"])
        self.assertEqual(clean["post_bins"], [1, 12])
        json.dumps(clean, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
