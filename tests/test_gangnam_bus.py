"""버스 공동 표본·고정 분모와 원본 형식의 실제 실패 경계를 검증한다."""

import os
import sys
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest

CASE = Path(
    os.environ.get(
        "GANGNAM_CASE", Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
    )
)
sys.path.insert(0, str(CASE))
import estimate as bus  # noqa: E402
import fetch  # noqa: E402


@pytest.mark.parametrize(
    "day,label,expected",
    [(20240229, "~24시", "2024-02-29 23:00"), (20240301, "~01시", "2024-03-01 00:00")],
)
def test_hour_is_interval_start(day, label, expected):
    assert fetch.interval_start(day, label) == pd.Timestamp(expected, tz="Asia/Seoul")


def test_duplicate_conflicts_are_quarantined():
    data = pd.DataFrame({"key": ["a", "a", "b", "b", "c"], "value": [1, 1, 2, 3, np.nan]})
    result, audit = bus.clean_duplicates(data, ["key"])
    assert result.key.tolist() == ["a", "c"]
    assert audit == dict(identical_removed=1, conflicting_rows_quarantined=2, conflicting_keys=1)


def test_bus_zip_quarantines_wrong_width_and_preserves_zero(tmp_path):
    path = tmp_path / "source.zip"
    header = ",".join([*fetch.RENAME, "운행시간_17시"])
    with ZipFile(path, "w") as archive:
        archive.writestr("valid.csv", (header + "\n20240501,r,a,1,b,2,0\n").encode("cp949"))
        archive.writestr("bad.csv", (header + "\n20240501,r,a,1,b,2,10,extra\n").encode("cp949"))
    frame, info = fetch.extract_bus(path, ["a", "b"], [17])
    assert len(frame) == 1 and frame.h17.iloc[0] == 0
    assert info["dates"] == ["20240501"]
    assert {r["status"] for r in info["member_validation"]} == {
        "accepted",
        "quarantined_header_row_mismatch",
    }


