"""행안부 연령별 주민등록인구: 2022-12, 등록구분 전체·남녀 합계."""

import csv
import io
import json
import re
from html.parser import HTMLParser

PAGE = "https://jumin.mois.go.kr/ageStatMonth.do"
LICENSE_PAGE = "https://www.data.go.kr/data/3033304/fileData.do"
REGIONS = "https://jumin.mois.go.kr/selectHangkikcdListAjax.do"
DOWNLOAD = "https://jumin.mois.go.kr/downloadCsvAge.do?searchYearMonth=month&xlsStats=1"
QUERY = dict(
    sltOrgType="2",
    sltOrgLvl1="1100000000",
    sltOrgLvl2="A",
    sltUndefType="",
    searchYearStart="2022",
    searchMonthStart="12",
    searchYearEnd="2022",
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


def download_query(page):
    params = DownloadForm(page).values
    expected = {k: v for k, v in QUERY.items() if k not in {"sum", "searchYearMonth", "tableChart"}}
    if any(params.get(k) != v for k, v in expected.items()) or params.get("category") != "month":
        raise ValueError("인구 조회 응답의 지역·연도·등록구분·연령 조건 불일치")
    if "downloadCsvAge.do" not in page:
        raise ValueError("인구 CSV 다운로드 경로 확인 실패")
    # 공식 chkExcel 함수가 선택한 체크박스를 hidden input으로 옮기는 동작.
    params.update(sum="sum", gender="")
    return params


def region_codes(raw, districts):
    entries = json.loads(raw)["locations"]
    selected = [
        r for r in entries if r.get("sidonm") == "서울특별시" and str(r.get("levels")) == "2"
    ]
    mapping = {r["sikunkunm"]: r["hangkikcd"] for r in selected}
    if len(selected) != 25 or set(mapping) != set(districts) or len(set(mapping.values())) != 25:
        raise ValueError("행안부 서울 25개 구 코드 대응 불일치")
    if any(not re.fullmatch(r"11\d{3}00000", code) for code in mapping.values()):
        raise ValueError("행안부 자치구 코드 형식 불일치")
    return mapping


def population_header():
    prefix = "2022년12월_계_"
    return [
        "행정구역",
        prefix + "총인구수",
        prefix + "연령구간인구수",
        *[prefix + f"{age}세" for age in range(100)],
        prefix + "100세 이상",
    ]


def inspect_population(raw, mapping):
    """연령 합계, 구 합계 및 도시 합계의 모든 연령을 대조한다."""
    reader = csv.reader(io.StringIO(raw.decode("cp949")))
    if next(reader, None) != population_header():
        raise ValueError("인구 CSV의 연월·남녀 합계·1세 단위·최상위 연령 열 불일치")
    districts, codes, city = {}, set(), None
    for row in reader:
        if len(row) != 104:
            raise ValueError("인구 행 길이 불일치")
        match = re.fullmatch(r"서울특별시\s*(.*?)\s*\((\d{10})\)", row[0])
        if not match:
            raise ValueError("인구 행정구역 표기 불일치")
        gu, code = match.groups()
        gu = gu.strip()
        if code in codes:
            raise ValueError("인구 행정구역 중복")
        codes.add(code)
        values = []
        for text in row[1:]:
            if not re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)", text):
                raise ValueError("인구 수치에 음수·소수·비공개·결측 또는 비정상 기호")
            values.append(int(text.replace(",", "")))
        if values[0] != values[1] or sum(values[2:]) != values[0]:
            raise ValueError(f"{gu or '서울'} 총인구·연령구간·연령별 합계 불일치")
        if not gu and code == "1100000000":
            city = values
        elif mapping.get(gu) == code:
            if gu in districts:
                raise ValueError("인구 구명 중복")
            districts[gu] = values
        else:
            raise ValueError("인구 지역 수준 또는 공식 구명·코드 대응 불일치")
    if set(districts) != set(mapping) or city is None:
        raise ValueError("서울 합계 또는 25개 구 누락")
    if any(sum(values[i] for values in districts.values()) != city[i] for i in range(103)):
        raise ValueError("구별 합계와 서울 총계 불일치")
    result = {}
    for gu, values in districts.items():
        total = values[0]
        older = sum(values[2 + 65 :])  # 65세~99세와 100세 이상을 모두 포함.
        result[gu] = {
            "population": total,
            "population_65plus": older,
            "older_population_pct": 100 * older / total if total else None,
            "source_gu_code": mapping[gu],
        }
    check = {
        "source_id": "population",
        "check": "연령 합계·서울 합계·25개 구 코드",
        "status": "ok",
        "districts": len(districts),
        "reference_date": "2022-12-31",
        "seoul_population": city[0],
        "seoul_65plus": sum(city[2 + 65 :]),
        "top_age": "100세 이상",
        "resident_types": "전체(거주자·거주불명자·재외국민), 외국인 제외",
        "gender": "계",
        "unit": "명",
        "gu_code_system": "행안부 주민등록 행정기관 코드 10자리",
    }
    return result, check
