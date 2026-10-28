"""과거 기상 응답의 시각 검증·0 보존·범위 판정·겹친 관측 충돌을 검사한다."""

import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))

from gangnam.overnight_weather import deduplicate, number, parse_response, request_endpoints  # noqa: E402


def response():
    return {"dataTm": "202406281800", "stnId": "401", "db": "MINDB_60M", "items": [
        {"tm": "202406281800", "awsStnId": 401, "awsTmp": "30", "awsPcpHr1": "0", "awsReh": "41", "awsWs10": "2.2", "awsTroblKnd": "N/A"}
    ]}


def test_rain_zero_is_observed_and_blank_is_not_zero():
    assert number("0", 0, 500) == (0., "numeric")
    missing, status = number("-", 0, 500)
    assert np.isnan(missing) and status == "blank"
    missing, status = number("-99.9", -70, 60)
    assert np.isnan(missing) and status == "outside_range"
    missing, status = number(".", 0, 500)
    assert np.isnan(missing) and status == "non_numeric_placeholder"
    with pytest.raises(ValueError, match="수치 표기"):
        number("강수 없음", 0, 500)


@pytest.mark.parametrize("field,value", [("dataTm", "202610290100"), ("stnId", "400"), ("db", "MINDB_01M")])
def test_current_fallback_or_wrong_station_is_rejected(field, value):
    payload = response()
    payload[field] = value
    with pytest.raises(ValueError, match="요청과"):
        parse_response(payload, 401, "2024-06-28 18:00")


def test_unknown_fault_does_not_become_verified_qc_and_zero_is_kept():
    d = parse_response(response(), 401, "2024-06-28 18:00")
    assert d.service_fault_raw.item() == "N/A"
    assert not d.service_known_issue.item()
    assert d.precipitation_1h_mm.item() == 0
    assert d.temperature_c.item() == 30


def test_known_device_problem_is_excluded_but_raw_value_is_preserved():
    payload = response()
    payload["items"][0]["awsTroblKnd"] = "장애"
    d = parse_response(payload, 401, "2024-06-28 18:00")
    assert d.service_known_issue.item()
    assert np.isnan(d.precipitation_1h_mm.item())
    assert d.precipitation_1h_mm_raw.item() == "0"


def test_duplicate_or_future_observation_is_rejected():
    payload = response()
    payload["items"].append(payload["items"][0].copy())
    with pytest.raises(ValueError, match="중복"):
        parse_response(payload, 401, "2024-06-28 18:00")
    payload = response()
    payload["items"][0]["tm"] = "202406281900"
    with pytest.raises(ValueError, match="날짜"):
        parse_response(payload, 401, "2024-06-28 18:00")


def test_month_requests_cover_every_hour_without_future_month_dependency():
    for month in ("2023-04", "2024-02", "2024-07"):
        endpoints = request_endpoints([month])
        covered = {t for end in endpoints for t in pd.date_range(end - timedelta(hours=59), end, freq="h")}
        expected = set(pd.date_range(month + "-01", periods=pd.Period(month).days_in_month * 24, freq="h"))
        assert expected <= covered
        assert max(endpoints) == max(expected)


def test_overlapping_conflicting_measurements_are_quarantined():
    a = parse_response(response(), 401, "2024-06-28 18:00")
    clean, audit = deduplicate(pd.concat([a, a], ignore_index=True))
    assert len(clean) == 1 and audit["conflicting_keys_quarantined"] == 0
    changed = a.copy()
    changed["precipitation_1h_mm"] = 3
    clean, audit = deduplicate(pd.concat([a, changed], ignore_index=True))
    assert clean.empty and audit["conflicting_keys_quarantined"] == 1
