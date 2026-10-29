"""공개 CSV의 핵심 수치와 해시를 원본·모델 없이 대조하고 선택적으로 로컬 동결을 검사한다."""

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path

CASE = Path(__file__).resolve().parent
SPEC = "overnight_review_spec.json"
OUTPUT = "results/overnight/review"
FIELDS = ["id", "description", "value", "unit", "source", "field", "selector", "interpretation"]
FROZEN_MANIFESTS = ["forecast/selection_manifest.json", "forecast_baselines/supplement_manifest.json",
                    "relative_ablation/development_manifest.json", "interval_calibration/preparation_manifest.json",
                    "conditional_low/development_manifest.json", "conditional_margin/preparation_manifest.json",
                    "confirmation/selection_manifest.json"]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def local_path(base, name):
    path = (base / name).resolve()
    if not path.is_relative_to(base.resolve()) or Path(name).is_absolute():
        raise ValueError(f"사례 밖 경로는 사용할 수 없습니다: {name}")
    return path


def derive(base, spec):
    """명시한 조건에 유일하게 맞는 유효 행만 선택한다. 실패 행을 임의로 대체하지 않는다."""
    tables, sources, rows, identifiers = {}, {}, [], set()
    for claim in spec["claims"]:
        if claim["id"] in identifiers:
            raise ValueError(f"수치 ID 중복: {claim['id']}")
        identifiers.add(claim["id"])
        name = claim["source"]
        if not name.startswith("results/overnight/") or not name.endswith(".csv"):
            raise ValueError("공개 탐색 CSV만 수치 근거로 사용합니다")
        path = local_path(base, name)
        if name not in tables:
            with path.open(encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
                    raise ValueError(f"CSV 헤더 누락·중복: {name}")
                tables[name] = list(reader)
            if any(None in row or any(v is None for v in row.values()) for row in tables[name]):
                raise ValueError(f"CSV 행 너비 오류: {name}")
            sources[name] = digest(path)
        matches = [row for row in tables[name] if all(row.get(key) == str(value) for key, value in claim["where"].items())]
        if len(matches) != 1:
            raise ValueError(f"수치의 근거 행은 1개여야 합니다: {claim['id']} ({len(matches)}개)")
        row = matches[0]
        for key, expected in claim.get("require", {}).items():
            if row.get(key) != str(expected):
                raise ValueError(f"보류·실패한 결과를 채택할 수 없습니다: {claim['id']} / {key}")
        value = row.get(claim["field"])
        try:
            valid = math.isfinite(float(value))
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise ValueError(f"유효한 숫자가 아닙니다: {claim['id']}")
        rows.append({"id": claim["id"], "description": claim["description"], "value": value,
                     "unit": claim["unit"], "source": name, "field": claim["field"],
                     "selector": json.dumps(claim["where"], ensure_ascii=False, sort_keys=True),
                     "interpretation": claim["interpretation"]})
    if not rows:
        raise ValueError("검증할 공개 수치가 없습니다")
    return rows, sources


def csv_bytes(rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def verify_public_freezes(base):
    verified, manifests = {}, {}
    for name in FROZEN_MANIFESTS:
        path = local_path(base, "results/overnight/" + name)
        record = json.loads(path.read_text(encoding="utf-8"))
        manifests[str(path.relative_to(base))] = digest(path)
        inputs = dict(record.get("inputs", {}))
        inputs.update({entry["path"]: entry["sha256"] for entry in record.get("frozen_files", [])})
        inputs.update({str((path.parent / key).relative_to(base)): value for key, value in record.get("outputs", {}).items()})
        for source, expected in inputs.items():
            if source.startswith(("data/", "runs/")):
                continue
            if digest(local_path(base, source)) != expected:
                raise ValueError(f"공개 동결 파일 변경: {source}")
            if source in verified and verified[source] != expected:
                raise ValueError(f"동결 명세 사이의 해시 충돌: {source}")
            verified[source] = expected
    return {"manifests": manifests, "verified_public_files": verified,
            "excluded_local_artifacts": "data/·runs/의 원본·캐시·모델은 --local-artifacts에서만 확인"}


def review(base, write=False):
    spec_path = local_path(base, SPEC)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    rows, sources = derive(base, spec)
    for name, expected in spec.get("preserved_inputs", {}).items():
        if digest(local_path(base, name)) != expected:
            raise ValueError(f"보존 대상 원문·프로토콜 변경: {name}")
    output = local_path(base, OUTPUT)
    table = csv_bytes(rows)
    manifest = {"scope": "공개 집계의 수치·선택 조건·해시 대조. 원본 재파싱·모델 재학습·인과 검증을 대신하지 않음",
                "claims": len(rows), "source_tables": len(sources), "spec_sha256": digest(spec_path),
                "code_sha256": digest(Path(__file__)), "inputs": sources,
                "summary_sha256": hashlib.sha256(table).hexdigest()}
    if spec.get("verify_public_frozen_manifests"):
        manifest["public_freezes"] = verify_public_freezes(base)
    if write:
        output.mkdir(parents=True, exist_ok=True)
        (output / "key_numbers.csv").write_bytes(table)
        (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        saved = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        if saved != manifest or (output / "key_numbers.csv").read_bytes() != table:
            raise ValueError("저장된 핵심 수치·입력·코드 해시가 현재 공개 자료와 다릅니다")
    return manifest


def verify_local():
    """로컬 원본·개발 예측·모델이 있을 때 각 실험의 기존 동결 검사를 그대로 호출한다."""
    from gangnam.common import read_yaml
    from gangnam.overnight_baseline_runner import verify_manifest
    from gangnam.overnight_conditional_low import verify as conditional
    from gangnam.overnight_conditional_margin import verify as margin
    from gangnam.overnight_confirmation_data import verify as confirmation
    from gangnam.overnight_forecast_data import allowed_months
    from gangnam.overnight_interval_calibration import verify as interval
    from gangnam.overnight_relative_ablation import verify as ablation

    months = allowed_months("test", read_yaml("overnight_forecast_config.yaml"))
    if months != ["2025-05", "2025-06", "2025-07", "2025-08"]:
        raise ValueError("동결 시험 허용 기간 변경")
    sizes = {}
    for name, check in [("baselines", verify_manifest), ("relative_ablation", ablation),
                        ("interval_calibration", interval), ("conditional_low", conditional), ("conditional_margin", margin),
                        ("confirmation", confirmation)]:
        manifest = check()[-1]
        sizes[name] = len(manifest["entries"])
    original = json.loads((CASE / "results/overnight/forecast/selection_manifest.json").read_text(encoding="utf-8"))
    return {"original_frozen_files": len(original["frozen_files"]), "additional_manifest_entries": sizes,
            "allowed_test_months": months}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="공개 집계의 현재 수치와 저장된 검증 명세 대조 (기본)")
    mode.add_argument("--write", action="store_true", help="공개 집계에서 핵심 수치·명세를 생성")
    parser.add_argument("--local-artifacts", action="store_true", help="로컬 모델·개발 캐시가 있을 때 7개 실험 동결 추가 검증")
    args = parser.parse_args()
    try:
        result = review(CASE, write=args.write)
        print(f"공개 핵심 수치 {result['claims']}개·근거 CSV {result['source_tables']}개: 대조 통과")
        if args.local_artifacts:
            print(json.dumps(verify_local(), ensure_ascii=False))
    except (ValueError, KeyError, OSError, ImportError) as exc:
        parser.exit(1, f"검증 실패: {exc}\n")


if __name__ == "__main__":
    main()
