"""정규화한 사고와 직전 12월 인구를 엄격한 지역명·연도 키로 결합한다.

입력 사고 CSV: region_name,year,older_accidents. 지역명은 행안부 전체명과
대응을 확인한 값이어야 한다. 유사 문자열 매칭·경계 배분·처치 추정은 하지 않는다.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent


def integer(value):
    if not re.fullmatch(r"\d+", str(value)):
        raise ValueError(f"비음수 정수 필요: {value!r}")
    return int(value)


def read_verified_csv(path, expected_hash):
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
        raise ValueError(f"품질검사 기록과 입력 해시 불일치: {path.name}")
    with path.open(encoding="utf-8-sig", newline="") as source:
        return list(csv.DictReader(source))


def build_panel(accidents, population):
    if not accidents:
        raise ValueError("사고 자료 없음")
    lookup = {}
    for row in population:
        # 세종은 시도 합계와 기초 행의 이름이 같다. 합계만 제거하고
        # 전주시처럼 사고 표의 공간 단위가 될 수 있는 일반구 도시 합계는 보존한다.
        if row.get("is_province_total") in (True, "True"):
            continue
        year = integer(row["outcome_year"])
        if integer(row["reference_year"]) != year - 1:
            raise ValueError("직전연도 12월 인구만 허용")
        if row.get("reference_date") != f"{year - 1}-12-31":
            raise ValueError("직전 12월 말 기준일 필요")
        key = (row["region_name"], year)
        if key in lookup:
            raise ValueError(f"인구 키 중복: {key}")
        lookup[key] = row
    output, seen, region_ids = [], set(), set()
    for row in accidents:
        name, year = row["region_name"], integer(row["year"])
        if not 2014 <= year <= 2019:
            raise ValueError(f"계획 기간 밖 사고 연도: {year}")
        key = (name, year)
        if key in seen:
            raise ValueError(f"사고 키 중복: {key}")
        if key not in lookup:
            raise ValueError(f"분모 없음: {key}")
        seen.add(key)
        denominator = lookup[key]
        older = integer(denominator["population_65plus"])
        if older == 0:
            raise ValueError(f"0명 분모: {key}")
        count = integer(row["older_accidents"])
        code = denominator["region_code"]
        if not re.fullmatch(r"\d{10}", code):
            raise ValueError(f"10자리 행정기관 코드 필요: {code}")
        if (code, year) in region_ids:
            raise ValueError(f"같은 지역 코드에 복수 사고 행: {code}, {year}")
        region_ids.add((code, year))
        output.append(
            dict(
                region_id=code,
                province_id=denominator["province_code"],
                region_name=name,
                year=year,
                crashes65=count,
                population65_start=older,
                crashes65_per_10000_residents=10000 * count / older,
            )
        )
    for year in {r["year"] for r in output}:
        names = [r["region_name"] for r in output if r["year"] == year]
        for name in names:
            if any(other.startswith(name + " ") for other in names):
                raise ValueError(f"공간 중첩: {year} {name}와 하위 지역")
    return output


def run():
    inputs = {name: HERE / "data" / f"{name}.csv" for name in ["accidents", "population"]}
    accident_qc = json.loads((HERE / "taas-qc.json").read_text())
    population_qc = json.loads((HERE / "population-qc.json").read_text())
    expected = dict(
        accidents=accident_qc["outputs_sha256"]["data/accidents.csv"],
        population=population_qc["output_sha256"],
    )
    tables = {name: read_verified_csv(path, expected[name]) for name, path in inputs.items()}
    unjoined = read_verified_csv(
        HERE / "data/taas-unmatched.csv", accident_qc["outputs_sha256"]["data/taas-unmatched.csv"]
    )
    rows = build_panel(tables["accidents"], tables["population"])
    target = HERE / "data/outcome-panel.csv"
    with target.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    years = sorted({r["year"] for r in rows})
    region_years = {}
    for row in rows:
        region_years.setdefault(row["region_id"], []).append(row["year"])
    coverage = []
    for year in years:
        joined = [r for r in rows if r["year"] == year]
        excluded = [r for r in unjoined if integer(r["year"]) == year]
        count = sum(r["crashes65"] for r in joined)
        excluded_count = sum(integer(r["older_accidents"]) for r in excluded)
        national = accident_qc["independent_reference"]["expected_totals"][str(year)]
        if count + excluded_count != national:
            raise ValueError(f"결합·보류 사고 건수와 전국 합계 불일치: {year}")
        coverage.append(
            dict(
                year=year,
                joined_rows=len(joined),
                unjoined_rows=len(excluded),
                national_crashes65=national,
                joined_crashes65=count,
                unjoined_crashes65=excluded_count,
            )
        )
    coverage_path = HERE / "data/panel-coverage.csv"
    with coverage_path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(coverage[0]))
        writer.writeheader()
        writer.writerows(coverage)
    qc = dict(
        output=str(target.relative_to(HERE)),
        rows=len(rows),
        years=years,
        rows_by_year={year: sum(r["year"] == year for r in rows) for year in years},
        regions=len(region_years),
        complete_six_year_regions=sum(
            sorted(v) == list(range(2014, 2020)) for v in region_years.values()
        ),
        temporal_completeness_is_not_boundary_validation=True,
        coverage=coverage,
        unjoined_rows=len(unjoined),
        input_sha256={
            name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in inputs.items()
        },
        output_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        coverage_sha256=hashlib.sha256(coverage_path.read_bytes()).hexdigest(),
        analysis_ready=False,
        spatial_harmonization_complete=False,
        treatment_joined=False,
        effect_estimated=False,
        limitation="원시 지역명 대응만 검사. 경계 동일성·비교군 적격성은 별도 확인.",
    )
    (HERE / "panel-qc.json").write_text(json.dumps(qc, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(qc, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()
