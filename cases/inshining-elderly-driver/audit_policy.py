"""Local structural checks, never approval of historical truth or causal analysis."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlsplit

TOP_KEYS = {"schema_version", "checked_on", "evidence", "classifications", "limitations"}
EVIDENCE_KEYS = {
    "id",
    "jurisdiction",
    "source_url",
    "source_published_on",
    "retrieval_mode",
    "snapshot_path",
    "snapshot_sha256",
    "quotation",
    "claim_type",
    "claimed_start",
    "date_precision",
}
CLASSIFICATION_KEYS = {
    "jurisdiction",
    "first_offer_start",
    "date_precision",
    "role_2019",
    "evidence_ids",
    "analysis_approved",
    "reason",
    "unresolved_checks",
}
PRECISIONS = {"year", "month", "day", "unknown"}
CLAIMS = {
    "offer_start",
    "ordinance_effective",
    "eligibility_start",
    "concurrent_policy_start",
    "first_implementation",
    "other",
}
ROLES = {"treated", "excluded_treated", "candidate", "hold"}
LIMITS = [
    "자동 검사는 JSON 구조, 날짜·분류 논리, 파일 해시와 인용문 포함 여부만 확인한다.",
    "공식 도메인 형태 검사는 페이지의 진위·게시 주체·원문 사실성·최초 시행 여부를 보장하지 않는다.",
    "인용문의 날짜 의미, 조례·지원 개시 구별, 관할 범위 및 인과성은 독립 검토자가 확인해야 한다.",
    "candidate는 비교군 후보이며 확정 미처치가 아니다. hold/unknown을 0 또는 미처치로 바꾸면 안 된다.",
    "한계 기재와 검사 통과는 교란 제거, 분석 승인 또는 효과 추정의 타당성을 뜻하지 않는다.",
]


def valid_date(value, precision):
    if precision == "unknown":
        return value is None
    if not isinstance(value, str):
        return False
    patterns = {"year": r"\d{4}", "month": r"\d{4}-\d{2}", "day": r"\d{4}-\d{2}-\d{2}"}
    if (
        precision not in patterns
        or re.fullmatch(patterns[precision], value, flags=re.ASCII) is None
    ):
        return False
    try:
        date.fromisoformat(value + {"year": "-01-01", "month": "-01", "day": ""}[precision])
    except ValueError:
        return False
    return True


def official_https(value):
    if not isinstance(value, str) or any(char.isspace() for char in value):
        return False
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        return (
            parsed.scheme == "https"
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 443)
            and (host.endswith(".go.kr") or host == "korea.kr" or host.endswith(".korea.kr"))
        )
    except ValueError:
        return False


def audit_document(document, case_dir):
    report = {
        "schema_version": 1,
        "analysis_approved": False,
        "errors": [],
        "warnings": [],
        "unknowns": [],
        "semantic_review_required": [],
        "evidence_files": [],
        "limitations": list(LIMITS),
        "guarantees": [
            "구조·논리·파일 일치 검사만 수행하며 정책의 사실성이나 인과성을 승인하지 않음"
        ],
    }

    def issue(group, code, location, message, **details):
        report[group].append({"code": code, "location": location, "message": message, **details})

    def error(code, location, message):
        issue("errors", code, location, message)

    def keys(row, expected, location):
        if not isinstance(row, dict):
            error("object_required", location, "객체가 필요하다.")
            return False
        missing, extra = expected - row.keys(), row.keys() - expected
        if missing or extra:
            error(
                "schema_keys",
                location,
                f"필수 키 누락={sorted(missing)}, 허용하지 않은 키={sorted(extra)}",
            )
            return False
        return True

    def nonempty(value):
        return isinstance(value, str) and bool(value.strip())

    def strings(value):
        return isinstance(value, list) and all(nonempty(item) for item in value)

    if not keys(document, TOP_KEYS, "$"):
        report["status"] = "blocked"
        return report
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        error("schema_version", "$.schema_version", "schema_version은 정수 1이어야 한다.")
    if not valid_date(document["checked_on"], "day"):
        error("date", "$.checked_on", "유효한 YYYY-MM-DD 날짜가 필요하다.")
    if not strings(document["limitations"]):
        error("type", "$.limitations", "문자열 배열이 필요하다.")
    for collection in ("evidence", "classifications"):
        if not isinstance(document[collection], list):
            error("type", f"$.{collection}", "배열이 필요하다.")
    if report["errors"]:
        report["status"] = "blocked"
        return report

    evidence_by_id = {}
    usable_ids = set()
    for index, row in enumerate(document["evidence"]):
        location = f"$.evidence[{index}]"
        if not keys(row, EVIDENCE_KEYS, location):
            continue
        error_count = len(report["errors"])
        for field in ("id", "jurisdiction"):
            if not nonempty(row[field]):
                error("type", f"{location}.{field}", "비어 있지 않은 문자열이 필요하다.")
        identifier = row["id"]
        if isinstance(identifier, str):
            if identifier in evidence_by_id:
                error("duplicate_id", location, f"중복 근거 id: {identifier}")
            else:
                evidence_by_id[identifier] = row
        if not official_https(row["source_url"]):
            error(
                "official_https",
                location,
                "공식 HTTPS URL(.go.kr 또는 korea.kr)이 필요하다. 도메인 형태만 검사한다.",
            )
        if row["source_published_on"] is not None and not valid_date(
            row["source_published_on"], "day"
        ):
            error("date", location, "게시일은 유효한 YYYY-MM-DD 또는 null이어야 한다.")
        mode = row["retrieval_mode"]
        if not isinstance(mode, str) or mode not in {"direct", "search_index", "unavailable"}:
            error("enum", location, "retrieval_mode가 유효하지 않다.")
        if not isinstance(row["claim_type"], str) or row["claim_type"] not in CLAIMS:
            error("enum", location, "claim_type이 유효하지 않다.")
        precision = row["date_precision"]
        if (
            not isinstance(precision, str)
            or precision not in PRECISIONS
            or not valid_date(row["claimed_start"], precision)
        ):
            error(
                "date_precision",
                location,
                "claimed_start와 date_precision의 형식·달력이 일치해야 한다.",
            )
        if not isinstance(row["quotation"], str):
            error("type", location, "quotation은 문자열이어야 한다.")
        if row["snapshot_path"] is not None and not nonempty(row["snapshot_path"]):
            error("type", location, "snapshot_path는 상대 경로 문자열 또는 null이어야 한다.")
        digest = row["snapshot_sha256"]
        if digest is not None and (
            not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            error(
                "hash_format",
                location,
                "snapshot_sha256은 소문자 64자리 SHA256 또는 null이어야 한다.",
            )
        if mode in ("direct", "search_index"):
            if not nonempty(row["quotation"]):
                error("quotation", location, "확인 가능한 자료에는 빈 인용문을 허용하지 않는다.")
            if row["snapshot_path"] is None or digest is None:
                error(
                    "snapshot_required",
                    location,
                    "확인 가능한 자료에는 UTF-8 스냅샷 경로와 SHA256이 필요하다.",
                )
        if isinstance(row["snapshot_path"], str):
            relative = Path(row["snapshot_path"])
            root = Path(case_dir).resolve()
            try:
                path = (root / relative).resolve()
            except (OSError, ValueError, RuntimeError) as exc:
                path = None
                error("snapshot_path", location, f"스냅샷 경로를 해석할 수 없다: {exc}")
            if path is None:
                pass
            elif relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(root):
                error(
                    "path_escape",
                    location,
                    "스냅샷은 case 내부 상대 경로여야 한다. 경로 탈출은 금지한다.",
                )
            else:
                try:
                    raw = path.read_bytes()
                    text = raw.decode("utf-8")
                    if mode == "direct" and "search index excerpt" in text.casefold():
                        error(
                            "retrieval_marker_mismatch",
                            location,
                            "스냅샷에 SEARCH INDEX EXCERPT가 명시되어 있어 direct로 기록할 수 없다.",
                        )
                    actual_digest = hashlib.sha256(raw).hexdigest()
                    report["evidence_files"].append(
                        {
                            "evidence_id": identifier,
                            "path": row["snapshot_path"],
                            "sha256": actual_digest,
                        }
                    )
                    if digest != actual_digest:
                        error("snapshot_hash", location, "스냅샷 SHA256 불일치.")
                    if isinstance(row["quotation"], str) and row["quotation"] not in text:
                        error(
                            "quotation", location, "인용문이 스냅샷의 정확한 부분 문자열이 아니다."
                        )
                except (OSError, UnicodeError) as exc:
                    error("snapshot_read", location, f"UTF-8 스냅샷을 읽을 수 없다: {exc}")
        if row["claimed_start"] is None or mode == "unavailable":
            issue(
                "unknowns",
                "evidence_unknown",
                location,
                "시행 시점 또는 자료가 미확인이다. 미처치나 0으로 해석할 수 없다.",
                evidence_id=identifier,
            )
        if mode == "search_index":
            issue(
                "warnings",
                "original_unverified",
                location,
                "검색 색인만 확인했다. 공식 원문은 미확인이며 독립 의미 검토가 필요하다.",
                evidence_id=identifier,
            )
        issue(
            "semantic_review_required",
            "source_interpretation",
            location,
            "독립 검토자가 인용문의 의미·원문 진위·날짜·관할 범위·최초 시행 여부를 확인해야 한다.",
            evidence_id=identifier,
            retrieval_mode=mode,
        )
        if (
            len(report["errors"]) == error_count
            and isinstance(identifier, str)
            and mode in ("direct", "search_index")
        ):
            usable_ids.add(identifier)

    jurisdictions = set()
    for index, row in enumerate(document["classifications"]):
        location = f"$.classifications[{index}]"
        if not keys(row, CLASSIFICATION_KEYS, location):
            continue
        jurisdiction = row["jurisdiction"]
        if not nonempty(jurisdiction):
            error("type", location, "jurisdiction은 비어 있지 않은 문자열이어야 한다.")
        elif jurisdiction in jurisdictions:
            error("duplicate_jurisdiction", location, f"중복 지자체 분류: {jurisdiction}")
        else:
            jurisdictions.add(jurisdiction)
        if row["analysis_approved"] is not False:
            error("analysis_approval", location, "모든 분류의 analysis_approved는 false여야 한다.")
        if not nonempty(row["reason"]):
            error("type", location, "reason은 비어 있지 않은 문자열이어야 한다.")
        for field in ("evidence_ids", "unresolved_checks"):
            if not strings(row[field]):
                error("type", f"{location}.{field}", "문자열 배열이 필요하다.")
        role, precision, start = row["role_2019"], row["date_precision"], row["first_offer_start"]
        if not isinstance(role, str) or role not in ROLES:
            error("enum", location, "role_2019가 유효하지 않다.")
        date_ok = (
            isinstance(precision, str) and precision in PRECISIONS and valid_date(start, precision)
        )
        if not date_ok:
            error(
                "date_precision",
                location,
                "first_offer_start와 date_precision의 형식·달력이 일치해야 한다.",
            )
        cited = []
        if strings(row["evidence_ids"]):
            for identifier in row["evidence_ids"]:
                source = evidence_by_id.get(identifier)
                if source is None:
                    error("missing_evidence", location, f"존재하지 않는 근거: {identifier}")
                elif source["jurisdiction"] != jurisdiction:
                    error(
                        "jurisdiction_mismatch",
                        location,
                        f"다른 관할 근거를 자동 적용할 수 없다: {identifier}",
                    )
                elif identifier in usable_ids:
                    cited.append(source)
        if date_ok and start is None:
            issue(
                "unknowns",
                "classification_unknown",
                location,
                "시행일 미확인: hold로 유지하며 0이나 미처치로 간주하지 않는다.",
                jurisdiction=jurisdiction,
            )
            if role != "hold":
                error("unknown_role", location, "시행일 미확인 분류는 hold여야 한다.")
        elif date_ok:
            year = int(start[:4])
            expected_role = (
                "treated" if year < 2019 else "excluded_treated" if year == 2019 else "candidate"
            )
            if role == "hold":
                if not strings(row["unresolved_checks"]) or not row["unresolved_checks"]:
                    error(
                        "hold_without_unresolved_checks",
                        location,
                        "개시일이 알려진 분류를 hold로 보류하려면 비어 있지 않은 unresolved_checks가 필요하다.",
                    )
                issue(
                    "warnings",
                    "known_date_classification_hold",
                    location,
                    "개시일은 알려져 있으나 분류는 보류되어 있다. 알려진 날짜와 비교군 적격성의 미확인을 구별하며 candidate로 자동 변경하지 않는다.",
                    jurisdiction=jurisdiction,
                    first_offer_start=start,
                )
                issue(
                    "unknowns",
                    "classification_eligibility_unknown",
                    location,
                    "날짜 미확인이 아니라 분류 적격성의 미확인이다. 보류 사유와 미해결 확인 사항을 독립 검토해야 한다.",
                    jurisdiction=jurisdiction,
                    first_offer_start=start,
                    unresolved_checks=row["unresolved_checks"],
                )
            elif role != expected_role:
                error(
                    "year_role", location, f"시행 연도에 따른 role_2019는 {expected_role}여야 한다."
                )
            if not any(
                source["claim_type"] in {"offer_start", "first_implementation"}
                and source["claimed_start"] == start
                and source["date_precision"] == precision
                for source in cited
            ):
                error(
                    "unsupported_first_offer",
                    location,
                    "동일 관할·동일 날짜·동일 정밀도의 지원 개시/최초 시행 근거가 필요하다. 조례나 소급 자격으로 대체할 수 없다.",
                )
        issue(
            "semantic_review_required",
            "classification_interpretation",
            location,
            "독립 검토자가 최초 시행과 비교 가능성을 확인해야 한다. candidate는 확정 미처치가 아니다.",
            jurisdiction=jurisdiction,
        )
    report["status"] = "blocked" if report["errors"] else "structural_checks_passed"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, default=Path(__file__).with_name("policy-evidence.json")
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    output = args.output or args.input.with_name("policy-checks.json")
    if output.resolve() == args.input.resolve():
        parser.error("검사 출력은 입력 파일을 덮어쓸 수 없다.")
    digest = None
    try:
        raw = args.input.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        document = json.loads(raw.decode("utf-8"))
        report = audit_document(document, args.input.parent)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        report = audit_document(None, args.input.parent)
        report["errors"] = [{"code": "input_read", "location": "$", "message": str(exc)}]
    report.update(
        input_path=str(args.input.resolve()),
        input_sha256=digest,
        generated_at=datetime.now(UTC).isoformat(),
        command=[
            sys.executable,
            str(Path(__file__).resolve()),
            "--input",
            str(args.input.resolve()),
            "--output",
            str(output.resolve()),
        ],
    )
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"{report['status']}: errors={len(report['errors'])}, warnings={len(report['warnings'])}, unknowns={len(report['unknowns'])}; analysis_approved=false"
    )
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
