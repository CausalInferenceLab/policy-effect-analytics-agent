"""제출 파일·수치표·HTML을 검증하고 선택적으로 새 실행의 최종 결과를 대조한다."""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

from review_overview import check as check_overview

CASE = Path(__file__).resolve().parent


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def rows(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def compare_tables(actual_path, expected_path, keys):
    """행 순서와 무관하게 모든 조건·누락값·수치를 대조한다. 좋은 조건만 선택하지 않는다."""
    tables = []
    for path in [actual_path, expected_path]:
        entries = rows(path)
        mapping = {tuple(row[key] for key in keys): row for row in entries}
        if not entries or len(mapping) != len(entries):
            raise ValueError("비어 있거나 중복된 비교 키")
        tables.append(mapping)
    actual, expected = tables
    if actual.keys() != expected.keys():
        raise ValueError("결과 조건의 누락 또는 추가")
    for key, row in expected.items():
        if row.keys() != actual[key].keys():
            raise ValueError("결과 열 변경")
        for field, value in row.items():
            other = actual[key][field]
            if value == other:
                continue
            try:
                matches = math.isclose(float(value), float(other), rel_tol=1e-10, abs_tol=1e-10)
            except ValueError:
                matches = False
            if not matches:
                raise ValueError(f"결과 불일치: {key} / {field}")
    return len(expected)


def check(base=CASE, bus_results=None, forecast_results=None):
    base = Path(base)
    manifest = json.loads((base / "run_manifest.json").read_text(encoding="utf-8"))
    if len(manifest["public_files"]) != 24 or len(set(manifest["public_files"])) != 24:
        raise ValueError("공개 사례 파일 수가 24개가 아닙니다")
    for name in manifest["public_files"]:
        path = (base / name).resolve()
        if not path.is_relative_to(base.resolve()) or not path.is_file():
            raise ValueError(f"공개 파일 경로 누락: {name}")
    for name, expected in manifest["sha256"].items():
        if sha256(base / name) != expected:
            raise ValueError(f"공개 파일 해시 불일치: {name}")
    claims = {}
    for name, expected_rows in manifest["evidence_tables"].items():
        table = rows(base / name)
        if len(table) != expected_rows:
            raise ValueError("역사적 수치표 행 수 변경")
        for claim in table:
            if claim["id"] in claims or not math.isfinite(float(claim["value"])):
                raise ValueError("수치 ID 중복 또는 유한하지 않은 값")
            claims[claim["id"]] = claim
    checked_claims = 0
    tables = {name: rows(base / name) for name in manifest["recomputed_sources"]}
    for identifier in manifest["primary_claim_ids"]:
        claim = claims[identifier]
        selector = json.loads(claim["selector"])
        found = [
            row
            for row in tables[claim["source"]]
            if all(row[k] == str(v) for k, v in selector.items())
        ]
        if len(found) != 1 or not math.isclose(
            float(found[0][claim["field"]]), float(claim["value"]), rel_tol=1e-10, abs_tol=1e-10
        ):
            raise ValueError("최종 결과와 핵심 수치 불일치: " + identifier)
        checked_claims += 1
    overview = check_overview(page=base / "project-overview.html", base=base)
    compared = {}
    if bus_results is not None:
        compared["bus"] = compare_tables(
            bus_results,
            base / "results/deepening/cohort/comparisons.csv",
            ["cohort", "comparison", "segment"],
        )
    if forecast_results is not None:
        compared["forecast"] = compare_tables(
            forecast_results,
            base / "results/deepening/archive_forecast/metrics.csv",
            ["period", "horizon", "name", "seed", "scope"],
        )
    return dict(
        public_files=24,
        snapshot_claims=len(claims),
        primary_claims_matched=checked_claims,
        historical_supplemental_claims=len(claims) - checked_claims,
        html=overview,
        recomputed_results_compared=compared,
        scope="기본 검사는 공개 스냅샷 무결성 검증. 별도 실행 CSV를 전달한 경우에만 재계산 결과를 대조함",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bus-results", type=Path)
    parser.add_argument("--forecast-results", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            check(bus_results=args.bus_results, forecast_results=args.forecast_results),
            ensure_ascii=False,
            indent=2,
        )
    )
