"""전년·기상 비교의 날짜 검증, 표본 선택, 결측 보존과 재방문 집계를 검증한다."""

import calendar
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))

from gangnam.common import read_yaml  # noqa: E402
from gangnam.directional import (  # noqa: E402
    compare,
    daily_index,
    period_dates,
    positive_presence,
    select_cells,
    standardize_weather,
    station_records,
    week_means,
)
from gangnam.directional_weather import parse_calendar  # noqa: E402


def calendar_html():
    rows = []
    for week in calendar.Calendar(firstweekday=6).monthdayscalendar(2024, 2):
        dates = "".join(f"<td>{str(day) + '일' if day else ''}</td>" for day in week)
        values = "".join("<td>" + (f"평균기온:1.5℃ 최고기온:3℃ 최저기온:-2℃ 일강수량:{'-' if day == 1 else '0.0'}mm" if day else "") + "</td>" for day in week)
        rows.extend([f"<tr>{dates}</tr>", f"<tr>{values}</tr>"])
    return '<p class="cmp-table-topinfo">서울 2024년 2월</p><table class="table-cal">' + "".join(rows) + "</table>"


def test_weather_calendar_preserves_dash_and_numeric_zero():
    d = parse_calendar(calendar_html(), "2024-02")
    assert len(d) == 29
    assert pd.isna(d.loc[0, "precipitation_mm"])
    assert d.loc[0, "precipitation_raw"] == "-"
    assert d.loc[1, "precipitation_mm"] == 0
    assert d.loc[0, "temperature_min_c"] == -2


@pytest.mark.parametrize("old,new,message", [
    ("서울", "인천", "제목"), ("2024년 2월", "2024년 3월", "제목"),
    ("1일", "2일", "요일"), ("29일", "", "누락"), ("평균기온", "평균온도", "필드"),
])
def test_weather_calendar_rejects_wrong_page_or_structure(old, new, message):
    with pytest.raises(ValueError, match=message):
        parse_calendar(calendar_html().replace(old, new, 1), "2024-02")


def panel():
    rows = []
    for route, dates in {"both": ["2023-05-22", "2024-05-20", "2024-07-08"],
                         "new": ["2024-05-20", "2024-07-08"]}.items():
        for date in dates:
            rows.append({"date": date, "group": "central_north", "route": route,
                         "stop": "a", "arrival": "b", "hour": 17, "value": 10.})
    return pd.DataFrame(rows)


def test_pre_cohort_requires_both_years_and_ignores_post_values():
    d = panel()
    periods = {"pre2023": ["2023-05-22"], "pre2024": ["2024-05-20"]}
    chosen = select_cells(d, periods, .8, "common_pre_calendar")
    assert chosen.route.tolist() == ["both"]
    d.loc[d.date.eq("2024-07-08"), "value"] = np.nan
    pd.testing.assert_frame_equal(chosen, select_cells(d, periods, .8, "common_pre_calendar"))


def test_missing_day_remains_missing_index_and_unit_scale_cancels():
    d = panel().query("route == 'both'")
    periods = {"pre2023": ["2023-05-22"], "pre2024": ["2024-05-20"]}
    dates = ["2024-05-20", "2024-05-21"]
    def run(frame):
        cells = select_cells(frame, periods, .8, "common_pre_calendar")
        return daily_index(frame, cells, dates, {"minimum_coverage": .8}, ["group"])
    a, b = run(d), run(d.assign(value=d.value * 60))
    pd.testing.assert_frame_equal(a, b)
    assert a.loc[0, "index"] == 100
    assert pd.isna(a.loc[1, "index"]) and a.loc[1, "coverage"] == 0


def test_week_bootstrap_resamples_whole_weeks_and_is_reproducible():
    d = pd.DataFrame({"date": ["2024-05-20", "2024-05-21", "2024-05-27", "2024-05-28"], "index": [0, 100, 100, 100]})
    a = week_means(d, 100, np.random.default_rng(9))
    np.testing.assert_array_equal(a, week_means(d, 100, np.random.default_rng(9)))
    assert set(a) == {50., 75., 100.}
    assert week_means(d.iloc[:2], 100, np.random.default_rng(9)) is None


def test_weather_standardization_removes_distribution_only_change():
    pre = pd.DataFrame({"date": [f"a{i}" for i in range(10)], "stratum": ["A"] * 8 + ["B"] * 2, "index": [100] * 8 + [200] * 2})
    post = pd.DataFrame({"date": [f"b{i}" for i in range(10)], "stratum": ["A"] * 2 + ["B"] * 8, "index": [110] * 2 + [220] * 8})
    result, weights = standardize_weather(pd.concat([pre, post]), pre.date, post.date, ["stratum"])
    assert result["change_pct"] == pytest.approx(10)
    assert weights.weight.tolist() == [.5, .5]
    assert result["before_retained"] == result["after_retained"] == 1


def test_weather_excludes_nonoverlapping_strata_and_reports_lost_days():
    d = pd.DataFrame({"date": list("abcdefgh"), "stratum": ["A", "A", "B", "B", "A", "A", "C", "C"], "index": [100] * 8})
    result, cells = standardize_weather(d, list("abcd"), list("efgh"), ["stratum"])
    assert cells.stratum.tolist() == ["A"]
    assert result["before_retained"] == result["after_retained"] == .5
    result, _ = standardize_weather(d, list("cd"), list("gh"), ["stratum"])
    assert result["change_pct"] is None and result["before_used"] == 0


def test_source_day_sensitivity_does_not_change_calendar_and_excludes_oct1():
    pytest.importorskip("holidays", reason="공휴일 패키지는 사례·analysis 환경에서 설치")
    cfg = read_yaml("directional_config.yaml")
    full = period_dates(cfg)
    conditional = period_dates(cfg, {"2023-05-22", "2024-10-01", "2024-10-02"})
    assert "2024-10-01" not in full["autumn2024"]
    assert conditional["autumn2024"] == ["2024-10-02"]
    assert len(full["autumn2024"]) == 38
    assert "2023-06-05" in full["pre2023"] and "2023-06-05" not in conditional["pre2023"]


def test_revisit_presence_union_is_not_a_trip_subtotal(tmp_path, monkeypatch):
    import gangnam.directional as module
    d = pd.DataFrame({"date": ["2024-05-20"] * 3, "route": ["repeat", "repeat", "single"],
                      "stop": ["s"] * 3, "sequence": [1, 5, 1], "h17": [4, 6, 2]})
    presence = positive_presence(d, [17])
    assert len(presence) == 2 and presence.positive.all()
    monkeypatch.setattr(module, "OUT", tmp_path)
    monkeypatch.setattr(module, "period_dates", lambda cfg: {"pre2024": ["2024-05-20"]})
    assert station_records(d, pd.DataFrame({"stop": ["s"]}), {"hours": [17]}, "bus_trips") == 2
    result = pd.read_csv(tmp_path / "station_bus_trips.csv")
    assert result.recorded_subtotal_daily_mean.item() == 2


def test_coverage_gate_is_kept_even_when_available_indices_look_precise():
    d = pd.DataFrame({"date": ["2024-05-20", "2024-05-27", "2024-07-08", "2024-07-15"],
                      "index": [100, 100, 90, 90], "coverage": [1, 1, .81, .81]})
    cfg = {"minimum_days": 2, "maximum_coverage_gap": .1, "bootstrap": {"seed": 1, "draws": 100}}
    result = compare(d, d.date[:2], d.date[2:], cfg)
    assert result["change_pct"] == pytest.approx(-10)
    assert not result["quality_pass"]
