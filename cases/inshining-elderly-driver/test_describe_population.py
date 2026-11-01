"""직전 12월 주민등록인구 분모와 출력 보존 계약의 회귀 검사."""

import contextlib
import copy
import csv
import importlib
import io
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def accident_rows():
    return [
        {
            "taas_province": province,
            "taas_district": "합계",
            "year": str(year),
            "older_accidents": str(count),
        }
        for year, busan in zip(range(2014, 2020), (10, 15, 20, 25, 35, 40), strict=False)
        for province, count in (("부산", busan), ("합계", busan + 100))
    ]


def population_rows():
    return [
        {
            "reference_year": str(year - 1),
            "reference_date": f"{year - 1}-12-31",
            "outcome_year": str(year),
            "region_code": "2600000000",
            "region_name": "부산광역시",
            "source_label": "부산광역시 (2600000000)",
            "province_code": "2600000000",
            "province_name": "부산광역시",
            "population": str(1000 + offset * 100),
            "population_65plus": str(100 + offset * 20),
            "is_province_total": "True",
            "overlapping_city_total": "False",
            "is_aggregate": "True",
        }
        for offset, year in enumerate(range(2014, 2020))
    ]


class PopulationSeriesTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(
            Path(__file__).with_name("describe_population.py").is_file(),
            "population-normalized descriptive module is not implemented",
        )
        self.build = importlib.import_module("describe_population").build_population_series

    def test_two_frequencies_use_the_same_older_accident_numerator(self):
        result = self.build(accident_rows(), population_rows())
        for row, source in zip(result, population_rows(), strict=False):
            self.assertEqual(
                row["per_10000_65plus"],
                row["busan_count"] / int(source["population_65plus"]) * 10000,
            )
            self.assertEqual(
                row["per_10000_total"], row["busan_count"] / int(source["population"]) * 10000
            )
        self.assertEqual(result[0]["per_10000_65plus"], 1000.0)
        self.assertEqual(result[0]["per_10000_total"], 100.0)

    def test_only_exact_province_total_is_used_without_district_double_counting(self):
        extras = [
            dict(
                population_rows()[0],
                region_code="2611000000",
                region_name="부산광역시 중구",
                is_province_total="False",
                is_aggregate="False",
                population="9999999",
                population_65plus="9999999",
            ),
            dict(
                population_rows()[0],
                region_code="1100000000",
                region_name="서울특별시",
                province_code="1100000000",
                province_name="서울특별시",
                population="9999999",
                population_65plus="9999999",
            ),
        ]
        self.assertEqual(
            self.build(accident_rows(), population_rows() + extras),
            self.build(accident_rows(), population_rows()),
        )

    def test_order_independent_sorted_output_and_exact_types(self):
        result = self.build(reversed(accident_rows()), reversed(population_rows()))
        self.assertEqual(result, self.build(accident_rows(), population_rows()))
        self.assertEqual([row["year"] for row in result], list(range(2014, 2020)))
        expected = {
            "year",
            "busan_count",
            "population_reference_date",
            "population_65plus",
            "population_total",
            "per_10000_65plus",
            "per_10000_total",
            "population_definition_break",
        }
        for row in result:
            self.assertEqual(set(row), expected)
            for field in ("year", "busan_count", "population_65plus", "population_total"):
                self.assertIs(type(row[field]), int)
            for field in ("per_10000_65plus", "per_10000_total"):
                self.assertIs(type(row[field]), float)
            self.assertIs(type(row["population_definition_break"]), bool)
            self.assertIs(type(row["population_reference_date"]), str)

    def test_definition_break_is_first_affected_outcome_year_only(self):
        result = self.build(accident_rows(), population_rows())
        self.assertEqual(
            [row["population_definition_break"] for row in result],
            [False, False, True, False, False, False],
        )
        self.assertEqual(
            [row["population_reference_date"] for row in result],
            [f"{year}-12-31" for year in range(2013, 2019)],
        )

    def test_inputs_are_not_mutated(self):
        accidents, population = accident_rows(), population_rows()
        original = copy.deepcopy((accidents, population))
        self.build(accidents, population)
        self.assertEqual((accidents, population), original)

    def test_missing_and_duplicate_province_years_are_rejected(self):
        for rows in (population_rows()[:-1], population_rows() + population_rows()[:1]):
            with self.subTest(rows=len(rows)), self.assertRaises(ValueError):
                self.build(accident_rows(), rows)

    def test_wrong_reference_year_and_date_are_rejected(self):
        for field, value in (
            ("reference_year", "2014"),
            ("reference_year", "2013.0"),
            ("reference_date", "2013-12-30"),
            ("reference_date", "2013-11-30"),
            ("reference_date", "2014-12-31"),
            ("reference_date", "2013-2-31"),
        ):
            rows = population_rows()
            rows[0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.build(accident_rows(), rows)

    def test_outcome_year_outside_range_or_noninteger_is_rejected(self):
        for value in ("2013", "2020", "2014.0", "", "-2014"):
            rows = population_rows()
            rows[0]["outcome_year"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.build(accident_rows(), rows)

    def test_wrong_code_name_or_hierarchy_flags_are_rejected(self):
        for field, value in (
            ("region_code", "2611000000"),
            ("region_name", "부산광역시 중구"),
            ("province_code", "1100000000"),
            ("province_name", "서울특별시"),
            ("is_province_total", "False"),
            ("is_province_total", "true"),
            ("is_aggregate", "False"),
            ("overlapping_city_total", "True"),
        ):
            rows = population_rows()
            rows[0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                self.build(accident_rows(), rows)

    def test_noninteger_negative_missing_and_zero_populations_are_rejected(self):
        for field in ("population", "population_65plus"):
            for value in ("-1", "1.5", "1,000", "", None, 100, "0"):
                rows = population_rows()
                rows[0][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.build(accident_rows(), rows)

    def test_older_population_cannot_exceed_total(self):
        rows = population_rows()
        rows[0]["population_65plus"] = "1001"
        with self.assertRaises(ValueError):
            self.build(accident_rows(), rows)

    def test_strict_existing_accident_validation_is_preserved(self):
        for rows in (accident_rows()[:-1], accident_rows() + accident_rows()[:1]):
            with self.subTest(rows=len(rows)), self.assertRaises(ValueError):
                self.build(rows, population_rows())


class PopulationCliTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("describe_population")
        self.assertTrue(hasattr(self.module, "main"), "population CLI is not implemented")

    def call(self, arguments):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = self.module.main(arguments)
        return code, stderr.getvalue()

    def arguments(self, root, accidents, population):
        return [
            "--accidents",
            str(accidents),
            "--population",
            str(population),
            "--output-dir",
            str(root / "figures"),
            "--series-output",
            str(root / "series.csv"),
            "--manifest-output",
            str(root / "manifest.json"),
        ]

    def test_all_output_kinds_refuse_either_input_before_parsing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for input_flag in ("--accidents", "--population"):
                for output_flag in ("--series-output", "--manifest-output", "--output-dir"):
                    with self.subTest(input_flag=input_flag, output_flag=output_flag):
                        source = root / "03_busan_counts_and_population.png"
                        source.write_bytes(b"preserve malformed input")
                        arguments = self.arguments(root, root / "accidents", root / "population")
                        arguments[arguments.index(input_flag) + 1] = str(source)
                        destination = root if output_flag == "--output-dir" else source
                        arguments[arguments.index(output_flag) + 1] = str(destination)
                        code, error = self.call(arguments)
                        self.assertEqual(code, 1)
                        self.assertIn("입력·코드", error)
                        self.assertEqual(source.read_bytes(), b"preserve malformed input")
                        self.assertFalse((root / "figures").exists())

    def test_symlink_and_hardlink_to_input_are_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.csv"
            source.write_bytes(b"preserve input")
            for kind in ("symlink", "hardlink"):
                with self.subTest(kind=kind):
                    alias = root / f"{kind}.csv"
                    if kind == "symlink":
                        alias.symlink_to(source)
                    else:
                        alias.hardlink_to(source)
                    arguments = self.arguments(root, source, root / "population.csv")
                    arguments[arguments.index("--series-output") + 1] = str(alias)
                    code, error = self.call(arguments)
                    self.assertEqual(code, 1)
                    self.assertIn("입력·코드", error)
                    self.assertEqual(source.read_bytes(), b"preserve input")
                    self.assertFalse((root / "figures").exists())

    def test_outputs_cannot_alias_each_other_including_links(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = root / "series.csv"
            first.write_bytes(b"preserve existing output")
            destinations = [first, root / "symbolic.csv", root / "hard.csv"]
            destinations[1].symlink_to(first)
            destinations[2].hardlink_to(first)
            for destination in destinations:
                with self.subTest(destination=destination.name):
                    arguments = self.arguments(root, root / "accidents", root / "population")
                    arguments[arguments.index("--manifest-output") + 1] = str(destination)
                    code, error = self.call(arguments)
                    self.assertEqual(code, 1)
                    self.assertIn("출력 파일", error)
                    self.assertEqual(first.read_bytes(), b"preserve existing output")
                    self.assertFalse((root / "figures").exists())

    def test_output_must_not_alias_module_or_dependency_code(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            case = Path(__file__).parent
            for name in ("describe_population.py", "describe.py", "test_describe_population.py"):
                with self.subTest(name=name):
                    source = case / name
                    original = source.read_bytes()
                    alias = root / name
                    alias.symlink_to(source)
                    arguments = self.arguments(root, root / "accidents", root / "population")
                    arguments[arguments.index("--series-output") + 1] = str(alias)
                    code, error = self.call(arguments)
                    self.assertEqual(code, 1)
                    self.assertIn("입력·코드", error)
                    self.assertEqual(source.read_bytes(), original)

    def test_command_preserves_virtual_environment_interpreter_symlink_path(self):
        root = Path(__file__).resolve().parents[2]
        interpreter = root / ".local/submissions/policy-effect-analytics-agent/.venv/bin/python"
        with mock.patch.object(sys, "executable", str(interpreter)):
            command = self.module._command(
                ["--accidents", str(root / "counts.csv"), "--population=population.csv"]
            )
        self.assertEqual(
            shlex.split(command)[0],
            ".local/submissions/policy-effect-analytics-agent/.venv/bin/python",
        )
        self.assertIn("--accidents counts.csv", command)
        self.assertIn("--population=population.csv", command)
        self.assertNotIn(str(root), command)

    def test_csv_bom_inputs_and_local_draft_manifest_without_rendering(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            inputs = (root / "accidents.csv", root / "population.csv")
            for path, rows in zip(inputs, (accident_rows(), population_rows()), strict=False):
                with path.open("w", encoding="utf-8-sig", newline="") as output:
                    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
                    writer.writeheader()
                    writer.writerows(rows)

            def render(series, path):
                self.assertEqual(len(series), 6)
                path.write_bytes(b"synthetic renderer output")
                return {"matplotlib_version": "fixture"}

            with (
                mock.patch.object(self.module, "_render", side_effect=render),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                code, error = self.call(self.arguments(root, *inputs))
            self.assertEqual(code, 0, error)
            import json

            manifest = json.loads((root / "manifest.json").read_text())
            self.assertIs(manifest["descriptive_only"], True)
            self.assertIs(manifest["analysis_approved"], False)
            self.assertIs(manifest["publication_approved"], False)
            self.assertEqual(len(manifest["inputs"]), 2)
            self.assertEqual(len(manifest["outputs"]), 2)
            self.assertEqual(manifest["population_definition_break"]["first_outcome_year"], 2016)
            with (root / "series.csv").open(newline="") as source:
                result = list(csv.DictReader(source))
            self.assertEqual(len(result), 6)
            self.assertEqual(result[0]["population_reference_date"], "2013-12-31")
            self.assertEqual(float(result[0]["per_10000_65plus"]), 1000.0)


class PopulationImportTests(unittest.TestCase):
    def test_pure_api_imports_without_site_packages(self):
        result = subprocess.run(
            [
                sys.executable,
                "-S",
                "-c",
                "import describe_population; assert 'matplotlib' not in __import__('sys').modules",
            ],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class PriorArtifactProtectionTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("describe_population")

    def test_every_prior_case_artifact_rejects_direct_symlink_and_hardlink_outputs(self):
        prior_names = (
            "figures/01_busan_counts.png",
            "figures/02_busan_vs_rest_counts.png",
            "descriptive-manifest.json",
            "data/descriptive-series.csv",
            "data/raw/original.csv",
            "data/population.csv",
            "taas-qc.json",
            "population-qc.json",
            "visualization-notes.md",
            "policy-evidence.json",
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            case = root / "case"
            for offset, name in enumerate(prior_names):
                source = case / name
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(b"preserve prior artifact")
                symbolic, hard = root / f"symbolic-{offset}", root / f"hard-{offset}"
                symbolic.symlink_to(source)
                hard.hardlink_to(source)
                for destination in (source, symbolic, hard):
                    with self.subTest(name=name, destination=destination.name):
                        with (
                            mock.patch.object(self.module, "HERE", case),
                            self.assertRaises(ValueError),
                        ):
                            self.module._validate_output_paths(
                                [root / "accidents", root / "population"],
                                [root / "new.png", destination, root / "new-manifest.json"],
                            )
                        self.assertEqual(source.read_bytes(), b"preserve prior artifact")

    def test_only_three_fixed_owned_paths_may_be_regenerated(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            case = root / "case"
            owned = [
                case / "figures/03_busan_counts_and_population.png",
                case / "data/population-descriptive-series.csv",
                case / "population-descriptive-manifest.json",
            ]
            for path in owned:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"owned artifact may be regenerated")
            with mock.patch.object(self.module, "HERE", case):
                self.module._validate_output_paths([root / "accidents", root / "population"], owned)
                self.module._validate_output_paths(
                    [root / "accidents", root / "population"],
                    [root / "replay.png", root / "replay.csv", root / "replay.json"],
                )

    def test_owned_filename_does_not_authorize_overwriting_linked_nonowned_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "nonowned-source.csv"
            source.write_bytes(b"preserve external link target")
            for kind in ("symlink", "hardlink"):
                with self.subTest(kind=kind):
                    case = root / kind
                    case.mkdir()
                    owned = case / "population-descriptive-manifest.json"
                    if kind == "symlink":
                        owned.symlink_to(source)
                    else:
                        owned.hardlink_to(source)
                    with (
                        mock.patch.object(self.module, "HERE", case),
                        self.assertRaises(ValueError),
                    ):
                        self.module._validate_output_paths(
                            [root / "accidents", root / "population"],
                            [root / "new.png", root / "new.csv", owned],
                        )
                    self.assertEqual(source.read_bytes(), b"preserve external link target")

    def test_actual_prior_production_artifacts_are_validator_only_protected(self):
        case = Path(__file__).parent
        targets = [
            case / name
            for name in (
                "figures/01_busan_counts.png",
                "figures/02_busan_vs_rest_counts.png",
                "descriptive-manifest.json",
                "data/descriptive-series.csv",
                "data/raw/population-2013-12.csv",
                "visualization-notes.md",
            )
        ]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for target in targets:
                with self.subTest(target=target.name):
                    original = target.read_bytes()
                    with self.assertRaises(ValueError):
                        self.module._validate_output_paths(
                            [case / "data/taas-national.csv", case / "data/population.csv"],
                            [root / "new.png", target, root / "new.json"],
                        )
                    self.assertEqual(target.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
