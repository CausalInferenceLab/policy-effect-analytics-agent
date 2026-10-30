"""review_submission.py - 보존한 공개 결과의 수치·해시·HTML을 원자료 없이 읽기 전용으로 검증한다."""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import review_deepening
import review_overnight
import review_overview

CASE = Path(__file__).resolve().parent
MANIFEST = "submission-manifest.json"


def read_json(base, name):
    return json.loads(review_overnight.local_path(base, name).read_text(encoding="utf-8"))


def verify_hash(base, name, expected):
    path = review_overnight.local_path(base, name)
    if not path.is_file():
        raise ValueError("공개 검증에 필요한 파일 누락: " + name)
    if review_overnight.digest(path) != expected:
        raise ValueError("보존된 해시와 다른 파일: " + name)


def inventory(base):
    """공개·보관 목록의 중복/경로 오류를 거절한다. 로컬 보관 파일은 읽지 않는다."""
    manifest = read_json(base, MANIFEST)
    if manifest.get("schema_version") != 1 or not re.fullmatch(
        r"[0-9a-f]{40}", manifest.get("baseline_commit", "")
    ):
        raise ValueError("공개 결과 명세의 버전·기준 커밋 오류")
    groups = {}
    for field in ("public_artifacts", "archived_files"):
        records = manifest[field]
        paths = set()
        for record in records:
            name = record["path"]
            review_overnight.local_path(base, name)
            if name in paths or not re.fullmatch(r"[0-9a-f]{64}", record["sha256"]):
                raise ValueError("보존 목록의 중복 경로·해시 오류: " + name)
            if type(record["bytes"]) is not int or record["bytes"] < 0 or not record.get("reason"):
                raise ValueError("보존 목록의 크기·사유 오류: " + name)
            if field == "public_artifacts" and not name.startswith("results/"):
                raise ValueError("공개 산출물은 results/ 안에 있어야 합니다: " + name)
            paths.add(name)
        groups[field] = paths
    if not groups["public_artifacts"] or groups["public_artifacts"] & groups["archived_files"]:
        raise ValueError("공개 산출물 목록이 비었거나 보관 목록과 겹칩니다")
    return manifest, groups["public_artifacts"], groups["archived_files"]


def verify_claims(base, phase, module, public_paths):
    """기존 전체 감사 명세의 수치·코드·출처 부분을 대조하며 명세를 다시 쓰지 않는다."""
    spec_name = f"{phase}_review_spec.json"
    folder = f"results/{phase}/review"
    manifest_name, table_name = f"{folder}/manifest.json", f"{folder}/key_numbers.csv"
    spec, saved = read_json(base, spec_name), read_json(base, manifest_name)
    required = {claim["source"] for claim in spec["claims"]} | {manifest_name, table_name}
    if not required <= public_paths:
        raise ValueError("공개 보존 목록에 핵심 근거가 없습니다: " + ", ".join(sorted(required - public_paths)))
    verify_hash(base, spec_name, saved["spec_sha256"])
    verify_hash(base, f"review_{phase}.py", saved["code_sha256"])
    if phase == "deepening":
        verify_hash(base, "review_overnight.py", saved["helper_sha256"])
    for name, expected in spec.get("preserved_inputs", {}).items():
        verify_hash(base, name, expected)
    rows, sources = module.derive(base, spec)
    table = review_overnight.csv_bytes(rows)
    if (len(rows) != saved["claims"] or len(sources) != saved["source_tables"]
            or sources != saved["inputs"]
            or hashlib.sha256(table).hexdigest() != saved["summary_sha256"]
            or (base / table_name).read_bytes() != table):
        raise ValueError("기존 수치·출처·검토표와 다릅니다: " + phase)
    return saved


def verify_retained_provenance(base, records, public_paths, archived_paths):
    """기존 동결에서 현재 공개하는 파일만 확인한다. 제외 산출물의 검증을 주장하지 않는다."""
    expected_hashes = {}

    def include(entries):
        for name, value in entries.items():
            if name in expected_hashes and expected_hashes[name] != value:
                raise ValueError("원래 감사 명세 사이의 해시 충돌: " + name)
            expected_hashes[name] = value

    for saved in records:
        manifests = saved.get("output_manifests", {})
        include(manifests)
        include(saved.get("verified_public_outputs", {}))
        freezes = saved.get("public_freezes", saved.get("previous_freezes", {}))
        include(freezes.get("manifests", {}))
        include(freezes.get("verified_public_files", {}))
        required = set(manifests) | set(freezes.get("manifests", {}))
        if not required <= public_paths:
            raise ValueError("기존 동결·감사 명세 누락: " + ", ".join(sorted(required - public_paths)))
    retained = 0
    for name, expected in expected_hashes.items():
        if name in archived_paths:
            continue
        if name.startswith("results/") and name not in public_paths:
            raise ValueError("보존·보관 목록에 없는 기존 근거: " + name)
        verify_hash(base, name, expected)
        retained += 1
    return retained


def check(base=CASE):
    base = Path(base).resolve()
    manifest, public_paths, archived_paths = inventory(base)
    for record in manifest["public_artifacts"]:
        verify_hash(base, record["path"], record["sha256"])
        if (base / record["path"]).stat().st_size != record["bytes"]:
            raise ValueError("공개 산출물 크기가 다릅니다: " + record["path"])
    for name, expected in manifest["preserved_files"].items():
        if name in archived_paths:
            raise ValueError("보존 원문을 보관 대상으로 바꿀 수 없습니다: " + name)
        verify_hash(base, name, expected)
    records = [verify_claims(base, "overnight", review_overnight, public_paths),
               verify_claims(base, "deepening", review_deepening, public_paths)]
    retained = verify_retained_provenance(base, records, public_paths, archived_paths)
    overview = review_overview.check(base / "project-overview.html", base=base)
    return {"claims": sum(record["claims"] for record in records),
            "source_tables": sum(record["source_tables"] for record in records),
            "public_artifacts": len(public_paths), "retained_frozen_files": retained,
            "archived_files_not_checked": len(archived_paths), "overview": overview}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", required=True)
    parser.parse_args()
    try:
        result = check()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("공개 결과 검증 실패: " + str(exc), file=sys.stderr)
        return 1
    print(f"공개 수치 {result['claims']}개·근거 {result['source_tables']}개·"
          f"산출물 {result['public_artifacts']}개 대조 통과")
    overview = result["overview"]
    print(f"HTML 근거 {overview['claims']}개·표시 {overview['displayed_numbers']}곳·"
          f"파생식 {overview['derived']}개·앵커 {overview['anchors']}개 대조 통과")
    print(f"보관 파일 {result['archived_files_not_checked']}개는 검사하지 않았습니다. "
          "원자료 재계산·학습·전체 로컬 감사는 수행하지 않습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
