"""공개 키가 중복되는 환승 기록과 빈 시각이 있는 출도착 합계를 검증한다."""

import importlib
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
quality = importlib.import_module("gangnam.overnight_auxiliary_quality")
probe = importlib.import_module("gangnam.overnight_transfer_probe")


def test_distinct_counts_under_same_transfer_key_remain_ambiguous():
    row = ["20240501", "0222", "123456789", "17", "2", "2", "0", "0", "0", "0", "300", "300", "0", "0", "0", "0"]
    other = row.copy()
    other[4:6] = ["3", "3"]
    audit, _, multiplicity = quality.transfer_quality(pd.DataFrame([row, other], columns=probe.TRANSFER))
    assert audit["ambiguous_rows"] == 2 and audit["exact_duplicate_extra_rows"] == 0
    assert audit["unique_key_rows"] == 0
    assert multiplicity.iloc[0].to_dict() == {"multiplicity": 2, "public_keys": 1}


def test_matching_daily_total_does_not_turn_blank_hours_into_zero():
    row = ["20240501", "123456789", "0222", "5", "2", "3"] + [None] * 22
    audit, _ = quality.od_quality(pd.DataFrame([row], columns=probe.OD))
    assert audit["hourly_blank_cells"] == 22 and audit["all_hours_known_rows"] == 0
    assert audit["known_hour_sum_daily_total_mismatch_rows"] == 0
