"""확장 버스 패널의 관측 상태·노선 동일 가중·결측 분모를 합성 자료로 점검한다."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))

from gangnam.overnight_bus import make_time_panel  # noqa: E402
from gangnam.overnight_sensitivity import aggregate_daily, describe_comparison, normalized  # noqa: E402


def selected():
    return pd.DataFrame([{"group": "north", "route": r, "stop": "s", "arrival": "t", "hour": h,
                          "baseline_2023": 50., "baseline_2024": 100.}
                         for r, hours in [("many", [17, 18, 19]), ("few", [17])] for h in hours])


def observations():
    d = selected().drop(columns=["baseline_2023", "baseline_2024"])
    d["date"] = "2024-07-08"
    d["value"] = [100., 100., 100., 200.]
    return d


def test_equal_route_weighting_changes_unit_of_average():
    s, d = selected(), normalized(observations(), selected())
    cells = aggregate_daily(d, s, ["2024-07-08"], "equal_cells", .8)
    routes = aggregate_daily(d, s, ["2024-07-08"], "equal_routes", .8)
    assert cells["index"].item() == 125.
    assert routes["index"].item() == 150.
    assert routes.unit_coverage.item() == 1.


def test_missing_route_is_not_zero_and_fails_unit_coverage():
    s = selected()
    d = normalized(observations().query("route == 'many'"), s)
    result = aggregate_daily(d, s, ["2024-07-08", "2024-07-09"], "equal_routes", .7)
    assert result.iloc[0].coverage == .75
    assert result.iloc[0].unit_coverage == .5
    assert np.isnan(result.iloc[0]["index"])
    assert result.iloc[1].coverage == 0
    assert result.iloc[1].unit_coverage == 0


def test_each_route_requires_internal_coverage_before_equal_weight():
    s = selected()
    d = observations().iloc[[0, 1, 3]]
    result = aggregate_daily(normalized(d, s), s, ["2024-07-08"], "equal_routes", .7)
    assert result.unit_coverage.item() == .5
    assert np.isnan(result["index"].item())


def test_normalization_uses_the_matching_year_only():
    d = observations()
    d["date"] = "2023-07-08"
    assert normalized(d, selected())["index"].tolist() == [200., 200., 200., 400.]


def test_quality_requires_twenty_days_and_both_coverage_gaps():
    dates = pd.date_range("2024-01-01", periods=40).strftime("%Y-%m-%d").tolist()
    d = pd.DataFrame({"date": dates, "index": [100.] * 20 + [90.] * 20,
                      "coverage": [1.] * 40, "unit_coverage": [1.] * 20 + [.8] * 20})
    cfg = {"minimum_days": 20, "maximum_coverage_gap": .1}
    assert not describe_comparison(d, dates[:20], dates[20:], cfg)["quality_pass"]
    d["unit_coverage"] = 1.
    result = describe_comparison(d, dates[:20], dates[20:], cfg)
    assert result["quality_pass"]
    assert result["change_pct"] == pytest.approx(-10.)
    assert not describe_comparison(d, dates[:19], dates[20:], cfg)["quality_pass"]


def test_time_panel_keeps_zero_blank_and_quarantines_revisit_keys():
    stations = pd.DataFrame({"stop": ["s", "t"], "group": ["central_north"] * 2, "order": [0, 1],
                             "historical_id_ars_pair": [True, True], "historical_2023_pair": [True, True]})
    base = {"date": "2024-07-08", "route": "r", "stop": "s", "arrival": "t", "sequence": "1", "arrival_sequence": "2"}
    wide = pd.DataFrame([{**base, "h17": 0., "h18": np.nan, "h19": 60.},
                         {**base, "route": "loop", "h17": 20., "h18": 20., "h19": 20.},
                         {**base, "route": "loop", "sequence": "8", "arrival_sequence": "9", "h17": 30., "h18": 30., "h19": 30.}])
    cfg = {"primary_groups": ["central_north"], "secondary_groups": [], "hours": [17, 18, 19]}
    d, excluded = make_time_panel(wide, stations, cfg)
    assert excluded == 2
    assert d.record_status.tolist() == ["zero", "blank", "positive"]
    assert d.value.notna().tolist() == [False, False, True]
    assert d.raw_value.iloc[0] == 0.
