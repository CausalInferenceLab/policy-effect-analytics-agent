"""추가 검증의 고정 기간·준비 월·잠금·결측 평가 분모를 확인한다."""

import copy
import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
data = importlib.import_module("gangnam.overnight_confirmation_data")
evaluation = importlib.import_module("gangnam.overnight_confirmation")


def configuration():
    return {"locked_year": 2026, "months": ["2025-09", "2025-10", "2025-11", "2025-12"],
            "period": ["2025-09-01", "2025-12-31"], "warmup_month": "2025-08", "primary_links": ["a"]}


def test_confirmation_rejects_locked_or_changed_period_and_warmup():
    cfg = configuration()
    assert data.check_scope(cfg) == cfg["months"]
    for change in [{"locked_year": 2027}, {"period": ["2025-09-01", "2026-01-31"]},
                   {"warmup_month": "2025-09"}, {"months": ["2025-09"]}]:
        altered = copy.deepcopy(cfg)
        altered.update(change)
        with pytest.raises(ValueError, match="고정 기간"):
            data.check_scope(altered)


def test_missing_outcomes_are_counted_and_other_period_or_duplicate_rejected():
    frame = pd.DataFrame({"link_id": ["a", "a"], "target_start": pd.to_datetime(["2025-09-01", "2025-09-02"]).tz_localize("Asia/Seoul"),
                          "speed_kmh": [15., np.nan]})
    valid, counts = evaluation.evaluation_frame(frame, configuration())
    assert len(valid) == 1 and counts == {"expected_rows": 2, "known_rows": 1, "unknown_rows": 1}
    with pytest.raises(ValueError, match="날짜"):
        evaluation.evaluation_frame(pd.concat([frame, frame.iloc[:1]]), configuration())
    frame.loc[0, "target_start"] = pd.Timestamp("2026-01-01", tz="Asia/Seoul")
    with pytest.raises(ValueError, match="날짜"):
        evaluation.evaluation_frame(frame, configuration())
