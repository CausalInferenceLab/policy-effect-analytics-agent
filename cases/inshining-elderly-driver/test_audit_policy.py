"""Policy evidence contract tests; fixtures use temporary local text only."""

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("audit_policy.py")


class PolicyAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.case = Path(self.temp.name)
        (self.case / "evidence/policy-sources").mkdir(parents=True)
        self.snapshot = self.case / "evidence/policy-sources/source.txt"
        self.snapshot.write_text(
            "공식 기록: 면허 반납 지원은 2018년 7월에 시작했다.\n", encoding="utf-8"
        )
        self.data = {
            "schema_version": 1,
            "checked_on": "2026-10-27",
            "limitations": ["독립 원문 검토 필요"],
            "evidence": [
                {
                    "id": "source-1",
                    "jurisdiction": "테스트시",
                    "source_url": "https://www.busan.go.kr/example",
                    "source_published_on": "2018-07-01",
                    "retrieval_mode": "direct",
                    "snapshot_path": "evidence/policy-sources/source.txt",
                    "snapshot_sha256": hashlib.sha256(self.snapshot.read_bytes()).hexdigest(),
                    "quotation": "면허 반납 지원은 2018년 7월에 시작했다.",
                    "claim_type": "offer_start",
                    "claimed_start": "2018-07",
                    "date_precision": "month",
                }
            ],
            "classifications": [
                {
                    "jurisdiction": "테스트시",
                    "first_offer_start": "2018-07",
                    "date_precision": "month",
                    "role_2019": "treated",
                    "evidence_ids": ["source-1"],
                    "analysis_approved": False,
                    "reason": "공식 시행 기록",
                    "unresolved_checks": [],
                }
            ],
        }

    def audit(self, data=None):
        source = self.case / "policy-evidence.json"
        output = self.case / "policy-checks.json"
        source.write_text(
            json.dumps(self.data if data is None else data, ensure_ascii=False), encoding="utf-8"
        )
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--input", str(source), "--output", str(output)],
            capture_output=True,
            text=True,
        )
        self.assertTrue(output.is_file(), f"Checker must emit a report: {result.stderr}")
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result.returncode != 0, bool(report["errors"]))
        self.assertFalse(report["analysis_approved"])
        return report

    def rejected(self):
        self.assertTrue(self.audit()["errors"])

    def test_valid_evidence_passes_structural_checks_only(self):
        report = self.audit()
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["status"], "structural_checks_passed")
        self.assertTrue(report["semantic_review_required"])
        self.assertTrue(report["limitations"])
        self.assertEqual(
            report["input_sha256"],
            hashlib.sha256((self.case / "policy-evidence.json").read_bytes()).hexdigest(),
        )
        self.assertTrue(report["evidence_files"])

    def test_schema_rejects_missing_unknown_and_wrong_type_keys(self):
        for key, value in [
            ("checked_on", None),
            ("schema_version", True),
            ("evidence", {}),
            ("limitations", [4]),
            ("extra", 1),
        ]:
            with self.subTest(key=key):
                bad = copy.deepcopy(self.data)
                bad[key] = value
                self.assertTrue(self.audit(bad)["errors"])
        del self.data["checked_on"]
        self.rejected()

    def test_row_schema_and_enums_are_strict(self):
        for section, key, value in [
            ("evidence", "retrieval_mode", "browser"),
            ("evidence", "claim_type", "guess"),
            ("evidence", "date_precision", "weekly"),
            ("classifications", "role_2019", "control"),
            ("classifications", "evidence_ids", "source-1"),
            ("classifications", "unresolved_checks", [1]),
            ("evidence", "quotation", 1),
        ]:
            with self.subTest(section=section, key=key):
                bad = copy.deepcopy(self.data)
                bad[section][0][key] = value
                self.assertTrue(self.audit(bad)["errors"])
        del self.data["evidence"][0]["quotation"]
        self.rejected()

    def test_calendar_and_precision_are_validated(self):
        for date, precision in [
            ("2019-02-29", "day"),
            ("2019-13", "month"),
            ("0000", "year"),
            ("2018-07", "day"),
            ("2018-7", "month"),
            ("2018", "unknown"),
            (None, "year"),
        ]:
            with self.subTest(date=date, precision=precision):
                bad = copy.deepcopy(self.data)
                bad["evidence"][0].update(claimed_start=date, date_precision=precision)
                self.assertTrue(self.audit(bad)["errors"])
        self.data["checked_on"] = "2026-02-30"
        self.rejected()

    def test_bad_publication_date_rejected(self):
        self.data["evidence"][0]["source_published_on"] = "2019-02-29"
        self.rejected()

    def test_duplicate_evidence_and_classifications_rejected(self):
        for section in ["evidence", "classifications"]:
            bad = copy.deepcopy(self.data)
            bad[section].append(copy.deepcopy(bad[section][0]))
            self.assertTrue(self.audit(bad)["errors"])

    def test_missing_and_cross_jurisdiction_references_rejected(self):
        self.data["classifications"][0]["evidence_ids"] = ["missing"]
        self.rejected()
        self.data["classifications"][0]["evidence_ids"] = ["source-1"]
        self.data["classifications"][0]["jurisdiction"] = "테스트시 하위구"
        self.rejected()

    def test_corrupted_snapshot_hash_rejected(self):
        self.snapshot.write_text("변조한 자료", encoding="utf-8")
        self.rejected()

    def test_quotation_must_be_literal_nonempty_substring(self):
        for quotation in ["없는 문장", ""]:
            bad = copy.deepcopy(self.data)
            bad["evidence"][0]["quotation"] = quotation
            self.assertTrue(self.audit(bad)["errors"])

    def test_missing_and_non_utf8_snapshots_rejected(self):
        self.snapshot.write_bytes(b"\xff\xfe")
        self.rejected()
        self.snapshot.unlink()
        self.rejected()

    def test_path_traversal_absolute_and_symlink_escape_rejected(self):
        external = self.case.parent / f"{self.case.name}-outside.txt"
        external.write_text("external", encoding="utf-8")
        self.addCleanup(external.unlink)
        link = self.case / "escape.txt"
        link.symlink_to(external)
        for path in ["../outside.txt", str(external), "escape.txt"]:
            bad = copy.deepcopy(self.data)
            bad["evidence"][0]["snapshot_path"] = path
            self.assertTrue(self.audit(bad)["errors"])

    def test_invalid_path_and_symlink_loop_are_reported_as_errors(self):
        loop = self.case / "loop.txt"
        loop.symlink_to(loop)
        for path in ["loop.txt", "evidence/\x00source.txt"]:
            bad = copy.deepcopy(self.data)
            bad["evidence"][0]["snapshot_path"] = path
            self.assertTrue(self.audit(bad)["errors"])

    def test_only_https_official_domains_allowed(self):
        for url in [
            "http://busan.go.kr",
            "https://busan.go.kr.evil.com",
            "https://example.com",
            "https://user@busan.go.kr",
            "https://busan.go.kr:444/path",
        ]:
            bad = copy.deepcopy(self.data)
            bad["evidence"][0]["source_url"] = url
            self.assertTrue(self.audit(bad)["errors"])

    def test_ordinance_and_eligibility_cannot_establish_offer_start(self):
        for claim in [
            "ordinance_effective",
            "eligibility_start",
            "concurrent_policy_start",
            "other",
        ]:
            bad = copy.deepcopy(self.data)
            bad["evidence"][0]["claim_type"] = claim
            self.assertTrue(self.audit(bad)["errors"])
        self.data["evidence"][0]["claim_type"] = "first_implementation"
        self.assertEqual(self.audit()["errors"], [])

    def test_first_offer_date_needs_exact_supported_date(self):
        for date, precision in [("2018", "year"), ("2017-07", "month"), ("2018-07-01", "day")]:
            bad = copy.deepcopy(self.data)
            bad["classifications"][0].update(first_offer_start=date, date_precision=precision)
            self.assertTrue(self.audit(bad)["errors"])

    def test_roles_follow_first_offer_year_without_promoting_candidates(self):
        for date, expected in [
            ("2018", "treated"),
            ("2019", "excluded_treated"),
            ("2020", "candidate"),
        ]:
            with self.subTest(date=date):
                bad = copy.deepcopy(self.data)
                bad["evidence"][0].update(claimed_start=date, date_precision="year")
                bad["classifications"][0].update(
                    first_offer_start=date, date_precision="year", role_2019=expected
                )
                self.assertEqual(self.audit(bad)["errors"], [])
                bad["classifications"][0]["role_2019"] = (
                    "treated" if expected != "treated" else "candidate"
                )
                self.assertTrue(self.audit(bad)["errors"])

    def test_unknown_is_hold_and_reported_separately(self):
        self.data["evidence"][0].update(claimed_start=None, date_precision="unknown")
        self.data["classifications"][0].update(
            first_offer_start=None, date_precision="unknown", role_2019="hold"
        )
        report = self.audit()
        self.assertEqual(report["errors"], [])
        self.assertTrue(report["unknowns"])
        self.data["classifications"][0]["role_2019"] = "candidate"
        self.rejected()
        self.data["classifications"][0].update(first_offer_start=0, role_2019="hold")
        self.rejected()

    def test_known_start_can_remain_hold_with_unresolved_classification_checks(self):
        self.data["evidence"][0].update(claimed_start="2020", date_precision="year")
        self.data["classifications"][0].update(
            first_offer_start="2020",
            date_precision="year",
            role_2019="hold",
            reason="2020년 지원 개시 기록은 있으나 2019년 소급 자격·예고 노출 확인 필요",
            unresolved_checks=["2019년 예고·소급 자격이 사전 행동에 영향을 주었는지 확인"],
        )
        report = self.audit()
        self.assertEqual(report["errors"], [])
        self.assertTrue(
            any(item["code"] == "known_date_classification_hold" for item in report["warnings"])
        )
        self.assertTrue(
            any(item["code"] == "classification_eligibility_unknown" for item in report["unknowns"])
        )
        written = json.loads((self.case / "policy-evidence.json").read_text(encoding="utf-8"))
        self.assertEqual(written["classifications"][0]["role_2019"], "hold")
        self.assertEqual(written["classifications"][0]["first_offer_start"], "2020")

    def test_known_start_hold_requires_unresolved_checks_and_date_evidence(self):
        self.data["evidence"][0].update(claimed_start="2020", date_precision="year")
        self.data["classifications"][0].update(
            first_offer_start="2020", date_precision="year", role_2019="hold"
        )
        report = self.audit()
        self.assertTrue(
            any(item["code"] == "hold_without_unresolved_checks" for item in report["errors"])
        )
        self.data["classifications"][0]["unresolved_checks"] = ["2019년 예고 노출 확인"]
        self.data["classifications"][0]["first_offer_start"] = "2021"
        report = self.audit()
        self.assertTrue(any(item["code"] == "unsupported_first_offer" for item in report["errors"]))
        self.data["classifications"][0]["reason"] = ""
        self.rejected()

    def test_analysis_approval_true_is_always_rejected(self):
        self.data["classifications"][0]["analysis_approved"] = True
        self.rejected()

    def test_explicit_search_index_marker_cannot_be_labeled_direct(self):
        for marker in ["SEARCH INDEX EXCERPT", "search index excerpt"]:
            with self.subTest(marker=marker):
                original = "공식 기록: 면허 반납 지원은 2018년 7월에 시작했다.\n"
                self.snapshot.write_text(marker + "\n" + original, encoding="utf-8")
                self.data["evidence"][0]["snapshot_sha256"] = hashlib.sha256(
                    self.snapshot.read_bytes()
                ).hexdigest()
                self.data["evidence"][0]["retrieval_mode"] = "direct"
                report = self.audit()
                self.assertTrue(
                    any(item["code"] == "retrieval_marker_mismatch" for item in report["errors"])
                )
                self.data["evidence"][0]["retrieval_mode"] = "search_index"
                report = self.audit()
                self.assertEqual(report["errors"], [])
                self.assertTrue(
                    any(item["code"] == "original_unverified" for item in report["warnings"])
                )

    def test_search_index_requires_snapshot_and_warns_about_original(self):
        self.data["evidence"][0]["retrieval_mode"] = "search_index"
        report = self.audit()
        self.assertEqual(report["errors"], [])
        self.assertTrue(any(item["code"] == "original_unverified" for item in report["warnings"]))
        self.assertTrue(
            any(
                item.get("evidence_id") == "source-1" for item in report["semantic_review_required"]
            )
        )
        self.data["evidence"][0]["snapshot_path"] = None
        self.rejected()

    def test_unavailable_evidence_cannot_support_known_start(self):
        self.data["evidence"][0].update(
            retrieval_mode="unavailable", snapshot_path=None, snapshot_sha256=None, quotation=""
        )
        self.rejected()
        self.data["evidence"][0].update(claimed_start=None, date_precision="unknown")
        self.data["classifications"][0].update(
            first_offer_start=None, date_precision="unknown", role_2019="hold"
        )
        report = self.audit()
        self.assertEqual(report["errors"], [])
        self.assertTrue(report["unknowns"])

    def test_malformed_json_still_produces_failure_report(self):
        source = self.case / "broken.json"
        output = self.case / "checks.json"
        source.write_text("{bad", encoding="utf-8")
        process = subprocess.run(
            [sys.executable, str(SCRIPT), "--input", str(source), "--output", str(output)],
            capture_output=True,
        )
        self.assertNotEqual(process.returncode, 0)
        self.assertTrue(output.is_file())
        self.assertTrue(json.loads(output.read_text())["errors"])


if __name__ == "__main__":
    unittest.main()
