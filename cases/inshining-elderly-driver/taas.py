"""TAAS 익명 공개 통계: 65세 이상 가해운전자 사고, 시군구×연도.

공개 Viewer.js/Dropper.js의 정상 조건 변환·RSA 클라이언트 핸드셰이크를
재현한다. 인증·서버 식별값은 메모리에서만 처리한다. 표준 라이브러리만 사용.
실행: python3 taas.py --fetch  (기본값은 저장된 원본 검증·정제)
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import http.cookiejar
import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = "https://taas.koroad.or.kr"
DEFINITION = "가해운전자(1당사자)의 연령이 65세 이상인 교통사고"
BATCHES = [(2014, 2018), (2019, 2019)]
PROVINCES = dict(
    서울="서울특별시",
    부산="부산광역시",
    대구="대구광역시",
    인천="인천광역시",
    광주="광주광역시",
    대전="대전광역시",
    울산="울산광역시",
    세종="세종특별자치시",
    경기="경기도",
    강원="강원도",
    충북="충청북도",
    충남="충청남도",
    전북="전라북도",
    전남="전라남도",
    경북="경상북도",
    경남="경상남도",
    제주="제주특별자치도",
)
# Independent published totals: ACRC attachment (2014–18), MOIS SafeTV (2019).
NATIONAL_REFERENCE = {2014: 20275, 2015: 23063, 2016: 24429, 2017: 26713, 2018: 30012, 2019: 33239}


def build_parameters(pattern, start, end, page=1):
    if end < start or end - start >= 5:
        raise ValueError("공개 UI의 최대 5년 조회 범위를 벗어남")
    if DEFINITION not in pattern.get("MenuComment", ""):
        raise ValueError("65세 이상 가해운전자 정의 확인 실패")
    value = pattern["Parameter"]
    if ':condition="D903@|OCT_USER.ACC_CLS_15_YN.ELE_NAME = 예;|"' not in value:
        raise ValueError("저장 패턴의 노인운전자사고 조건 변경")
    replacements = dict(
        row_list="906:907",
        col_list="888",
        mea_list="334",
        condition="D903@|@P01 S01 #OTE![예]!#;|;",
        agg_info="D906;@T;@합계;|D907;@T;@합계;|D888;@T;@합계;|",
        pagenum=str(page),
    )
    for key, val in replacements.items():
        value, count = re.subn(":" + key + r'="[^"]*"', ":" + key + '="' + val + '"', value)
        if count != 1:
            raise ValueError("조회 파라미터 누락 또는 중복: " + key)
    return value + f',:vcondition="D1443@|@P08 S01 T111 #OTE![{start}01]!# #OTE![{end}12]!#;|;"'


def parse_page(raw, years):
    root = ET.fromstring(raw)
    if root.tag != "OCTAGONDATA" or root.findtext("ERROR", "").strip():
        raise ValueError("TAAS 통계 XML 또는 오류 응답")
    if DEFINITION not in root.findtext("./GRIDCOMMENT/PATTERNCOMMENT", ""):
        raise ValueError("응답의 65세 이상 가해운전자 정의 불일치")

    def table(name):
        text = root.findtext("./GRID/" + name)
        if not text:
            raise ValueError("통계 테이블 누락: " + name)
        return ET.fromstring(text.replace("&nbsp;", " ")).findall("TR")

    cols = table("COLSESSION")
    observed = [td.attrib.get("code", "") for tr in cols for td in tr.findall("TD")]
    has_total = observed[:1] == ["합계"]
    if observed[int(has_total) :] != [str(y) for y in years]:
        raise ValueError("응답 연도 불일치 또는 월별 자료")
    labels, values = table("ROWSESSION"), table("DATASESSION")
    if len(labels) != len(values):
        raise ValueError("지역명과 수치 행 수 불일치")
    records, province = [], None
    for label, data in zip(labels, values, strict=False):
        cells = label.findall("TD")
        names = [td.attrib.get("code", "").strip() for td in cells]
        if not names or any(not name for name in names):
            raise ValueError("지역 코드명 누락")
        if len(names) == 2:
            province, district = names
        elif len(names) == 1 and names[0] == "합계":
            province, district = "합계", "합계"
        elif len(names) == 1:
            district = names[0]
        else:
            raise ValueError("지역 차원 수 불일치")
        numbers = ["".join(td.itertext()).strip() for td in data.findall("TD")]
        if len(numbers) != len(observed) or any(
            not re.fullmatch(r"\d+|\d{1,3}(?:,\d{3})+", n) for n in numbers
        ):
            raise ValueError("사고 수 결측·형식·열 수 불일치")
        numbers = tuple(int(n.replace(",", "")) for n in numbers)
        if has_total and numbers[0] != sum(numbers[1:]):
            raise ValueError("행별 연도 합계 불일치")
        records.append((province, district, numbers[int(has_total) :]))
    return dict(
        page=int(root.findtext("./PAGE/CURRENTPAGE", "0")),
        total_pages=int(root.findtext("./PAGE/TOTALPAGE", "0")),
        rows=records,
    )


def reconcile(pages, years):
    if not pages or [p["page"] for p in pages] != list(range(1, pages[0]["total_pages"] + 1)):
        raise ValueError("통계 페이지 누락 또는 중복")
    if any(p["total_pages"] != len(pages) for p in pages):
        raise ValueError("페이지 수 불일치")
    rows, province = [], None
    for page in pages:
        for prov, district, vals in page["rows"]:
            province = prov or province
            if not province:
                raise ValueError("페이지 경계의 시도명 누락")
            rows.append((province, district, vals))
    keys = [(p, d) for p, d, _ in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("지역 행 중복")
    lookup = {(p, d): v for p, d, v in rows}
    if ("합계", "합계") not in lookup:
        raise ValueError("전국 합계 누락")
    provinces = sorted({p for p, d, _ in rows if p != "합계"})
    totals = {}
    for p in provinces:
        if (p, "합계") in lookup:
            totals[p] = lookup[(p, "합계")]
        elif p == "세종" and (p, "세종시") in lookup and sum(prov == p for prov, _, _ in rows) == 1:
            totals[p] = lookup[(p, "세종시")]
        else:
            raise ValueError("시도 합계 누락: " + p)
    national = lookup[("합계", "합계")]
    for i, _year in enumerate(years):
        if sum(totals[p][i] for p in provinces) != national[i]:
            raise ValueError("전국·시도 합계 불일치")
        for p in provinces:
            if sum(v[i] for prov, d, v in rows if prov == p and d != "합계") != totals[p][i]:
                raise ValueError("시도·시군구 합계 불일치: " + p)
    return dict(
        rows=rows,
        national_totals=dict(zip(years, national, strict=False)),
        province_count=len(provinces),
        district_count=sum(d != "합계" for _, d, _ in rows),
    )


def verify_reference(totals):
    if not totals or any(NATIONAL_REFERENCE.get(year) != count for year, count in totals.items()):
        raise ValueError("독립 공표 전국 고령가해사고 총계 불일치")


def canonical_name(province, district, allowed_names, year=None):
    if year == 2014 and province == "충북" and district in ("청주시", "청원군"):
        return None
    prefix = PROVINCES.get(province)
    if not prefix:
        return None
    candidate = prefix + " " + district
    if candidate in allowed_names:
        return candidate
    # 명시적 이름 대응 근거와 적용 범위: region-name-crosswalk.json.
    # 다른 시도·기간으로 확대하거나 유사 이름을 자동 추정하지 않는다.
    if (
        province == "부산"
        and district == "진구"
        and year in range(2014, 2020)
        and "부산광역시 부산진구" in allowed_names
    ):
        return "부산광역시 부산진구"
    # 세종시는 TAAS의 단일 기초 통계행과 행안부 광역행이 같은 공간이다.
    if province == "세종" and district in ("세종시", "세종특별자치시") and prefix in allowed_names:
        return prefix
    return None


class PublicClient:
    def __init__(self):
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def post(self, path, data):
        if isinstance(data, dict):
            data = urllib.parse.urlencode(data).encode()
        request = urllib.request.Request(
            BASE + path,
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Referer": BASE + "/OBIP25/analysis/TypicalAnalysis.jsp",
            },
        )
        return self.opener.open(request, timeout=60).read()

    def metadata(self, mode, **params):
        values = dict(className="request", pmode=mode, **params)
        body = (
            "<request>"
            + "".join(
                "<" + k + "><![CDATA[" + str(v) + "]]></" + k + ">" for k, v in values.items()
            )
            + "</request>"
        )
        response = json.loads(self.post("/OBIP25/ajax/procAnalysis.eos", body.encode()))
        if response.get("error"):
            raise ValueError("공개 메타데이터 요청 실패")
        return response["result"]

    def session(self, start, end):
        html = self.post(
            "/OBIP25/analysis/TypicalAnalysis.jsp",
            dict(uid="view", pid="7265", vCondition=f"D1443={start}01~{end}12;"),
        ).decode()
        pattern = self.metadata("loadPattern", patternId=7265)
        dimensions = self.metadata("getDimensionItems", subjectId=131)
        expected = {
            888: "연도",
            903: "노인운전자사고",
            906: "시도",
            907: "시군구",
            1443: "기준년월",
        }
        available = {r["DimAttrId"]: r["LogColName"] for r in dimensions}
        if any(available.get(k) != v for k, v in expected.items()):
            raise ValueError("공개 차원 ID 정의 변경")
        info = json.loads(self.post("/OBIP25/common/ajax/procTest.jsp", dict(className="request")))[
            "result"
        ].split("#%%#")
        labels = ["clientIP", "domainName", "wasIP", "wasName", "wasMacAddress", "clientEmail"]
        values = [info[0], info[1].split("common")[0], *info[2:6]]
        message = "".join(
            ",:" + k + '="' + v + '"' for k, v in zip(labels, values, strict=False)
        ).encode()
        n = int(re.search(r'id="rsaPublicKeyModulus" value="([0-9a-f]+)"', html).group(1), 16)
        e = int(re.search(r'id="rsaPublicKeyExponent" value="([0-9a-f]+)"', html).group(1), 16)
        size = (n.bit_length() + 7) // 8
        padding = bytearray()
        while len(padding) < size - len(message) - 3:
            padding.extend(b for b in os.urandom(size) if b)
        encoded = b"\x00\x02" + bytes(padding[: size - len(message) - 3]) + b"\x00" + message
        token = format(pow(int.from_bytes(encoded, "big"), e, n), "x")
        if len(token) % 2:
            token = "0" + token
        return pattern, dict(
            lic=token, info="10001", trid="1", subjectId="131", odfname="", cubeinfo=""
        )

    def query(self, params, handshake):
        response = self.post(
            "/OBIP25/servlet/OctagonProxyServlet",
            dict(handshake, params=params + ',:data_check="Y"'),
        )
        if ET.fromstring(response).findtext(".//MESSAGE_CODE") != "0":
            raise ValueError("공개 클라이언트 사전 확인 미승인")
        return self.post("/OBIP25/servlet/OctagonProxyServlet", dict(handshake, params=params))


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def require_new_raw_directory(rawdir):
    if any(rawdir.glob("taas-*.xml")):
        raise FileExistsError(
            "기존 TAAS 원본을 덮어쓸 수 없음. 기본 실행으로 해시 검증·재사용; 새 수집은 별도 원본 경로 필요"
        )


def run(fetch=False):
    rawdir = HERE / "data/raw"
    rawdir.mkdir(parents=True, exist_ok=True)
    if fetch:
        require_new_raw_directory(rawdir)
    qcpath = HERE / "taas-qc.json"
    previous = json.loads(qcpath.read_text()) if qcpath.exists() else {}
    sources, data, checks = [], [], []
    client = PublicClient() if fetch else None
    for start, end in BATCHES:
        years = list(range(start, end + 1))
        pages, number, total = [], 1, 1
        if fetch:
            pattern, handshake = client.session(start, end)
        while number <= total:
            path = rawdir / f"taas-{start}-{end}-page-{number}.xml"
            if fetch:
                params = build_parameters(pattern, start, end, number)
                raw = client.query(params, handshake)
                retrieved = datetime.now(UTC).isoformat()
            else:
                raw = path.read_bytes()
                old = next(
                    (
                        s
                        for s in previous.get("sources", [])
                        if s["file"] == str(path.relative_to(HERE))
                    ),
                    None,
                )
                if not old or old["sha256"] != hashlib.sha256(raw).hexdigest():
                    raise ValueError("원본 출처·해시 불일치: " + path.name)
                params, retrieved = old["query"], old["retrieved_at"]
            page = parse_page(raw, years)
            if fetch:
                with path.open("xb") as stream:
                    stream.write(raw)
            total = page["total_pages"]
            if page["page"] != number or total < 1 or total > 20:
                raise ValueError("비정상 페이지 번호")
            pages.append(page)
            sources.append(
                dict(
                    file=str(path.relative_to(HERE)),
                    sha256=hashlib.sha256(raw).hexdigest(),
                    bytes=len(raw),
                    retrieved_at=retrieved,
                    query=params,
                    endpoint=BASE + "/OBIP25/servlet/OctagonProxyServlet",
                    pattern_id=7265,
                    subject_id=131,
                )
            )
            number += 1
        result = reconcile(pages, years)
        verify_reference(result["national_totals"])
        if result["province_count"] != 17:
            raise ValueError("17개 시도 합계 미확보")
        checks.append({k: v for k, v in result.items() if k != "rows"})
        for prov, district, values in result["rows"]:
            for year, value in zip(years, values, strict=False):
                data.append(
                    dict(
                        taas_province=prov, taas_district=district, year=year, older_accidents=value
                    )
                )
    # population.csv의 outcome_year가 해당 연도의 연초 행정구역명 집합이다.
    with (HERE / "data/population.csv").open(encoding="utf-8-sig", newline="") as stream:
        allowed = {}
        for row in csv.DictReader(stream):
            allowed.setdefault(int(row["outcome_year"]), set()).add(row["region_name"])
    matched, unmatched, name_mappings = [], [], []
    for row in data:
        if row["taas_district"] == "합계":
            continue
        name = canonical_name(
            row["taas_province"],
            row["taas_district"],
            allowed.get(row["year"], set()),
            year=row["year"],
        )
        if name is None:
            reason = "해당 연도 행안부 전체명에 정확히 일치하지 않음; 경계·집계단위 수동 확인 필요"
            if (
                row["year"] == 2014
                and row["taas_province"] == "충북"
                and row["taas_district"] in ("청주시", "청원군")
            ):
                reason = (
                    "2014년 청주·청원 연중 통합: 연초 분모와 사고 집계의 경계 일치 확인 전 보류"
                )
            unmatched.append(dict(row, reason=reason))
        else:
            matched.append(
                dict(region_name=name, year=row["year"], older_accidents=row["older_accidents"])
            )
            if row["taas_province"] == "부산" and row["taas_district"] == "진구":
                name_mappings.append(
                    dict(
                        row,
                        region_name=name,
                        reason="부산 16개 구군 중 15개 정확 일치, 유일한 잔여 이름 대응",
                    )
                )
    keys = [(r["region_name"], r["year"]) for r in matched]
    if len(keys) != len(set(keys)):
        raise ValueError("정규화 후 지역×연도 중복")
    write_csv(
        HERE / "data/taas-national.csv",
        ["taas_province", "taas_district", "year", "older_accidents"],
        data,
    )
    write_csv(
        HERE / "data/taas-unmatched.csv",
        ["taas_province", "taas_district", "year", "older_accidents", "reason"],
        unmatched,
    )
    write_csv(HERE / "data/accidents.csv", ["region_name", "year", "older_accidents"], matched)
    qc = dict(
        generated_at=datetime.now(UTC).isoformat(),
        definition=DEFINITION,
        public_report=BASE + "/OBIP25/analysis/TypicalAnalysis.jsp",
        query_translation_sources=[
            BASE + "/OBIP25/analysis/octagon/js/Dropper.js",
            BASE + "/OBIP25/analysis/octagon/js/Viewer.js",
        ],
        filters=dict(
            senior="D903=예",
            date="D1443 year-month interval",
            rows="906:907",
            columns="888",
            measure="334",
        ),
        sources=sources,
        batch_checks=checks,
        matched_rows=len(matched),
        unmatched_rows=len(unmatched),
        name_mappings=name_mappings,
        name_mapping_reference="region-name-crosswalk.json",
        name_mapping_reference_sha256=hashlib.sha256(
            (HERE / "region-name-crosswalk.json").read_bytes()
        ).hexdigest(),
        outputs_sha256={
            name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
            for name in ["data/accidents.csv", "data/taas-national.csv", "data/taas-unmatched.csv"]
        },
        independent_reference=dict(
            expected_totals=NATIONAL_REFERENCE,
            passed=True,
            sources=[
                dict(
                    years=list(range(2014, 2019)),
                    url="https://m.acrc.go.kr/boardDownload.es?bid=1013&list_no=30601&seq=1",
                    publisher="국민권익위원회 붙임1",
                ),
                dict(
                    years=[2019],
                    url="https://www.safetv.go.kr/base/video/view?idx=1314",
                    publisher="행정안전부 안전한TV, TAAS 2020 자료 인용",
                ),
            ],
        ),
        checks=[
            "응답 정의 65+ 가해운전자",
            "연도 열 정확 일치",
            "전체 페이지 수 일치",
            "지역 행 중복 없음",
            "시군구 합=시도 합",
            "시도 합=전국 합",
            "독립 공표 전국 6개년 총계 일치",
        ],
        spatial_note="TAAS 시군구는 사고 발생지 통계. 행안부는 주민등록지. 행정기관 코드나 경계가 동일하다는 검증을 대신하지 않음.",
    )
    qcpath.write_text(json.dumps(qc, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            dict(
                national_totals=[c["national_totals"] for c in checks],
                matched_rows=len(matched),
                unmatched_rows=len(unmatched),
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true")
    run(parser.parse_args().fetch)