def test_road_parser_keeps_missing_time_grid_and_rejects_duplicate(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    path = tmp_path / "source.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(fetch.HEADERS)
    row = (
        [20240229, "목", "강남대로", "a", "A", "B", "하행", 100, 3, "간선", "외곽", "강남"]
        + [0, -1, None, "NULL"]
        + [20] * 20
    )
    sheet.append(row)
    book.save(path)
    rules = dict(blank_is_missing=True, zero="missing", negative="missing", sentinels=["NULL"])
    frame, _ = fetch.parse_month(path, "2024-02", ["강남대로"], rules)
    assert len(frame) == 24 and frame.speed_kmh.isna().sum() == 4
    assert frame.interval_start_kst.iloc[-1] == pd.Timestamp("2024-02-29 23:00", tz="Asia/Seoul")
    sheet.append(row)
    book.save(path)
    book.close()
    with pytest.raises(ValueError, match="중복"):
        fetch.parse_month(path, "2024-02", ["강남대로"], rules)


def test_one_missing_hour_excludes_both_directions_and_fixed_denominator():
    dates = ["2024-05-01", "2024-05-02"]
    routes = [str(i) for i in range(13)]
    hours = list(range(7, 23))
    rows = pd.MultiIndex.from_product(
        [dates, routes, ["south", "north"], hours], names=["date", "route", "segment", "hour"]
    ).to_frame(index=False)
    rows["value"] = 100.0
    # 첫날 2개, 둘째 날 3개 노선에서 단 한 방향의 한 시간만 빠진다.
    rows.loc[rows.route.isin(["0", "1"]) & rows.segment.eq("north") & rows.hour.eq(8), "value"] = (
        np.nan
    )
    rows.loc[
        rows.date.eq(dates[1]) & rows.route.eq("2") & rows.segment.eq("south") & rows.hour.eq(9),
        "value",
    ] = 0
    matrix, joint = bus.joint_directions(rows, routes, hours, dates)
    assert joint.groupby("date").sum().tolist() == [11, 10]
    daily = bus.daily_paired(matrix, 13, dates, [17, 18, 19], 0.8)
    first, last = daily[daily.date.eq(dates[0])], daily[daily.date.eq(dates[1])]
    assert first["index"].eq(100).all() and last["index"].isna().all()
    assert first.coverage.eq(11 / 13).all() and last.coverage.eq(10 / 13).all()


def test_baseline_uses_only_reference_dates():
    index = pd.MultiIndex.from_product(
        [["pre2023", "pre2024", "post"], ["r"]], names=["date", "route"]
    )
    matrix = pd.DataFrame({17: [10.0, 20.0, 9000.0]}, index=index)
    _, baseline, normalized = bus.select_routes(
        matrix, pd.Series(True, index=index), {"pre2023": ["pre2023"], "pre2024": ["pre2024"]}, 0.8
    )
    assert baseline.loc["r", 17] == 20
    assert normalized.loc[("post", "r"), 17] == 45000


def test_same_date_sensitivity_never_admits_new_dates():
    data = pd.DataFrame(
        dict(date=["a", "b"], segment=["south", "south"], index=[90.0, 80.0], coverage=[1.0, 1.0])
    )
    reference = data.copy()
    reference.loc[1, "index"] = np.nan
    result = bus.accepted_dates_only(data, reference)
    assert result["index"].iloc[0] == 90 and pd.isna(result["index"].iloc[1])
    assert result.coverage.tolist() == [1.0, 1.0]


def test_figure_tables_follow_the_fixed_baseline():
    weekdays = pd.bdate_range("2024-06-03", "2024-06-14").strftime("%Y-%m-%d").tolist()
    routes, hours = ["r0", "r1", "r2"], [8, 17, 18, 19]
    cfg = dict(
        routes=routes,
        hours=hours,
        report_hours=[17, 18, 19],
        record_window=["2024-06-03", "2024-06-14"],
        retired_route=dict(id="r2"),
        minimum_coverage=0.5,
        minimum_pre_joint_coverage=0.5,
        minimum_days=1,
        maximum_coverage_gap=1.0,
        calendar=dict(
            pre2024=["2024-06-03", "2024-06-04"],
            post2024=["2024-06-10", "2024-06-11"],
            post2025=["2024-06-12"],
        ),
        selection_reference_dates=dict(
            pre2023=["2024-06-05"], pre2024=["2024-06-03", "2024-06-04"]
        ),
        comparisons=dict(
            summer2024=["pre2024", "post2024"], post2025_from_pre2024=["pre2024", "post2025"]
        ),
    )
    panel = pd.MultiIndex.from_product(
        [weekdays, routes, ["south", "north"], hours], names=["date", "route", "segment", "hour"]
    ).to_frame(index=False)
    second = panel.date.ge("2024-06-10")
    panel["value"] = 10.0
    panel.loc[second & panel.segment.eq("south"), "value"] = 5.0
    panel.loc[second & panel.segment.eq("north"), "value"] = 15.0
    dates = sorted(
        set().union(*cfg["calendar"].values(), *cfg["selection_reference_dates"].values())
    )
    matrix, joint = bus.joint_directions(panel, routes, hours, dates)
    _, baseline, normalized = bus.select_routes(
        matrix, joint, cfg["selection_reference_dates"], cfg["minimum_pre_joint_coverage"]
    )
    baseline.columns = [f"{segment}_h{hour:02}" for segment, hour in baseline.columns]
    kept = normalized[normalized.index.get_level_values("route") != "r2"]
    native = bus.daily_paired(kept, 2, dates, cfg["report_hours"], cfg["minimum_coverage"])

    weekly = bus.weekly_trajectory(panel, cfg, ["2024-06-06"], baseline, native)
    south, north = (weekly[weekly.segment.eq(s)] for s in ["south", "north"])
    assert south.index_mean.tolist() == [100, 50] and north.index_mean.tolist() == [100, 150]
    assert south.days.tolist() == [4, 5]

    hourly = bus.hourly_changes(kept, 2, dates, cfg)
    assert len(hourly) == len(hours) * 2 * 2
    evening = hourly[hourly.hour.eq(18) & hourly.comparison.eq("summer2024")]
    assert evening.set_index("segment").change_pct.round(6).to_dict() == {"south": -50, "north": 50}

    shifted = baseline * 2
    with pytest.raises(ValueError, match="사전 기준값"):
        bus.weekly_trajectory(panel, cfg, [], shifted, native)
