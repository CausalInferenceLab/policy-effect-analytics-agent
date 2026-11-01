"""Regression contracts for the offline Busan age comparison."""

import contextlib
import copy
import csv
import importlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from test_describe_population import accident_rows, population_rows

LABELS = (
    "합계",
    "19세 이하",
    "20-29세",
    "30-39세",
    "40-49세",
    "50-59세",
    "60-64세",
    "65세 이상",
    "불명",
)
CASE = Path(__file__).resolve().parent


def xml_fixture(years=(2014,), values=None):
    values = values or [31, 1, 2, 3, 4, 5, 6, 7, 3]
    root = ET.Element("OCTAGONDATA")
    page = ET.SubElement(root, "PAGE")
    for tag in ("TOTALPAGE", "CURRENTPAGE", "TOTALPAGEX", "TOTALPAGEY"):
        ET.SubElement(page, tag).text = "1"
    ET.SubElement(root, "TITLE")
    grid = ET.SubElement(root, "GRID")
    tables = {
        "COLSESSION": [[str(y) for y in years]],
        "ROWSESSION": [[x] for x in LABELS],
        "DATASESSION": [[str(v)] * len(years) for v in values],
    }
    for name, rows in tables.items():
        table = ET.Element("TABLE")
        for row in rows:
            tr = ET.SubElement(table, "TR")
            for value in row:
                td = ET.SubElement(tr, "TD", {"code": value} if name != "DATASESSION" else {})
                td.text = value
        ET.SubElement(grid, name).text = ET.tostring(table, encoding="unicode")
    ET.SubElement(root, "GRIDCOMMENT")
    ET.SubElement(root, "ERROR")
    return ET.tostring(root)


