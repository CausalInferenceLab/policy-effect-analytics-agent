"""월별 카드 비교에서 사전 표본 선택·날짜 가중·누락 월 처리를 검증한다."""

import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
analysis = importlib.import_module("gangnam.overnight_card_analysis")


def test_monthly_rate_weights_calendar_days_and_never_ignores_missing_month():
    d = pd.DataFrame({"month": ["2024-04", "2024-05"], "calendar_days": [30, 31],
                      "total": [300., 620.], "quality_complete": [True, True]})
    result = analysis.period_result(d, ["2024-04", "2024-05"])
    assert result["mean_per_calendar_day"] == pytest.approx(920 / 61)
    d.loc[1, "total"] = np.nan
    assert not analysis.period_result(d, ["2024-04", "2024-05"])["complete"]
    assert not analysis.period_result(d.iloc[:1], ["2024-04", "2024-05"])["complete"]


def test_fixed_card_cohort_does_not_select_post_only_label_or_fill_absence():
    before = ["2023-04", "2023-05", "2024-04", "2024-05"]
    rows = []
    for month, route in [(m, "old") for m in before] + [("2024-07", "new")]:
        for hour in range(24):
            for flow in ["boardings", "alightings"]:
                rows.append({"month": month, "route_label": route, "stop": "100", "hour": hour,
                             "flow": flow, "value": 0., "status": "zero", "ars": "01001", "eligible_row": True})
    grid, selected = analysis.fixed_labels(pd.DataFrame(rows), before, before + ["2024-07"])
    assert selected.route_label.tolist() == ["old"]
    after = grid[grid.month.eq("2024-07")]
    assert len(after) == 48 and after.value.isna().all() and after.status.eq("row_absent").all()
