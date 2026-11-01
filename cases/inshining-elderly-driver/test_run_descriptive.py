"""Offline report, provenance and before-write protection regressions."""

import copy
import hashlib
import importlib
import json
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class ReplayContracts(unittest.TestCase):
    def setUp(self):
        self.assertTrue(
            Path(__file__).with_name("run_descriptive.py").is_file(),
            "offline report runner implementation is required",
        )
        self.module = importlib.import_module("run_descriptive")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.case = Path(self.temp.name) / "cases/example"
        self.case.mkdir(parents=True)
        self.inputs = self.case / "input.csv"
        self.inputs.write_text("input")
        self.outputs = [
            self.case / name for name in ("report.md", "flow_log.json", "run_manifest.json")
        ]

    def test_fixed_owned_outputs_can_be_regenerated(self):
        for path in self.outputs:
            path.write_text("old")
        self.module.validate_outputs(self.case, [self.inputs], self.outputs)

    def test_all_other_existing_files_are_protected(self):
        other = self.case / "notes.md"
        other.write_text("preserve")
        for candidate in (self.inputs, other, self.case / "report.md/../input.csv"):
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                self.module.validate_outputs(
                    self.case, [self.inputs], [candidate, *self.outputs[1:]]
                )
        outside = Path(self.temp.name) / "outside.md"
        outside.write_text("preserve")
        with self.assertRaises(ValueError):
            self.module.validate_outputs(self.case, [self.inputs], [outside, *self.outputs[1:]])

    def test_own_output_symlinks_and_hardlinks_are_rejected(self):
        self.outputs[0].symlink_to(self.inputs)
        with self.assertRaises(ValueError):
            self.module.validate_outputs(self.case, [self.inputs], self.outputs)
        self.outputs[0].unlink()
        os.link(self.inputs, self.outputs[0])
        with self.assertRaises(ValueError):
            self.module.validate_outputs(self.case, [self.inputs], self.outputs)

    def test_output_aliases_and_ancestor_symlinks_are_rejected(self):
        with self.assertRaises(ValueError):
            self.module.validate_outputs(self.case, [self.inputs], [self.outputs[0]] * 3)
        link = Path(self.temp.name) / "alias"
        link.symlink_to(self.case, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.module.validate_outputs(
                self.case, [self.inputs], [link / "new.md", *self.outputs[1:]]
            )

    def test_dangling_symlink_and_output_ancestor_conflicts_are_rejected(self):
        self.outputs[0].symlink_to(self.case / "missing-target")
        with self.assertRaises(ValueError):
            self.module.validate_outputs(self.case, [self.inputs], self.outputs)
        self.outputs[0].unlink()
        nested = [self.case / "new-path", self.case / "new-path/flow.json", self.outputs[2]]
        with self.assertRaises(ValueError):
            self.module.validate_outputs(self.case, [self.inputs], nested)

    def test_new_temporary_outputs_are_allowed(self):
        out = Path(self.temp.name) / "fresh"
        self.module.validate_outputs(self.case, [self.inputs], [out / p.name for p in self.outputs])

    def test_manifest_rejects_missing_tampered_and_unapproved_records(self):
        root = Path(self.temp.name)
        entry = {
            "path": str(self.inputs.relative_to(root)),
            "sha256": hashlib.sha256(self.inputs.read_bytes()).hexdigest(),
        }
        manifest = {
            "descriptive_only": True,
            "analysis_approved": False,
            "input": entry,
            "outputs": [entry],
        }
        path = self.case / "fixture-manifest.json"
        path.write_text(json.dumps(manifest))
        self.module.verify_manifest(root, path, [self.inputs])
        for mutation in ("tamper", "missing", "unapproved", "traversal"):
            altered = copy.deepcopy(manifest)
            if mutation == "tamper":
                altered["input"]["sha256"] = "0" * 64
            elif mutation == "missing":
                altered["outputs"] = []
            elif mutation == "unapproved":
                altered["analysis_approved"] = True
            else:
                altered["input"]["path"] = "../escape"
            path.write_text(json.dumps(altered))
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.module.verify_manifest(root, path, [self.inputs])
        self.inputs.unlink()
        path.write_text(json.dumps(manifest))
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.module.verify_manifest(root, path, [self.inputs])

    def test_numeric_rows_unknown_preservation_and_no_effects_contract(self):
        rows = [
            {
                "year": y,
                "busan_count": 10,
                "national_count": 110,
                "rest_count": 100,
                "population_65plus": 100,
                "population_total": 1000,
                "per_10000_65plus": 1000.0,
                "under65_count": 21,
                "unknown_count": 3,
                "under65_population": 900,
                "under65_per_10000": 21 / 900 * 10000,
            }
            for y in range(2014, 2020)
        ]
        payload = self.module.make_descriptive(rows)
        self.module.validate_descriptive(payload)
        self.assertEqual(payload["rows"][0]["unknown_count"], 3)
        self.assertEqual(payload["rows"][0]["under65_count"], 21)
        flow = self.module.make_flow(payload, "2026-11-01T00:00:00+00:00")
        self.assertEqual(flow["results"], [])
        self.assertEqual(flow["execution_kind"], "descriptive_only")
        self.assertEqual(flow["causal_estimation"], "not_run")
        self.assertEqual(flow["verdict"], "not_identified")
        self.assertFalse(
            any(s["step"] in ("estimate", "refute", "estimator") for s in flow["steps"])
        )
        for field, value in (
            ("unknown_count", "3"),
            ("per_10000_65plus", math.nan),
            ("year", True),
        ):
            bad = copy.deepcopy(payload)
            bad["rows"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.module.validate_descriptive(bad)
        bad = copy.deepcopy(payload)
        bad["rows"][0]["estimate"] = -1
        with self.assertRaises(ValueError):
            self.module.validate_descriptive(bad)

    def test_csv_recalculation_rejects_unknown_reallocation_and_wrong_totals(self):
        path = self.case / "series.csv"
        expected = [{"year": 2014, "under65_count": 21, "unknown_count": 3, "rate": 2.5}]
        path.write_text("year,under65_count,unknown_count,rate\n2014,21,3,2.5\n")
        self.module.verify_csv(path, expected)
        for text in ("2014,24,0,2.5", "2014,21,3,3.5"):
            path.write_text("year,under65_count,unknown_count,rate\n" + text + "\n")
            with self.assertRaises(ValueError):
                self.module.verify_csv(path, expected)

    def test_custom_output_manifest_records_sanitized_actual_invocation(self):
        rows = [
            {
                "year": y,
                "busan_count": 10,
                "national_count": 110,
                "rest_count": 100,
                "population_65plus": 100,
                "population_total": 1000,
                "per_10000_65plus": 1000.0,
                "under65_count": 21,
                "unknown_count": 3,
                "under65_population": 900,
                "under65_per_10000": 21 / 900 * 10000,
            }
            for y in range(2014, 2020)
        ]
        study = {
            "rows": rows,
            "descriptive": self.module.make_descriptive(rows),
            "inputs": [self.inputs],
            "verification": ["synthetic fixture"],
        }
        with tempfile.TemporaryDirectory() as outside:
            outputs = [Path(outside) / p.name for p in self.outputs]
            args = [
                flag
                for pair in zip(
                    ("--report-output", "--flow-output", "--manifest-output"),
                    map(str, outputs),
                    strict=False,
                )
                for flag in pair
            ]
            with (
                mock.patch.object(self.module, "HERE", self.case),
                mock.patch.object(self.module, "verify_study", return_value=study),
            ):
                result = self.module.main(args)
            self.assertEqual(result, 0)
            text = outputs[2].read_text()
            manifest = json.loads(text)
            self.assertIn("--report-output", manifest["command"])
            self.assertIn("--flow-output", manifest["command"])
            self.assertNotEqual(manifest["command"], self.module.COMMAND)
            self.assertEqual(manifest["canonical_reproduction_command"], self.module.COMMAND)
            self.assertTrue(manifest["invocation"]["external_output_paths_redacted"])
            self.assertNotIn(outside, text)
            self.assertNotIn(str(self.case), text)
            self.assertEqual(
                manifest["invocation"]["arguments"][::2],
                ["--report-output", "--flow-output", "--manifest-output"],
            )

    def test_relative_custom_outputs_keep_repository_directories_and_hashes(self):
        rows = [
            {
                "year": y,
                "busan_count": 10,
                "national_count": 110,
                "rest_count": 100,
                "population_65plus": 100,
                "population_total": 1000,
                "per_10000_65plus": 1000.0,
                "under65_count": 21,
                "unknown_count": 3,
                "under65_population": 900,
                "under65_per_10000": 21 / 900 * 10000,
            }
            for y in range(2014, 2020)
        ]
        study = {
            "rows": rows,
            "descriptive": self.module.make_descriptive(rows),
            "inputs": [self.inputs],
            "verification": ["synthetic relative output fixture"],
        }
        relative = [Path("new-replay") / path.name for path in self.outputs]
        args = [
            value
            for pair in zip(
                ("--report-output", "--flow-output", "--manifest-output"),
                map(str, relative),
                strict=False,
            )
            for value in pair
        ]
        before_directory = Path.cwd()
        try:
            os.chdir(self.case.resolve().parents[1])
            with (
                mock.patch.object(self.module, "HERE", self.case.resolve()),
                mock.patch.object(self.module, "verify_study", return_value=study),
            ):
                result = self.module.main(args)
            self.assertEqual(result, 0)
            manifest = json.loads(relative[2].read_text())
            self.assertEqual(
                [record["path"] for record in manifest["outputs"]],
                [str(path) for path in relative[:2]],
            )
            for record in manifest["outputs"]:
                self.assertEqual(
                    record["sha256"], hashlib.sha256(Path(record["path"]).read_bytes()).hexdigest()
                )
            self.assertFalse(manifest["invocation"]["external_output_paths_redacted"])
            self.assertNotIn(str(self.case.parents[1]), relative[2].read_text())
        finally:
            os.chdir(before_directory)

    def test_validation_failure_writes_nothing(self):
        for output in self.outputs:
            output.write_text("preserve")
        with (
            mock.patch.object(self.module, "HERE", self.case),
            mock.patch.object(
                self.module, "verify_study", side_effect=ValueError("missing figure")
            ),
        ):
            result = self.module.main([])
        self.assertEqual(result, 1)
        self.assertTrue(all(p.read_text() == "preserve" for p in self.outputs))


if __name__ == "__main__":
    unittest.main()
