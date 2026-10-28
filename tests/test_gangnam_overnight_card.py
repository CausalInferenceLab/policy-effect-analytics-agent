"""월 카드의 시간 열·반복 정류장·0과 공란·역사적 대응 처리를 검증한다."""

import csv
import importlib
import io
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
card = importlib.import_module("gangnam.overnight_card")


def headers():
    return [f"{h}시{flow}총승객수" for h in range(24) for flow in ["승차", "하차"]]


def test_card_zero_is_known_blank_is_unknown_and_revisits_are_excluded():
    row = {"month": "2024-04", "route_label": "100", "stop": "123456789", "ars": "22001", "stop_name": "시험"}
    row.update(dict.fromkeys(headers(), "0"))
    row["1시승차총승객수"] = ""
    stations = pd.DataFrame({"stop": ["123456789"], "ars": ["22001"]})
    long, excluded = card.eligible_long(pd.DataFrame([row]), stations)
    assert excluded.empty and long.value.notna().sum() == 47
    assert long.value.dropna().eq(0).all()
    repeated, excluded = card.eligible_long(pd.DataFrame([row, row]), stations)
    assert len(excluded) == 2 and repeated.value.isna().all()


def test_history_reads_identifiers_without_retaining_passenger_values():
    source = io.StringIO()
    csv.writer(source).writerows([card.IDS + headers(), ["202505", "100", "노선", "123456789", "22001", "정류장"] + ["9"] * 48])
    source.seek(0)
    frame, audit = card.read_card(source, "2025-05", {"123456789"}, False)
    assert set(frame) == set(card.RENAMES.values())
    assert not audit["values_read_for_analysis"]
    assert frame.ars.iloc[0] == "22001"


def test_duplicate_hour_alias_is_rejected():
    with pytest.raises(ValueError, match="중복"):
        card.hour_columns(headers() + ["00시승차총승객수"])
