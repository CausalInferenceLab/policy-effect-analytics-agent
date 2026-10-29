"""인접 경로의 공동 결측과 원시 합의 정규화, 사전 선택의 사후 독립성을 검증한다."""

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
module = importlib.import_module("gangnam.overnight_path_sums")


def fixture_rows():
    dates = ["2023-06-01", "2024-06-01", "2024-07-01", "2024-07-02"]
    rows = []
    for date, pair in zip(dates, [(10, 30), (10, 30), (5, 45), (5, 0)], strict=True):
        for leg, value in enumerate(pair):
            rows.append({"date": date, "route": "r", "hour": 17, "stop": str(leg), "arrival": str(leg + 1), "value": value})
    legs = pd.DataFrame({"leg": [0, 1], "stop": ["0", "1"], "arrival": ["1", "2"]})
    candidates = pd.DataFrame({"route": ["r"], "hour": [17]})
    return dates, pd.DataFrame(rows), candidates, legs


def test_raw_sum_is_normalized_after_adding_and_any_invalid_leg_invalidates_all():
    dates, rows, candidates, legs = fixture_rows()
    matrix, joint = module.joint_matrix(rows, candidates, legs, dates)
    assert not joint.loc[(dates[-1], "r", 17)] and matrix.loc[(dates[-1], "r", 17)].isna().all()
    reference = {"pre2023": [dates[0]], "pre2024": [dates[1]]}
    support, baseline, normalized = module.choose_and_normalize(matrix, joint, reference, .8)
    assert support.eligible.all() and baseline["sum"].iloc[0] == 40
    point = normalized.loc[(dates[2], "r", 17)]
    assert point["sum"] == 125 and point[["leg_0", "leg_1"]].mean() == 100
    daily = module.daily_indices(normalized, 1, dates, .8)
    assert daily[daily.date.eq(dates[-1])]["index"].isna().all()
    assert daily[daily.date.eq(dates[-1])].coverage.eq(0).all()


def test_missing_leg_and_future_change_do_not_change_pre_selection():
    dates, rows, candidates, legs = fixture_rows()
    matrix, joint = module.joint_matrix(rows, candidates, legs, dates)
    reference = {"pre2023": [dates[0]], "pre2024": [dates[1]]}
    support, baseline, _ = module.choose_and_normalize(matrix, joint, reference, .8)
    future = rows[~(rows.date.eq(dates[2]) & rows.stop.eq("1"))].copy()
    future.loc[future.date.eq(dates[-1]), "value"] = 1000000
    changed, mask = module.joint_matrix(future, candidates, legs, dates)
    assert changed.loc[(dates[2], "r", 17)].isna().all()
    other_support, other_baseline, _ = module.choose_and_normalize(changed, mask, reference, .8)
    pd.testing.assert_frame_equal(support, other_support)
    pd.testing.assert_frame_equal(baseline, other_baseline)
    duplicated = pd.concat([rows, rows.iloc[:1]], ignore_index=True)
    with pytest.raises(ValueError, match="중복"):
        module.joint_matrix(duplicated, candidates, legs, dates)
    assert np.isfinite(baseline["sum"]).all()
