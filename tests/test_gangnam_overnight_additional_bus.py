"""추가 승객·버스 자료의 0·공란·형식 손상·사전 가중치·날짜 부재를 검증한다."""

import importlib
import json
import sys
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))
extract = importlib.import_module("gangnam.overnight_bus_extract")
passengers = importlib.import_module("gangnam.overnight_passengers")
forecast = importlib.import_module("gangnam.overnight_forecast_bus")


def test_passenger_zero_is_recorded_and_blank_stays_unknown():
    frame = pd.DataFrame({"출발_정류장_ID": ["S", "S"], "도착_정류장_ID": ["T", "T"], "재차인원합_7시": ["0", None]})
    result = extract.choose_chunk(frame, "bus_passengers", {"S"}, ["재차인원합_7시"])
    assert result.iloc[0]["재차인원합_7시"] == 0
    assert pd.isna(result.iloc[1]["재차인원합_7시"])
    frame.loc[0, "재차인원합_7시"] = "inf"
    with pytest.raises(ValueError, match="무한대"):
        extract.choose_chunk(frame, "bus_passengers", {"S"}, ["재차인원합_7시"])


def test_malformed_header_is_quarantined_without_shifting_columns(tmp_path, monkeypatch):
    monkeypatch.setattr(extract, "CASE", tmp_path)
    monkeypatch.setattr(extract, "BASE", tmp_path / "data/overnight")
    raw = tmp_path / "data/raw.zip"
    raw.parent.mkdir()
    keys, columns, _ = extract.schema("bus_passengers", [7])
    with ZipFile(raw, "w") as archive:
        archive.writestr("bad.csv", (",".join(keys + columns) + "\n20240401,R,S,T,1,5,5,EXTRA\n").encode("cp949"))
    info = extract.extract(({"kind": "bus_passengers", "month": "2024-04", "path": "data/raw.zip", "sha256": extract.sha256(raw)}, ["S"], [7], "passengers"))
    assert info["rows_selected"] == 0
    assert info["dates"] == []
    assert info["member_validation"][0]["status"] == "quarantined_header_row_mismatch"
    assert json.loads((tmp_path / info["path"]).with_suffix(".json").read_text())["schema_revision"] == 2


def test_passenger_weights_use_only_preperiod_and_fail_missing_support():
    cell = {"group": "G", "route": "R", "stop": "S", "arrival": "T", "hour": 17}
    selected = pd.DataFrame([cell])
    joined = pd.DataFrame([{**cell, "date": date, "passenger": value} for date, value in
                           [("2024-01-01", 2.), ("2024-01-02", 4.), ("2024-01-03", 10000.)]])
    before = ["2024-01-01", "2024-01-02"]
    assert passengers.fixed_weights(joined, selected, before, .8).weight.iloc[0] == 3.
    joined.loc[0, "passenger"] = np.nan
    assert pd.isna(passengers.fixed_weights(joined, selected, before, .8).weight.iloc[0])


def test_unweighted_majority_cannot_be_rebranded_passenger_weighted():
    selected = pd.DataFrame([{"group": "G", "route": str(i), "stop": "S", "arrival": "T", "hour": 17,
                              "weight": 10. if i == 0 else np.nan} for i in range(4)])
    joined = selected.drop(columns="weight").assign(date="2024-01-01", index=100.)
    daily = passengers.weighted_daily(joined, selected, ["2024-01-01"], .8)
    assert daily.weight_cell_fraction.iloc[0] == .25
    assert pd.isna(daily["index"].iloc[0])


def test_source_date_absence_is_distinct_from_missing_fixed_cell():
    panel = pd.DataFrame({"date": ["2024-01-01", "2024-01-02"], "group": "G", "route": "R", "hour": 17, "raw": [1., 2.]})
    output, _, _ = forecast.group_features(panel, ["group", "route", "hour"],
        ["2024-01-01", "2024-01-02", "2024-01-04"], "2024-01-02", "raw", "time", False)
    assert pd.isna(output.loc[pd.Timestamp("2024-01-03 17:00", tz="Asia/Seoul"), "bus_G_time_fraction"])
    assert output.loc[pd.Timestamp("2024-01-04 17:00", tz="Asia/Seoul"), "bus_G_time_fraction"] == 0.
