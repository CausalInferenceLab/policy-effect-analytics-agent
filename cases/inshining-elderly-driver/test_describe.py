"""연간 관측 집계와 입력 보존 계약의 회귀 검사."""

import contextlib
import copy
import io
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

from describe import _command, build_series, main


def complete_rows():
    """합계 두 종류가 모두 있는 6년 fixture; 2016년 지수는 서로 다르다."""
    counts = [
        (2014, 10, 110),
        (2015, 15, 165),
        (2016, 20, 230),
        (2017, 25, 275),
        (2018, 35, 435),
        (2019, 40, 440),
    ]
    return [
        {
            "taas_province": province,
            "taas_district": "합계",
            "year": str(year),
            "older_accidents": str(count),
        }
        for year, busan, national in counts
        for province, count in (("합계", national), ("부산", busan))
    ]


class BuildSeriesTests(unittest.TestCase):
    def test_exact_aggregate_rows_avoid_hierarchy_double_counting(self):
        rows = complete_rows()
        rows.extend(
            [
                {
                    "taas_province": "부산",
                    "taas_district": "중구",
                    "year": "2017",
                    "older_accidents": "99999",
                },
                {
                    "taas_province": "서울",
                    "taas_district": "합계",
                    "year": "2017",
                    "older_accidents": "99999",
                },
                {
                    "taas_province": "합계",
                    "taas_district": "중구",
                    "year": "2017",
                    "older_accidents": "99999",
                },
                {
                    "taas_province": "부산광역시",
                    "taas_district": "합계",
                    "year": "2017",
                    "older_accidents": "99999",
                },
                {
                    "taas_province": "부산",
                    "taas_district": "중구",
                    "year": "bad",
                    "older_accidents": "bad",
                },
            ]
        )
        baseline = build_series(rows)[3]
        self.assertEqual(baseline["busan_count"], 25)
        self.assertEqual(baseline["national_count"], 275)
        self.assertEqual(baseline["rest_count"], 250)

    def test_rest_counts_are_national_minus_busan_for_every_year(self):
        self.assertEqual(
            [row["rest_count"] for row in build_series(complete_rows())],
            [100, 150, 210, 250, 400, 400],
        )

    def test_both_2017_indices_are_100(self):
        baseline = build_series(complete_rows(), base_year=2017)[3]
        self.assertEqual(baseline["busan_index"], 100.0)
        self.assertEqual(baseline["rest_index"], 100.0)

    def test_other_indices_use_each_geographys_own_2017_count(self):
        rows = build_series(complete_rows())
        self.assertAlmostEqual(rows[2]["busan_index"], 80.0)
        self.assertAlmostEqual(rows[2]["rest_index"], 84.0)
        self.assertAlmostEqual(rows[4]["busan_index"], 140.0)
        self.assertAlmostEqual(rows[4]["rest_index"], 160.0)

    def test_output_is_sorted_and_contains_only_contract_fields(self):
        rows = build_series(reversed(complete_rows()))
        self.assertEqual([row["year"] for row in rows], list(range(2014, 2020)))
        expected = {
            "year",
            "busan_count",
            "national_count",
            "rest_count",
            "busan_index",
            "rest_index",
        }
        for row in rows:
            self.assertEqual(set(row), expected)
            for field in ("year", "busan_count", "national_count", "rest_count"):
                self.assertIs(type(row[field]), int)
            self.assertIs(type(row["busan_index"]), float)
            self.assertIs(type(row["rest_index"]), float)

    def test_input_rows_are_not_mutated(self):
        rows = complete_rows()
        original = copy.deepcopy(rows)
        build_series(rows)
        self.assertEqual(rows, original)

    def test_missing_year_in_either_aggregate_is_rejected(self):
        for province in ("합계", "부산"):
            with self.subTest(province=province), self.assertRaises(ValueError):
                build_series(
                    [
                        row
                        for row in complete_rows()
                        if not (row["taas_province"] == province and row["year"] == "2016")
                    ]
                )

    def test_duplicate_year_in_either_aggregate_is_rejected(self):
        for province in ("합계", "부산"):
            rows = complete_rows()
            rows.append(next(row.copy() for row in rows if row["taas_province"] == province))
            with self.subTest(province=province), self.assertRaises(ValueError):
                build_series(rows)

    def test_unexpected_or_non_integer_year_is_rejected(self):
        for value in ("2013", "2020", "2014.0", "", None):
            rows = complete_rows()
            rows[0]["year"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                build_series(rows)

    def test_negative_non_integer_or_missing_count_is_rejected(self):
        for value in ("-1", "2.5", "NaN", "", "1,000", None, 12):
            rows = complete_rows()
            rows[0]["older_accidents"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                build_series(rows)

    def test_national_smaller_than_busan_is_rejected(self):
        rows = complete_rows()
        rows[0]["older_accidents"] = "9"
        with self.assertRaises(ValueError):
            build_series(rows)

    def test_zero_2017_denominator_for_either_series_is_rejected(self):
        for busan, national in (("0", "275"), ("25", "25")):
            rows = complete_rows()
            for row in rows:
                if row["year"] == "2017":
                    row["older_accidents"] = busan if row["taas_province"] == "부산" else national
            with self.subTest(busan=busan, national=national), self.assertRaises(ValueError):
                build_series(rows)

    def test_zero_outside_baseline_is_retained(self):
        rows = complete_rows()
        rows[1]["older_accidents"] = "0"
        first = build_series(rows)[0]
        self.assertEqual(first["busan_count"], 0)
        self.assertEqual(first["busan_index"], 0.0)

    def test_baseline_is_fixed_to_integer_2017(self):
        for value in (2016, 2020, "2017", True, 2017.0, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                build_series(complete_rows(), base_year=value)


class ManifestCommandTests(unittest.TestCase):
    def test_recorded_interpreter_keeps_the_rendering_environment(self):
        interpreter = shlex.split(_command([]))[0]
        self.assertFalse(Path(interpreter).is_absolute())
        result = subprocess.run(
            [interpreter, "-B", "-c", "import matplotlib; print(matplotlib.__version__)"],
            cwd=Path(__file__).resolve().parents[2],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip())


class OutputProtectionTests(unittest.TestCase):
    def test_cli_refuses_each_destination_that_would_overwrite_input(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "01_busan_counts.png"
            original = b"preserve source without attempting to parse"
            source.write_bytes(original)
            for flag, destination in (
                ("--series-output", source),
                ("--manifest-output", source),
                ("--output-dir", root),
            ):
                with self.subTest(flag=flag):
                    stderr = io.StringIO()
                    with contextlib.redirect_stderr(stderr):
                        code = main(["--input", str(source), flag, str(destination)])
                    self.assertEqual(code, 1)
                    self.assertIn("입력", stderr.getvalue())
                    self.assertEqual(source.read_bytes(), original)

    def test_cli_resolves_symlinks_before_input_overwrite_check(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.csv"
            source.write_bytes(b"preserve original")
            alias = root / "alias.csv"
            alias.symlink_to(source)
            with contextlib.redirect_stderr(io.StringIO()):
                code = main(["--input", str(source), "--series-output", str(alias)])
            self.assertEqual(code, 1)
            self.assertEqual(source.read_bytes(), b"preserve original")

    def test_cli_rejects_hardlink_to_input_before_parsing_or_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.csv"
            source.write_bytes(b"preserve original")
            alias = root / "alias.csv"
            alias.hardlink_to(source)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = main(["--input", str(source), "--series-output", str(alias)])
            self.assertEqual(code, 1)
            self.assertIn("입력 원본을 출력으로 덮어쓸 수 없습니다", stderr.getvalue())
            self.assertEqual(source.read_bytes(), b"preserve original")


if __name__ == "__main__":
    unittest.main()
