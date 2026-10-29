"""공식 안내의 생략·중복과 집단별 날짜 차이를 숨기지 않는지 검사한다."""

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
pd = pytest.importorskip("pandas")
pytest.importorskip("numpy")
pytest.importorskip("openpyxl")
mod = importlib.import_module("gangnam.deepening_infrastructure")
groups = importlib.import_module("gangnam.deepening_route_groups")
check = importlib.import_module("gangnam.deepening_infrastructure_check")
raw = importlib.import_module("gangnam.deepening_infrastructure_raw")


def test_notice_parser_keeps_leading_zero_and_rejects_ellipsis_or_duplicate():
    html = "<table><tr><td>정류소 (22-295)</td><td>140, 0411 [2개노선]</td></tr></table>"
    assert mod.notice_routes(html, ["22295"]) == {"22295": ["140", "0411"]}
    with pytest.raises(ValueError, match="생략"):
        mod.notice_routes(html.replace("0411", "0411 등"), ["22295"])
    with pytest.raises(ValueError, match="중복"):
        mod.notice_routes(html + html, ["22295"])


def test_historical_name_ambiguity_is_not_silently_mapped():
    history = pd.DataFrame([dict(target_route="a", route_name=name, match_status="matched") for name in ["140", "141"]])
    with pytest.raises(ValueError, match="다중 대응"):
        mod.group_membership(history, ["a"], {}, {})


def test_common_dates_require_each_fixed_partition_to_be_observed():
    daily = pd.DataFrame([dict(date=day, group=group, segment="south", index=value)
        for day, group, value in [("2024-06-03", "a", 100), ("2024-06-03", "b", float("nan")),
                                  ("2024-06-04", "a", 100), ("2024-06-04", "b", 120)]])
    assert groups.common_dates(daily) == {"2024-06-04"}


def test_group_gap_uses_relative_changes_and_same_weeks():
    dates = pd.bdate_range("2024-05-01", "2024-07-01").strftime("%Y-%m-%d").tolist()
    before, after = dates[:20], dates[20:]
    rows = [dict(date=day, group=group, index=(100 if day in before else 50) if group == "announced_central" else (200 if day in before else 250))
            for day in dates for group in ["announced_central", "announced_curb"]]
    result = groups.group_gap(pd.DataFrame(rows), before, after, 200, 17)
    assert result["central_minus_curb_percentage_points"] == pytest.approx(-75)
    assert result["week_bootstrap_low"] == pytest.approx(-75)
    assert result["week_bootstrap_high"] == pytest.approx(-75)


def test_missing_non_report_hour_excludes_both_directions_in_independent_check():
    rows = [SimpleNamespace(route="a", segment=segment, hour=hour, raw_value=20., record_status="positive")
            for segment in ["south", "north"] for hour in range(7, 23)]
    baselines = {("a", row.segment, row.hour): 10. for row in rows}
    assert check.route_day_values(rows, baselines, list(range(7, 23)), [17, 18, 19]) == {"south": 200., "north": 200.}
    rows[0].raw_value = float("nan")
    rows[0].record_status = "blank"
    assert check.route_day_values(rows, baselines, list(range(7, 23)), [17, 18, 19]) is None


def test_trip_record_absence_zero_and_conflict_are_distinct():
    zero = ("1", tuple([0.] * 25))
    assert raw.summarize(set(), False)["record_state"] == "source_date_absent"
    assert raw.summarize(set(), True)["record_state"] == "row_absent"
    result = raw.summarize({zero}, True)
    assert result["zero_hours"] == 24 and result["daily_hour_sum_equal"]
    assert raw.summarize({zero, ("2", zero[1])}, True)["record_state"] == "multiple_records_quarantined"
