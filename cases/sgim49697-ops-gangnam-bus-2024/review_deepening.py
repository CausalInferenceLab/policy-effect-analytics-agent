"""두 번째 탐색의 공개 수치·산출물 해시를 원자료와 외부 패키지 없이 검토한다."""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

from review_overnight import csv_bytes, digest, local_path, verify_public_freezes

CASE = Path(__file__).resolve().parent
SPEC = "deepening_review_spec.json"
OUT = "results/deepening/review"


def derive(base, spec):
    documents, sources, rows, identifiers = {}, {}, [], set()
    for claim in spec["claims"]:
        identifier, name = claim["id"], claim["source"]
        if identifier in identifiers or not name.startswith("results/deepening/"):
            raise ValueError("수치 ID 중복 또는 공개 추가 탐색 밖 출처")
        identifiers.add(identifier)
        path = local_path(base, name)
        if name not in documents:
            if path.suffix == ".csv":
                with path.open(encoding="utf-8-sig", newline="") as stream:
                    reader = csv.DictReader(stream)
                    if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
                        raise ValueError("공개 CSV 헤더 누락·중복")
                    documents[name] = list(reader)
                if any(None in row or any(value is None for value in row.values()) for row in documents[name]):
                    raise ValueError("공개 CSV 행 너비 오류")
            elif path.suffix == ".json":
                documents[name] = json.loads(path.read_text(encoding="utf-8"))
            else:
                raise ValueError("CSV·JSON 공개 집계만 허용")
            sources[name] = digest(path)
        if path.suffix == ".csv":
            selected = [row for row in documents[name] if all(row.get(key) == str(value) for key, value in claim["where"].items())]
            if len(selected) != 1:
                raise ValueError(f"근거 행은 정확히 하나여야 합니다: {identifier}")
            row = selected[0]
            if any(row.get(key) != str(value) for key, value in claim.get("require", {}).items()):
                raise ValueError("지정한 품질 조건과 다른 수치: " + identifier)
            value, selector, field = row[claim["field"]], claim["where"], claim["field"]
        else:
            value = documents[name]
            for key in claim["keys"]:
                value = value[key]
            selector, field = {"keys": claim["keys"]}, "/".join(claim["keys"])
        try:
            finite = not isinstance(value, bool) and math.isfinite(float(value))
        except (TypeError, ValueError):
            finite = False
        if not finite:
            raise ValueError("유한 숫자가 아닌 공개 수치: " + identifier)
        if "expected" in claim and float(value) != float(claim["expected"]):
            raise ValueError("필수 검증 결과와 다른 수치: " + identifier)
        rows.append(dict(id=identifier, description=claim["description"], value=str(value), unit=claim["unit"],
                         source=name, field=field, selector=json.dumps(selector, ensure_ascii=False, sort_keys=True),
                         interpretation=claim["interpretation"]))
    if not rows:
        raise ValueError("검토할 수치가 없습니다")
    return rows, sources


def review(base=CASE, write=False):
    spec = json.loads(local_path(base, SPEC).read_text(encoding="utf-8"))
    rows, sources = derive(base, spec)
    integrity, manifests = {}, {}
    for name in spec["output_manifests"]:
        path = local_path(base, name)
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifests[name] = digest(path)
        for filename, expected in manifest["outputs"].items():
            if Path(filename).name != filename or not isinstance(expected, str):
                raise ValueError("공개 산출물 명세의 경로·해시 형식 오류")
            output_name = str((path.parent / filename).relative_to(base))
            if digest(local_path(base, output_name)) != expected:
                raise ValueError("공개 산출물 해시 변경: " + output_name)
            if output_name in integrity and integrity[output_name] != expected:
                raise ValueError("산출물 명세 사이의 해시 충돌")
            integrity[output_name] = expected
    table = csv_bytes(rows)
    result = dict(scope="공개 집계의 선택 조건·수치·산출물 해시 대조. 원자료 재파싱·모델 학습·인과 검증을 대신하지 않음",
                  claims=len(rows), source_tables=len(sources), spec_sha256=digest(local_path(base, SPEC)),
                  code_sha256=digest(Path(__file__)), helper_sha256=digest(local_path(base, "review_overnight.py")),
                  inputs=sources, output_manifests=manifests,
                  verified_public_outputs=integrity, previous_freezes=verify_public_freezes(base),
                  summary_sha256=hashlib.sha256(table).hexdigest())
    output = local_path(base, OUT)
    if write:
        output.mkdir(parents=True, exist_ok=True)
        (output / "key_numbers.csv").write_bytes(table)
        (output / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif json.loads((output / "manifest.json").read_text(encoding="utf-8")) != result or (output / "key_numbers.csv").read_bytes() != table:
        raise ValueError("저장된 공개 수치·출처·코드가 현재 내용과 다릅니다")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    args = parser.parse_args()
    result = review(write=args.write)
    print(f"추가 탐색 공개 수치 {result['claims']}개·출처 {result['source_tables']}개·산출물 {len(result['verified_public_outputs'])}개 확인")
