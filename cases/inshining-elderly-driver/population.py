"""행안부 2013~2018년 12월 인구 원본 취득과 연초 65+ 분모 정제.

표준 라이브러리만 사용한다. 원본 행정기관 코드·연도별 경계는 그대로 둔다.
시·도 합계 및 일반구를 포함한 도시 합계를 leaf 행과 함께 합산하지 않는다.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

PAGE = "https://jumin.mois.go.kr/ageStatMonth.do"
DOWNLOAD = "https://jumin.mois.go.kr/downloadCsvAge.do?searchYearMonth=month&xlsStats=2"
HERE = Path(__file__).resolve().parent
YEARS = range(2013, 2019)


def query(year):
    return dict(
        sltOrgType="1",
        sltOrgLvl1="A",
        sltOrgLvl2="",
        sltUndefType="",
        searchYearStart=str(year),
        searchMonthStart="12",
        searchYearEnd=str(year),
        searchMonthEnd="12",
        searchYearMonth="month",
        sum="sum",
        sltArgTypes="1",
        sltArgTypeA="0",
        sltArgTypeB="100",
        tableChart="T",
    )


class DownloadForm(HTMLParser):
    def __init__(self, page):
        super().__init__()
        self.active = False
        self.values = {}
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.active = attrs.get("id") == "formXlsDown"
        if tag == "input" and self.active and attrs.get("type") == "hidden":
            self.values[attrs["name"]] = attrs.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form":
            self.active = False


def download_query(page, year):
    params = DownloadForm(page).values
    expected = {
        k: v for k, v in query(year).items() if k not in {"sum", "searchYearMonth", "tableChart"}
    }
    if any(params.get(k) != v for k, v in expected.items()) or params.get("category") != "month":
        raise ValueError("인구 조회 응답 조건 불일치")
    if "downloadCsvAge.do" not in page or "xlsStats=2" not in page:
        raise ValueError("전체시군구 CSV 다운로드 경로 확인 실패")
    params.update(sum="sum", gender="")
    return params


def population_header(year):
    prefix = f"{year}년12월_계_"
    return [
        "행정구역",
        prefix + "총인구수",
        prefix + "연령구간인구수",
        *[prefix + f"{age}세" for age in range(100)],
        prefix + "100세 이상",
    ]


def inspect_population(raw, year, expected_provinces=17):
    reader = csv.reader(io.StringIO(raw.decode("cp949")))
    if next(reader, None) != population_header(year):
        raise ValueError("인구 헤더의 연월·계·1세단위·100세 이상 불일치")
    records, vectors = [], {}
    for row in reader:
        if len(row) != 104:
            raise ValueError("인구 행 길이 불일치")
        match = re.fullmatch(r"(.+?)\s*\((\d{10})\)", row[0])
        if not match:
            raise ValueError("행정구역명 또는 10자리 행정기관 코드 오류")
        name, code = match.groups()
        name = " ".join(name.split())
        if code in vectors:
            raise ValueError("행정기관 코드 중복")
        if any(not re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)", x) for x in row[1:]):
            raise ValueError("인구 수치에 결측·음수·소수 또는 비정상 구분 기호")
        values = [int(x.replace(",", "")) for x in row[1:]]
        if values[0] != values[1] or sum(values[2:]) != values[0]:
            raise ValueError(f"{name} 연령 합계 불일치")
        vectors[code] = values
        is_province = code[2:] == "00000000"
        records.append(
            dict(
                reference_year=year,
                reference_date=f"{year}-12-31",
                outcome_year=year + 1,
                region_code=code,
                region_name=name,
                source_label=row[0],
                province_code=code[:2] + "00000000",
                province_name=name.split()[0],
                population=values[0],
                population_65plus=sum(values[2 + 65 :]),
                is_province_total=is_province,
            )
        )
    provinces = [r for r in records if r["is_province_total"]]
    if len(provinces) != expected_provinces:
        raise ValueError(f"시도 합계 수 오류: {len(provinces)}")
    city_checks = 0
    for r in records:
        # 같은 시도에서 긴 행정구역명이 이어지는 경우만 일반구 자식으로 판정.
        children = [
            c
            for c in records
            if not c["is_province_total"]
            and c["province_code"] == r["province_code"]
            and c["region_name"].startswith(r["region_name"] + " ")
        ]
        overlap = bool(children) and not r["is_province_total"]
        r["overlapping_city_total"] = overlap
        r["is_aggregate"] = r["is_province_total"] or overlap
        if overlap:
            city_checks += 1
            if any(
                sum(vectors[c["region_code"]][i] for c in children) != vectors[r["region_code"]][i]
                for i in range(103)
            ):
                raise ValueError(f"{r['region_name']} 일반구 합계 불일치")
    for province in provinces:
        leaves = [
            r
            for r in records
            if r["province_code"] == province["region_code"] and not r["is_aggregate"]
        ]
        if not leaves or any(
            sum(vectors[r["region_code"]][i] for r in leaves) != vectors[province["region_code"]][i]
            for i in range(103)
        ):
            raise ValueError(f"{province['region_name']} 시군구 합계 불일치")
    check = dict(
        year=year,
        rows=len(records),
        province_reconciliations=len(provinces),
        overlapping_city_reconciliations=city_checks,
        leaf_rows=sum(not r["is_aggregate"] for r in records),
        leaf_population=sum(r["population"] for r in records if not r["is_aggregate"]),
        leaf_65plus=sum(r["population_65plus"] for r in records if not r["is_aggregate"]),
        all_age_row_sums_match=True,
        all_province_sums_match=True,
        all_city_district_sums_match=True,
    )
    return records, check


def fetch(url, params=None):
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(params).encode() if params else None,
        headers={"User-Agent": "policy-effect-study/1.0", "Referer": PAGE},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read(), dict(response.headers)


def verify_saved_source(raw, record):
    if record.get("sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("저장 원본의 출처 해시 누락 또는 불일치")


def run(download=False):
    raw_dir = HERE / "data/raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    records, checks, sources = [], [], []
    previous = HERE / "population-qc.json"
    old_sources = {}
    if previous.exists():
        old_sources = {s["year"]: s for s in json.loads(previous.read_text())["sources"]}
    for year in YEARS:
        target = raw_dir / f"population-{year}-12.csv"
        if download and not target.exists():
            page, _ = fetch(PAGE + "?" + urllib.parse.urlencode(query(year)))
            params = download_query(page.decode("utf-8"), year)
            raw, headers = fetch(DOWNLOAD, params)
            # 검사를 통과한 응답만 원본 CSV 경로로 확정한다.
            inspect_population(raw, year)
            target.write_bytes(raw)
            record = dict(
                year=year,
                source_url=PAGE,
                page_query=query(year),
                download_url=DOWNLOAD,
                download_method="POST",
                download_query=params,
                retrieved_at=datetime.now(UTC).isoformat(),
                response_content_type=headers.get("Content-Type"),
                response_content_disposition=headers.get("Content-Disposition"),
            )
        elif target.exists():
            raw = target.read_bytes()
            record = old_sources.get(year, {})
            verify_saved_source(raw, record)
        else:
            raise FileNotFoundError(f"{target}: 먼저 --download 실행")
        data, check = inspect_population(raw, year)
        records.extend(data)
        checks.append(check)
        record.update(
            path=str(target.relative_to(HERE)),
            bytes=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
            encoding="cp949",
        )
        sources.append(record)
        print(f"{year}-12: {check['rows']} source rows, {check['leaf_rows']} nonoverlapping rows")
    (HERE / "data").mkdir(exist_ok=True)
    output_path = HERE / "data/population.csv"
    with output_path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    code_sets = {y: {r["region_code"] for r in records if r["reference_year"] == y} for y in YEARS}
    changes = []
    for year in range(2014, 2019):
        changes.append(
            dict(
                reference_year=year,
                added_codes=sorted(code_sets[year] - code_sets[year - 1]),
                removed_codes=sorted(code_sets[year - 1] - code_sets[year]),
            )
        )
    status = dict(
        checked_at=datetime.now(UTC).isoformat(),
        sources=sources,
        checks=checks,
        output="data/population.csv",
        output_rows=len(records),
        output_sha256=hashlib.sha256(output_path.read_bytes()).hexdigest(),
        definition="직전연도12월 말, 등록구분전체(거주자·거주불명자·재외국민), 외국인제외, 남녀계,65세이상",
        oldest_age_included="100세 이상",
        province_total_rows_preserved=True,
        overlapping_city_totals_flagged=True,
        automatic_boundary_harmonization=False,
        code_changes=changes,
        limitations=[
            "연도별 원시 경계 유지. 청주·청원 통합, 부천 일반구 폐지 및 인천 남구 명칭·코드 변경 등을 별도 대응해야 함",
            "동일 코드의 경계 변경은 이 코드 차분만으로 검출되지 않음",
            "재외국민은2015년1월부터 전체에 포함되는 공식 정의 변경이 있음",
            "면허소지자 또는 운전 노출량이 아닌 주민등록인구 분모",
        ],
    )
    previous.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n")
    return status


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="없는 원본을 공식 CSV 경로로 취득")
    run(parser.parse_args().download)
