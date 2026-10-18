"""합성 자료로 시간 변환·대상 추출·파일 출력을 검증한다."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.sax.saxutils import escape
from zipfile import ZipFile

import numpy as np
import pandas as pd

from core.pipeline import run_plan, split_hours
from core.schema.plan import load_plan

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("green_traffic_fetch", HERE / "fetch.py")
fetch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetch)
CONTROLS = {"111202"}
PLAN = {"time": {"col": "hour_idx", "freq": "hour", "start": 0, "end": 43823}}


def row(stamp, code="111124", no2=0.02, pm25=15, region="서울 중구", network="도로변대기"):
    return [region, network, code, f"측정소{code}", stamp, no2, pm25]


def raw(rows):
    return pd.DataFrame(rows, columns=fetch.RAW_COLUMNS)


def write_workbook(path, rows):
    """테스트 전용의 작은 XLSX. 원자료를 사용하거나 배포하지 않는다."""
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    sheet_rows = []
    for number, values in enumerate([fetch.RAW_COLUMNS, *rows], 1):
        cells = []
        for index, value in enumerate(values):
            reference = f"{chr(65 + index)}{number}"
            if value is None:
                cells.append(f'<c r="{reference}"/>')
            elif isinstance(value, (int, float)):
                cells.append(f'<c r="{reference}"><v>{value}</v></c>')
            else:
                cells.append(
                    f'<c r="{reference}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'
                )
        sheet_rows.append(f'<row r="{number}">{"".join(cells)}</row>')
    parts = {
        "[Content_Types].xml": '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>',
        "_rels/.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": f'<workbook xmlns="{namespace}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": f'<worksheet xmlns="{namespace}"><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>',
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w") as workbook:
        for name, text in parts.items():
            workbook.writestr(name, text)


class FetchTests(unittest.TestCase):
    def test_end_labels_keep_date_and_gaps(self):
        data = raw([row(2017010101), row(2017010124), row(2017010202)])
        panel = fetch.normalise(data, CONTROLS, "end", PLAN)
        self.assertEqual(panel.hour_idx.tolist(), [0, 23, 25])
        self.assertEqual(panel.hour.tolist(), [0, 23, 1])
        self.assertEqual(panel.datetime.iloc[1], pd.Timestamp("2017-01-01 23:00", tz="Asia/Seoul"))
        self.assertEqual(panel.measurement_time.iloc[1], "2017010124")

    def test_start_labels_roll_24_to_next_day(self):
        panel = fetch.normalise(raw([row(2017010124)]), CONTROLS, "start", PLAN)
        self.assertEqual(panel.hour_idx.tolist(), [24])
        self.assertEqual(panel.hour.tolist(), [0])
        self.assertEqual(panel.datetime.iloc[0], pd.Timestamp("2017-01-02", tz="Asia/Seoul"))

    def test_restricted_hours_use_observation_start(self):
        stamps = [2019120106, 2019120107, 2019120121, 2019120122]
        panel = fetch.normalise(
            raw([row(stamp) for stamp in stamps]), CONTROLS, fetch.HOUR_LABEL, PLAN
        )
        self.assertEqual(panel.hour.tolist(), [5, 6, 20, 21])
        plan = load_plan(HERE / "plan.yaml")
        active, inactive = split_hours(plan, panel)
        self.assertEqual(active.measurement_time.tolist(), ["2019120107", "2019120121"])
        self.assertEqual(inactive.measurement_time.tolist(), ["2019120106", "2019120122"])
        self.assertEqual(len(active) + len(inactive), len(panel))

    def test_reference_week_survives_pilot_exclusion_for_both_windows(self):
        plan = load_plan(HERE / "plan.yaml")
        start = fetch.ORIGIN + pd.Timedelta(
            hours=plan.treatment.treat_time + plan.estimator.ref_period * plan.estimator.bin
        )
        clock = pd.date_range(start, periods=plan.estimator.bin, freq="h")
        data = raw(
            [
                row(int(f"{when:%Y%m%d}{when.hour + 1:02d}"), code)
                for code in sorted(fetch.TREATED | CONTROLS)
                for when in clock
            ]
        )
        panel = fetch.normalise(data, CONTROLS, "end", fetch.load_plan())
        active, inactive = split_hours(plan, panel)
        for window, count in [(active, 105), (inactive, 63)]:
            self.assertTrue(window.groupby("station_id").size().eq(count).all())
            relative = (window.hour_idx - plan.treatment.treat_time) // plan.estimator.bin
            self.assertTrue(relative.eq(plan.estimator.ref_period).all())
            self.assertTrue(window.datetime.lt(pd.Timestamp("2019-07-01", tz="Asia/Seoul")).all())

    def test_weekly_plan_runs_on_synthetic_data_with_pilot_gap(self):
        """실제 계획·수집기·공통 추정기의 연결을 작은 합성 표로 확인한다."""
        plan = load_plan(HERE / "plan.yaml")
        treat = fetch.ORIGIN + pd.Timedelta(hours=plan.treatment.treat_time)
        rng = np.random.default_rng(42)
        records = []
        for number, code in enumerate(sorted(fetch.TREATED | set(fetch.CONTROL_STATIONS))):
            for week in [-54, -53, -52, -51, -24, -23, 0, 1, 4, 12, 13]:
                day = (treat + pd.Timedelta(weeks=week)).normalize()
                for hour in [5, 6, 20, 21]:
                    when = day + pd.Timedelta(hours=hour)
                    exposed = code in fetch.TREATED and when >= treat and 6 <= hour < 21
                    records.append(
                        row(
                            int(f"{when:%Y%m%d}{hour + 1:02d}"),
                            code,
                            no2=0.02
                            + number * 0.001
                            + week * 0.00001
                            - 0.003 * exposed
                            + rng.normal(0, 0.00005),
                            pm25=15
                            + number * 0.2
                            + week * 0.01
                            - 2 * exposed
                            + rng.normal(0, 0.05),
                        )
                    )
        panel = fetch.normalise(raw(records), set(fetch.CONTROL_STATIONS), "end", fetch.load_plan())
        results = run_plan(plan, panel)
        self.assertEqual([result.outcome for result in results], ["no2", "pm25"])
        for result, effect, tolerance in zip(results, [-0.003, -2], [0.0005, 0.2], strict=True):
            self.assertAlmostEqual(result.estimate, effect, delta=tolerance)
            self.assertIn("randomization inference", result.assumptions_checked["inference"])
            coefficients = result.extra["coefs"]
            reference = coefficients.loc[coefficients.rel_time.eq(plan.estimator.ref_period)]
            self.assertEqual(reference.coef.tolist(), [0.0])
            self.assertEqual(coefficients.rel_time.min(), plan.estimator.window[0])
            self.assertEqual(coefficients.rel_time.max(), plan.estimator.window[1])
            self.assertNotIn(-2, coefficients.rel_time.tolist())  # 시범 운영기에는 계수 없음.
            checks = result.assumptions_checked
            self.assertIn("parallel_pretrends", checks)
            self.assertAlmostEqual(checks["placebo_window"]["estimate"], 0, delta=tolerance)
            self.assertEqual(
                checks["placebo_time"]["fake_treat_time"],
                plan.treatment.treat_time - 52 * plan.estimator.bin,
            )

    def test_pilot_exclusion_for_both_groups(self):
        stamps = [2019063024, 2019070101, 2019113024, 2019120101]
        data = raw(
            [row(stamp, code) for code in sorted(fetch.TREATED | CONTROLS) for stamp in stamps]
        )
        panel = fetch.normalise(data, CONTROLS, "end", PLAN)
        self.assertEqual(sorted(panel.hour_idx.unique()), [21863, 25536])
        self.assertEqual(len(panel), 6)
        self.assertTrue(panel.groupby("station_id").treated.nunique().eq(1).all())
        self.assertEqual(panel.loc[panel.station_id.eq("111202"), "treated"].tolist(), [0, 0])

    def test_missing_values_preserve_real_zero(self):
        data = raw(
            [
                row(2017010101, no2=-999, pm25=None),
                row(2017010102, no2="", pm25=-999),
                row(2017010103, no2=0, pm25=0),
            ]
        )
        panel = fetch.normalise(data, CONTROLS, "end", PLAN)
        self.assertTrue(panel.loc[:1, ["no2", "pm25"]].isna().all().all())
        self.assertEqual(panel.loc[2, ["no2", "pm25"]].tolist(), [0, 0])

    def test_region_network_and_station_filter(self):
        data = raw(
            [
                row(2017010101),
                row(2017010101, network="도시대기"),
                row(2017010101, region="부산 중구"),
                row(2017010101, code="111999"),
            ]
        )
        self.assertEqual(len(fetch.normalise(data, CONTROLS, "end", PLAN)), 1)
        self.assertTrue(fetch.normalise(raw([]), CONTROLS, "end", PLAN).empty)

    def test_invalid_time_fails(self):
        for stamp in [2017010100, 2017010125, 2017023001, "잘못된 시각"]:
            with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                fetch.normalise(raw([row(stamp)]), CONTROLS, "end", PLAN)

    def test_unresolved_settings_stop_before_reading(self):
        with patch.object(fetch, "read_month") as read, patch.object(fetch, "HOUR_LABEL", None):
            with self.assertRaisesRegex(ValueError, "대조군"):
                fetch.build_panel(controls=(), hour_label="end", plan=PLAN)
            with self.assertRaisesRegex(ValueError, "HOUR_LABEL"):
                fetch.build_panel(controls=CONTROLS, hour_label=None, plan=PLAN)
            read.assert_not_called()

    def test_missing_or_duplicate_month_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "2017년 1월.xlsx").touch()
            with self.assertRaisesRegex(ValueError, "2017-02"):
                fetch.monthly_files(root, 0, 744)
            (root / "2017년 01월.xlsx").touch()
            with self.assertRaisesRegex(ValueError, "둘 이상"):
                fetch.monthly_files(root, 0, 23)

    def test_duplicate_station_hour_fails(self):
        data = raw(
            [row(2017010101, code) for code in sorted(fetch.TREATED | CONTROLS)] + [row(2017010101)]
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "2017년 1월.xlsx").touch()
            with (
                patch.object(fetch, "read_month", return_value=data),
                self.assertRaisesRegex(ValueError, "중복"),
            ):
                fetch.build_panel(
                    root,
                    CONTROLS,
                    "end",
                    {"time": {"col": "hour_idx", "freq": "hour", "start": 0, "end": 23}},
                )

    @unittest.skipUnless(importlib.util.find_spec("openpyxl"), "openpyxl 미설치")
    def test_xlsx_reader_builds_panel_without_changing_input(self):
        rows = [row(2017010101, code) for code in sorted(fetch.TREATED | fetch.CONTROL_CANDIDATES)]
        rows += [
            row(2017010103),
            row(2017010101, network="도시대기"),
            row(2017010101, region="부산 중구"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "2017" / "2017년 01월.xlsx"
            write_workbook(path, rows)
            original = hashlib.sha256(path.read_bytes()).hexdigest()
            plan = {"time": {"col": "hour_idx", "freq": "hour", "start": 0, "end": 23}}
            panel = fetch.build_panel(root, plan=plan)
            self.assertEqual(len(panel), 12)  # 처치 2곳·대조 9곳, 처치 측정소의 추가 1시간.
            self.assertEqual(panel.loc[panel.treated.eq(0), "station_id"].nunique(), 9)
            self.assertEqual(panel.loc[panel.treated.eq(1), "station_id"].nunique(), 2)
            self.assertTrue({"111122", "111162", "111143", "111282"}.isdisjoint(panel.station_id))
            self.assertEqual(panel.loc[panel.station_id.eq("111124"), "hour_idx"].tolist(), [0, 2])
            self.assertEqual(panel.loc[panel.station_id.eq("111124"), "hour"].tolist(), [0, 2])
            self.assertEqual(original, hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(panel.attrs["source_files"], ["2017/2017년 01월.xlsx"])

    def test_main_saves_readable_date_and_provenance(self):
        panel = fetch.normalise(raw([row(2017010101)]), CONTROLS, "end", PLAN)
        panel.attrs["source_files"] = ["2017/2017년 01월.xlsx"]
        plan = {"data_sources": [{"name": "에어코리아", "license": "KOGL-3"}]}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "panel.csv"
            with (
                patch.object(fetch, "OUT", output),
                patch.object(fetch, "HERE", Path(directory)),
                patch.object(fetch, "load_plan", return_value=plan),
                patch.object(fetch, "build_panel", return_value=panel),
            ):
                fetch.main()
            saved = pd.read_csv(output)
            self.assertIn("2017-01-01 00:00:00", saved.datetime.iloc[0])
            self.assertEqual(saved.hour_idx.tolist(), [0])
            self.assertEqual(saved.hour.tolist(), [0])
            self.assertEqual(
                json.loads(output.with_suffix(".source.json").read_text())["license"], "KOGL-3"
            )


if __name__ == "__main__":
    unittest.main()
