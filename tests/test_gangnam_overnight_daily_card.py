"""일별 카드의 잘못된 다운로드와 불완전 합계·중복 표시 보존을 검증한다."""

import csv
import importlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
data = importlib.import_module("gangnam.overnight_daily_card_data")
analysis = importlib.import_module("gangnam.overnight_daily_card_analysis")


def test_daily_card_rejects_html_and_another_month(tmp_path):
    path = tmp_path / "daily.csv"
    path.write_text("<html>file not found</html>")
    with pytest.raises(ValueError, match="헤더"):
        data.validate(path, "2024-05")
    with path.open("w", encoding="cp949", newline="") as f:
        csv.writer(f).writerows([data.HEADERS, ["20240701", "100", "노선", "123456789", "22001", "정류장", "1", "2", "20240704"]])
    with pytest.raises(ValueError, match="첫 날짜"):
        data.validate(path, "2024-05")
    assert data.validate(path, "2024-07") == "cp949"


def test_incomplete_card_sum_is_not_a_smaller_known_sum():
    assert analysis.complete_sum(pd.Series([1., 2.])) == 3.
    assert analysis.complete_sum(pd.Series([0., 0.])) == 0.
    assert np.isnan(analysis.complete_sum(pd.Series([1., np.nan])))


def test_reconciliation_retains_public_key_duplicates_without_deduplication():
    base = {"month": "2024-05", "date": "20240501", "route_label": "100", "route_name": "노선", "stop": "1",
            "stop_name": "정류장(001)", "exact_duplicate": False, "승차총승객수": "2", "하차총승객수": "3"}
    second = {**base, "stop_name": "정류장(002)", "승차총승객수": "5"}
    totals = analysis.record_totals(pd.DataFrame([base, second]), True)
    board = totals[totals.flow.eq("boardings")].iloc[0]
    assert board.record_sum == 7 and board.ambiguous_key_rows == 2
    assert board.stop_name_variants == 2 and board.exact_duplicate_rows == 0