class AgeContracts(unittest.TestCase):
    def setUp(self):
        try:
            self.module = importlib.import_module("describe_age")
        except ModuleNotFoundError:
            self.module = None
        self.assertIsNotNone(self.module, "describe_age implementation is required")

    def test_known_under65_is_six_bins_not_total_minus_older(self):
        rows = self.module.parse_age_xml(xml_fixture(), (2014,))
        self.assertEqual(
            rows,
            [
                {
                    "year": 2014,
                    "all_age_count": 31,
                    "under65_count": 21,
                    "age65plus_count": 7,
                    "unknown_count": 3,
                }
            ],
        )
        self.assertNotEqual(rows[0]["under65_count"], 31 - 7)

    def test_parser_rejects_partition_and_period_failures(self):
        raw = xml_fixture()
        variants = [
            raw.replace(b'code="60-64', b'code="60-65'),
            raw.replace(b'code="20-29', b'code="19'),
            raw.replace(b'code="2014"', b'code="2015"'),
            raw.replace(b"&gt;31&lt;", b"&gt;30&lt;"),
            raw.replace(b"&gt;7&lt;", b"&gt;-7&lt;"),
            raw.replace(b"&gt;7&lt;", b"&gt;7.0&lt;"),
            raw.replace(b"&gt;7&lt;", b"&gt;*&lt;"),
            raw.replace(b"<TOTALPAGE>1", b"<TOTALPAGE>2"),
            raw.replace(b"<ERROR />", b"<ERROR>failure</ERROR>"),
            raw.replace(b"</OCTAGONDATA>", b"<MESSAGE>runtime</MESSAGE></OCTAGONDATA>"),
            raw.replace(b"</OCTAGONDATA>", b"<PRIVATE>x</PRIVATE></OCTAGONDATA>"),
        ]
        for value in variants:
            self.assertNotEqual(value, raw, "mutation must alter the XML fixture")
            with self.subTest(value=value[:80]), self.assertRaises(ValueError):
                self.module.parse_age_xml(value, (2014,))
        for label in ("19세 이하", "60-64세", "불명"):
            root = ET.fromstring(raw)
            table = ET.fromstring(root.findtext("./GRID/ROWSESSION"))
            table.remove(next(tr for tr in table if tr[0].get("code") == label))
            root.find("./GRID/ROWSESSION").text = ET.tostring(table, encoding="unicode")
            with self.assertRaises(ValueError):
                self.module.parse_age_xml(ET.tostring(root), (2014,))

    def test_parser_rejects_duplicate_age_and_bad_multiyear_total(self):
        root = ET.fromstring(xml_fixture((2014, 2015)))
        table = ET.fromstring(root.findtext("./GRID/ROWSESSION"))
        table[2][0].set("code", "19세 이하")
        root.find("./GRID/ROWSESSION").text = ET.tostring(table, encoding="unicode")
        with self.assertRaises(ValueError):
            self.module.parse_age_xml(ET.tostring(root), (2014, 2015))
        root = ET.fromstring(xml_fixture((2014, 2015)))
        cols = ET.fromstring(root.findtext("./GRID/COLSESSION"))
        cols[0].insert(0, ET.Element("TD", {"code": "합계"}))
        root.find("./GRID/COLSESSION").text = ET.tostring(cols, encoding="unicode")
        data = ET.fromstring(root.findtext("./GRID/DATASESSION"))
        for tr in data:
            td = ET.Element("TD")
            td.text = "0"
            tr.insert(0, td)
        root.find("./GRID/DATASESSION").text = ET.tostring(data, encoding="unicode")
        with self.assertRaises(ValueError):
            self.module.parse_age_xml(ET.tostring(root), (2014, 2015))

    def synthetic_sources(self):
        return {
            area: [
                {
                    "year": y,
                    "all_age_count": count + 24,
                    "under65_count": 21,
                    "age65plus_count": count,
                    "unknown_count": 3,
                }
                for y, count in zip(range(2014, 2020), (10, 15, 20, 25, 35, 40), strict=False)
            ]
            for area in ("busan", "national")
        }

    def test_equal_age_denominators_and_prior_december(self):
        sources = self.synthetic_sources()
        # National fixture is Busan + 100.
        for _index, row in enumerate(sources["national"]):
            row["age65plus_count"] += 100
            row["all_age_count"] = row["age65plus_count"] + 24
        result = self.module.build_age_series(sources, accident_rows(), population_rows())
        self.assertEqual(len(result), 6)
        self.assertEqual(result[0]["population_reference_date"], "2013-12-31")
        self.assertEqual(result[0]["under65_population"], 900)
        self.assertEqual(result[0]["age65plus_population"], 100)
        self.assertAlmostEqual(result[0]["under65_per_10000"], 21 / 900 * 10000)
        self.assertEqual(result[0]["age65plus_per_10000"], 1000)
        self.assertEqual([r["year"] for r in result if r["population_definition_break"]], [2016])

    def test_population_and_existing_65plus_mismatch_rejected(self):
        sources = self.synthetic_sources()
        for _index, row in enumerate(sources["national"]):
            row["age65plus_count"] += 100
            row["all_age_count"] = row["age65plus_count"] + 24
        bad = copy.deepcopy(sources)
        bad["busan"][0]["age65plus_count"] += 1
        with self.assertRaises(ValueError):
            self.module.build_age_series(bad, accident_rows(), population_rows())
        bad = copy.deepcopy(sources)
        bad["national"].pop()
        with self.assertRaises(ValueError):
            self.module.build_age_series(bad, accident_rows(), population_rows())
        for field, value in [
            ("population", "100"),
            ("reference_date", "2014-12-31"),
            ("region_code", "2611000000"),
            ("population_65plus", "0"),
        ]:
            population = population_rows()
            population[0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.module.build_age_series(sources, accident_rows(), population)

    def test_approved_source_hash_rejects_renamed_national_data(self):
        raw = CASE / "data/raw-age"
        sources = self.module.load_age_sources(raw)
        self.assertEqual(len(sources["busan"]), 6)
        self.assertEqual(sources["busan"][-1]["unknown_count"], 227)
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            for path in raw.glob("*.xml"):
                (directory / path.name).write_bytes(path.read_bytes())
            for period in ("2014-2018", "2019-2019"):
                (directory / f"source-query-busan-{period}.xml").write_bytes(
                    (directory / f"source-query-national-{period}.xml").read_bytes()
                )
            with self.assertRaisesRegex(ValueError, "SHA256"):
                self.module.load_age_sources(directory)

    def test_output_protection_includes_prior_case_and_all_link_aliases(self):
        names = (
            "figures/01_busan_counts.png",
            "figures/02_busan_vs_rest_counts.png",
            "figures/03_busan_counts_and_population.png",
            "descriptive-manifest.json",
            "population-descriptive-manifest.json",
            "data/descriptive-series.csv",
            "data/population-descriptive-series.csv",
            "age-source-manifest.json",
            "data/raw-age/source.xml",
            "population-qc.json",
            "visualization-notes.md",
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            case = root / "case"
            for index, name in enumerate(names):
                source = case / name
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(b"preserve")
                aliases = [source, root / f"sym-{index}", root / f"hard-{index}"]
                aliases[1].symlink_to(source)
                aliases[2].hardlink_to(source)
                for alias in aliases:
                    with (
                        mock.patch.object(self.module, "HERE", case),
                        self.assertRaises(ValueError),
                    ):
                        self.module._validate_output_paths(
                            [], [root / "new.png", alias, root / "new.json"]
                        )
                    self.assertEqual(source.read_bytes(), b"preserve")
            linked_owned = case / "age-descriptive-manifest.json"
            linked_owned.symlink_to(source)
            with mock.patch.object(self.module, "HERE", case), self.assertRaises(ValueError):
                self.module._validate_output_paths(
                    [], [root / "new.png", root / "new.csv", linked_owned]
                )
            for alias in (aliases[0], aliases[1], aliases[2]):
                with self.assertRaises(ValueError):
                    self.module._validate_output_paths([], [source, alias, root / "new.json"])

    def test_existing_external_output_is_not_owned_regeneration(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "existing.csv"
            source.write_bytes(b"preserve external")
            symbolic = root / "symbolic.csv"
            symbolic.symlink_to(source)
            hard = root / "hard.csv"
            hard.hardlink_to(source)
            for target in (source, symbolic, hard):
                with self.subTest(target=target.name), self.assertRaises(ValueError):
                    self.module._validate_output_paths(
                        [], [root / "new.png", target, root / "new.json"]
                    )
                self.assertEqual(source.read_bytes(), b"preserve external")

    def test_fixed_owned_outputs_allow_relative_and_absolute_regeneration(self):
        owned = [
            CASE / "figures" / self.module.FIGURE_NAME,
            CASE / "data/age-descriptive-series.csv",
            CASE / "age-descriptive-manifest.json",
        ]
        self.module._validate_output_paths([], owned)
        self.module._validate_output_paths([], [Path(os.path.relpath(p)) for p in owned])

    def test_dangling_output_symlinks_rejected_without_creating_target(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            case = root / "case"
            case.mkdir()
            target = root / "missing.csv"
            for output in (case / "age-descriptive-manifest.json", root / "nonowned.json"):
                output.symlink_to(target)
                with mock.patch.object(self.module, "HERE", case), self.assertRaises(ValueError):
                    self.module._validate_output_paths(
                        [], [root / "new.png", root / "new.csv", output]
                    )
                self.assertFalse(target.exists())

    def test_cli_rejects_collision_before_creating_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with contextlib.redirect_stderr(io.StringIO()):
                code = self.module.main(
                    [
                        "--series-output",
                        str(CASE / "population-qc.json"),
                        "--output-dir",
                        str(root / "figures"),
                    ]
                )
            self.assertEqual(code, 1)
            self.assertFalse((root / "figures").exists())

    def test_import_without_site_packages(self):
        run = subprocess.run(
            [
                sys.executable,
                "-S",
                "-c",
                "import describe_age; assert 'matplotlib' not in __import__('sys').modules",
            ],
            cwd=CASE,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_offline_cli_manifest_and_full_rows_without_rendering(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            def render(series, path):
                path.write_bytes(b"fixture image")
                return {"backend": "fixture"}

            output = io.StringIO()
            with (
                mock.patch.object(self.module, "_render", side_effect=render),
                contextlib.redirect_stdout(output),
            ):
                code = self.module.main(
                    [
                        "--output-dir",
                        str(root),
                        "--series-output",
                        str(root / "series.csv"),
                        "--manifest-output",
                        str(root / "manifest.json"),
                    ]
                )
            self.assertEqual(code, 0)
            manifest = json.loads((root / "manifest.json").read_text())
            self.assertIs(manifest["analysis_approved"], False)
            self.assertIs(manifest["publication_approved"], False)
            self.assertIs(manifest["descriptive_only"], True)
            with (root / "series.csv").open() as source:
                rows = list(csv.DictReader(source))
            self.assertEqual(len(rows), 6)
            self.assertEqual(list(rows[0]), list(self.module.FIELDS))
            self.assertEqual(len(json.loads(output.getvalue())["series"]), 6)


if __name__ == "__main__":
    unittest.main()
