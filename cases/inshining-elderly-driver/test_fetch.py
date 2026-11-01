"""Acquisition boundary tests use synthetic public responses, never a network replay."""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def load_fetch():
    path = HERE / "fetch.py"
    if not path.exists():
        raise AssertionError("portable fetch entrypoint has not been implemented")
    spec = importlib.util.spec_from_file_location("case_fetch", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def response(years):
    root = ET.Element("OCTAGONDATA")
    page = ET.SubElement(root, "PAGE")
    for key in ("TOTALPAGE", "CURRENTPAGE", "TOTALPAGEX", "TOTALPAGEY"):
        ET.SubElement(page, key).text = "1"
    ET.SubElement(root, "TITLE")
    grid = ET.SubElement(root, "GRID")
    labels = (
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
    for key in ("COLSESSION", "ROWSESSION", "DATASESSION"):
        table = ET.Element("TABLE")
        if key == "COLSESSION":
            row = ET.SubElement(table, "TR")
            for year in years:
                ET.SubElement(row, "TD", code=str(year)).text = str(year)
        else:
            for index, label in enumerate(labels):
                row = ET.SubElement(table, "TR")
                if key == "ROWSESSION":
                    ET.SubElement(row, "TD", code=label).text = label
                else:
                    for _ in years:
                        ET.SubElement(row, "TD").text = str(8 if index == 0 else 1)
        ET.SubElement(grid, key).text = ET.tostring(table, encoding="unicode")
    ET.SubElement(root, "GRIDCOMMENT")
    ET.SubElement(root, "ERROR")
    ET.SubElement(root, "MESSAGE").text = "/private/runtime.err"
    ET.SubElement(root, "CUBEKEY").text = "transient-token"
    return ET.tostring(root)


class FakeClient:
    def __init__(self, module, fail=0, metadata_change=None):
        self.module = module
        self.fail = fail
        self.calls = []
        self.metadata_change = metadata_change

    def session(self, start, end):
        self.years = tuple(range(start, end + 1))
        self.calls.append(("session", start, end))
        return {}, {"lic": "must-not-persist"}

    def metadata(self, mode, **params):
        self.calls.append((mode, params))
        if mode == "loadPattern":
            result = {
                "PatternId": 7125,
                "SubjectId": 131,
                "Parameter": self.module.PATTERN_TEMPLATE,
            }
        elif mode == "getDimensionItems":
            result = [
                {"DimAttrId": k, "LogColName": v[0], "PhyColName": v[1]}
                for k, v in self.module.DIMENSIONS.items()
            ]
        elif mode == "getMeasureItems":
            result = [
                {
                    "MeaId": 334,
                    "SubjectId": 131,
                    "LogColName": "사고[건]",
                    "PhyColName": "ACC_CNT",
                    "AggFunc": "SUM",
                }
            ]
        else:
            labels = (
                self.module.AGE_LABELS[1:]
                if params["dimAttrId"] == 2736
                else [str(y) for y in range(2014, 2020)]
            )
            result = [{"TotalPage": 1, "PageNo": 1}] + [
                {"ElementCode": x, "ElementName": x} for x in labels
            ]
        return self.metadata_change(mode, params, result) if self.metadata_change else result

    def query(self, params, handshake):
        self.calls.append(("query", params))
        if sum(c[0] == "query" for c in self.calls) == self.fail:
            return b"<OCTAGONDATA><ERROR>public query failed</ERROR></OCTAGONDATA>"
        return response(self.years)


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.fetch = load_fetch()

    def test_four_queries_bind_public_age_year_measure_and_area(self):
        client = FakeClient(self.fetch)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp).resolve() / "new"
            manifest = self.fetch.download_age(output, client)
            self.assertEqual(len(manifest["sources"]), 4)
            self.assertEqual(manifest["acquisition_kind"], "fresh_age_public_query")
            self.assertFalse(manifest["historical_byte_identity_promised"])
            self.assertEqual(manifest["review_status"], "pending")
            self.assertEqual(len(list(output.glob("*.xml"))), 4)
            for entry in manifest["sources"]:
                params = entry["public_parameters"]
                for value in (':row_list="2736"', ':col_list="888"', ':mea_list="334"'):
                    self.assertIn(value, params)
                self.assertEqual("D906@|" in params, entry["area"] == "busan")
                raw = (output / entry["file"]).read_bytes()
                self.assertNotIn(b"MESSAGE", raw)
                self.assertNotIn(b"private", raw)
                self.assertNotIn(b"transient-token", raw)
                self.assertEqual(entry["sha256"], self.fetch.sha256(raw))
            body = (output / "fresh-age-manifest.json").read_text()
            self.assertNotIn("must-not-persist", body)
            self.assertNotIn(str(Path(tmp).resolve()), body)
            self.assertIn("metadata", manifest)

    def test_partial_failure_persists_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp).resolve() / "new"
            with self.assertRaises(ValueError):
                self.fetch.download_age(output, FakeClient(self.fetch, fail=4))
            self.assertFalse(output.exists())

    def test_existing_directory_file_and_link_refused_before_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            existing = base / "existing"
            existing.mkdir()
            marker = existing / "preserve"
            marker.write_text("unchanged")
            target = base / "file"
            target.write_text("original")
            link = base / "link"
            link.symlink_to(existing, target_is_directory=True)
            hardlink = base / "hardlink"
            os.link(target, hardlink)
            for output in (existing, target, link, hardlink):
                client = FakeClient(self.fetch)
                with self.subTest(output=output), self.assertRaises((ValueError, FileExistsError)):
                    self.fetch.download_age(output, client)
                self.assertEqual(client.calls, [])
            self.assertEqual(marker.read_text(), "unchanged")
            self.assertEqual(target.read_text(), "original")

    def test_symlink_parent_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            (base / "real").mkdir()
            (base / "alias").symlink_to(base / "real", target_is_directory=True)
            with self.assertRaises(ValueError):
                self.fetch.download_age(base / "alias" / "new", FakeClient(self.fetch))
            self.assertFalse((base / "real" / "new").exists())

    def test_changed_measure_metadata_refused(self):
        def change(mode, params, result):
            if mode == "getMeasureItems":
                result[0]["LogColName"] = "사망[명]"
            return result

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp).resolve() / "new"
            with self.assertRaises(ValueError):
                self.fetch.download_age(output, FakeClient(self.fetch, metadata_change=change))
            self.assertFalse(output.exists())

    def test_nonempty_extra_filter_in_template_refused(self):
        pattern = {
            "PatternId": 7125,
            "SubjectId": 131,
            "Parameter": self.fetch.PATTERN_TEMPLATE.replace(':filter=""', ':filter="narrower"'),
        }
        with self.assertRaises(ValueError):
            self.fetch.build_age_parameters(pattern, 2014, 2018, "busan")

    def test_projection_refuses_error_missing_year_and_bad_partition(self):
        years = tuple(range(2014, 2019))
        for mutate in ("error", "year", "age", "total", "nested_runtime"):
            root = ET.fromstring(response(years))
            if mutate == "error":
                root.find("ERROR").text = "failure"
            elif mutate == "year":
                root.find("./GRID/COLSESSION").text = root.find("./GRID/COLSESSION").text.replace(
                    "2014", "2013"
                )
            elif mutate == "age":
                root.find("./GRID/ROWSESSION").text = root.find("./GRID/ROWSESSION").text.replace(
                    "60-64세", "60세 이상"
                )
            elif mutate == "total":
                root.find("./GRID/DATASESSION").text = root.find("./GRID/DATASESSION").text.replace(
                    ">8<", ">9<"
                )
            else:
                ET.SubElement(root.find("GRID"), "MESSAGE").text = "/private/runtime.err"
            with self.subTest(mutate=mutate), self.assertRaises(ValueError):
                self.fetch.project_age_xml(ET.tostring(root), years)

    def test_offline_reconciles_actual_parser_dictionary_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            case = Path(tmp).resolve()
            (case / "data/raw").mkdir(parents=True)
            sources = []
            for start, end in self.fetch.BATCHES:
                years = tuple(range(start, end + 1))
                for page in (1, 2):
                    root = ET.fromstring(response(years))
                    root.find("./PAGE/TOTALPAGE").text = "2"
                    root.find("./PAGE/CURRENTPAGE").text = str(page)
                    comment = ET.SubElement(root.find("GRIDCOMMENT"), "PATTERNCOMMENT")
                    comment.text = self.fetch.taas.DEFINITION
                    labels = (
                        [("합계", "합계"), ("부산", "합계")]
                        if page == 1
                        else [("부산", "부산진구")]
                    )
                    for key in ("ROWSESSION", "DATASESSION"):
                        table = ET.Element("TABLE")
                        for label in labels:
                            row = ET.SubElement(table, "TR")
                            if key == "ROWSESSION":
                                for name in label:
                                    ET.SubElement(row, "TD", code=name).text = name
                            else:
                                for year in years:
                                    ET.SubElement(row, "TD").text = str(
                                        self.fetch.taas.NATIONAL_REFERENCE[year]
                                    )
                        root.find("./GRID/" + key).text = ET.tostring(table, encoding="unicode")
                    raw = ET.tostring(root)
                    name = f"data/raw/taas-{start}-{end}-page-{page}.xml"
                    (case / name).write_bytes(raw)
                    sources.append({"file": name, "sha256": self.fetch.sha256(raw)})
            (case / "taas-qc.json").write_text(json.dumps({"sources": sources}))
            sources = []
            for year in range(2013, 2019):
                name = f"data/raw/population-{year}-12.csv"
                (case / name).write_bytes(b"population fixture boundary")
                sources.append(
                    {"path": name, "sha256": self.fetch.sha256((case / name).read_bytes())}
                )
            (case / "population-qc.json").write_text(json.dumps({"sources": sources}))
            with (
                patch.object(self.fetch.population, "inspect_population"),
                patch.object(self.fetch, "load_age_sources"),
                patch.object(
                    self.fetch.taas, "PublicClient", side_effect=AssertionError("network")
                ),
            ):
                result = self.fetch.offline_check(case)
            self.assertEqual(result["network_requests"], 0)
            self.assertEqual(result["writes"], 0)

    def test_default_offline_path_has_no_network_or_writes(self):
        with (
            patch.object(
                self.fetch, "offline_check", return_value={"mode": "offline_check"}
            ) as check,
            patch.object(self.fetch, "download_age", side_effect=AssertionError("network path")),
        ):
            self.assertEqual(self.fetch.main([]), 0)
            check.assert_called_once_with(HERE)

    def test_download_requires_age_only_and_new_output(self):
        for args in (
            ["--download"],
            ["--download", "--output-dir", "new"],
            ["--age-only"],
            ["--output-dir", "new"],
        ):
            with self.subTest(args=args), self.assertRaises(SystemExit):
                self.fetch.main(args)

    def test_offline_missing_raw_has_actionable_error(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            self.assertRaisesRegex(FileNotFoundError, "historical|기존|원본"),
        ):
            self.fetch.offline_check(Path(tmp).resolve())

    def test_cli_help_is_portable(self):
        result = subprocess.run(
            [sys.executable, str(HERE / "fetch.py"), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--age-only", result.stdout)
        self.assertIn("--download", result.stdout)


if __name__ == "__main__":
    unittest.main()
