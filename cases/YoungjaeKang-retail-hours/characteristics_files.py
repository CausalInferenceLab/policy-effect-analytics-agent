"""공개 XLSX/ZIP 특성자료의 파일 선택과 사례별 검사. 원자료는 배포하지 않는다."""

from __future__ import annotations

import csv
import io
import re
import struct
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET
from zipfile import ZipFile

FILE_SPECS = {
    "market": {
        "id": "OA-1176",
        "kind": "F",
        "filename": "전통시장 현황(2022.상반기 기준).xlsx",
        "period": "2022H1",
    },
    "stores": {
        "id": "OA-15577",
        "kind": "A",
        "filename": "서울시_상권분석서비스(점포-상권)_2022년.zip",
        "period": "2022Q4",
    },
    "territory": {
        "id": "OA-15560",
        "kind": "S",
        "filename": "서울시 상권분석서비스(영역-상권).zip",
        "period": "2023 파일; 2022Q4 호환성 미확인",
    },
}
for spec in FILE_SPECS.values():
    spec["page"] = f"https://data.seoul.go.kr/dataList/{spec['id']}/{spec['kind']}/1/datasetView.do"
DOWNLOAD = "https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do?&useCache=false"
INDUSTRIES = ("CS300007", "CS300008", "CS300009", "CS300010")


class FileInputs(HTMLParser):
    def __init__(self, text, filename):
        super().__init__()
        self.in_form = False
        self.params = {}
        self.sequences = set()
        self.filename = filename
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.in_form = a.get("name") == "frmFile" or a.get("id") == "frmFile"
        if tag == "input" and self.in_form and a.get("name"):
            self.params[a["name"]] = a.get("value", "")
        if a.get("title") == self.filename:
            match = re.search(
                r"downloadFile\('([0-9]+)'\)", a.get("onclick", "") + a.get("href", "")
            )
            if match:
                self.sequences.add(match[1])

    def handle_endtag(self, tag):
        if tag == "form":
            self.in_form = False


def file_query(text, spec):
    parser = FileInputs(text, spec["filename"])
    if (
        parser.params.get("infId") != spec["id"]
        or len(parser.sequences) != 1
        or not parser.params.get("infSeq")
    ):
        raise ValueError("과거 파일명·다운로드 폼 식별 실패")
    return {**parser.params, "seq": next(iter(parser.sequences))}


def archive(raw):
    z = ZipFile(io.BytesIO(raw))
    if (
        len(z.namelist()) != len(set(z.namelist()))
        or sum(i.file_size for i in z.infolist()) > 150_000_000
    ):
        z.close()
        raise ValueError("ZIP 중복 멤버 또는 해제 크기 제한 초과")
    return z


def market_rows(raw):
    """이 파일의 문자열/숫자 셀만 읽는다. 총계 계산식은 캐시 값만 읽고 상세 행 수로 별도 대조한다."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with archive(raw) as z:
        workbook = ET.fromstring(z.read("xl/workbook.xml"))
        sheets = workbook.findall("m:sheets/m:sheet", ns)
        sheet = [s for s in sheets if s.attrib["name"] == "시장목록"]
        if len(sheet) != 1:
            raise ValueError("시장목록 시트 없음/중복")
        rid = sheet[0].attrib[
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        ]
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        targets = [r.attrib["Target"] for r in rels if r.attrib["Id"] == rid]
        if len(targets) != 1:
            raise ValueError("시장목록 시트 연결 불일치")
        target = (
            str(PurePosixPath("xl") / targets[0])
            if not targets[0].startswith("/")
            else targets[0].lstrip("/")
        )
        ss = [
            "".join(t.text or "" for t in s.findall(".//m:t", ns))
            for s in ET.fromstring(z.read("xl/sharedStrings.xml"))
        ]
        root = ET.fromstring(z.read(target))
        result = []
        for row in root.findall("m:sheetData/m:row", ns):
            values = {}
            formulas = []
            for cell in row:
                col = re.sub(r"\d", "", cell.attrib["r"])
                if col not in {"D", "E", "F", "G", "H", "I"}:
                    continue
                if cell.find("m:f", ns) is not None:
                    formulas.append(col)
                v = cell.find("m:v", ns)
                if v is not None:
                    if cell.attrib.get("t") == "s":
                        index = int(v.text)
                        if not 0 <= index < len(ss):
                            raise ValueError("XLSX 공유 문자열 참조 범위 불일치")
                        text = ss[index]
                    else:
                        text = v.text
                    if text is None:
                        raise ValueError("XLSX 빈 값 셀")
                    values[col] = text.strip()
                elif cell.attrib.get("t") == "inlineStr":
                    values[col] = "".join(t.text or "" for t in cell.findall(".//m:t", ns)).strip()
            if formulas and (formulas != ["G"] or values.get("F") != "계"):
                raise ValueError("총계 외 집계 대상에 계산식 셀 존재")
            if values:
                result.append(values)
        return result


def positive_integer(text, zero=True):
    if not re.fullmatch(r"\d+", text):
        raise ValueError(f"비음수 정수 아님: {text!r}")
    value = int(text)
    if not zero and value == 0:
        raise ValueError("양수여야 함")
    return value


def inspect_market(raw, districts):
    return validate_market(market_rows(raw), districts)


def validate_market(rows, districts):
    if not rows or rows[0].get("D") != "서울시 자치구별 전통시장 현황(2022년 상반기)":
        raise ValueError("시장 파일 내부 기준시점 불일치")
    header = next((i for i, r in enumerate(rows) if r.get("G") == "시장명"), None)
    if header is None or any(
        rows[header].get(k) != v
        for k, v in {"E": "자치구", "F": "연번", "H": "형태", "I": "신주소\n(구주소)"}.items()
    ):
        raise ValueError("시장 열 정의 변경")
    totals, entries = {}, defaultdict(list)
    included, excluded = {"건물형", "골목형", "혼합형"}, {"상점가", "지하도상가"}
    aliases = []
    for row in rows[header + 1 :]:
        gu = row.get("E", "")
        if gu == "동대문":
            # 축약 구명을 주소 원문으로 검증한다. 임의 유사 문자열 매칭은 하지 않는다.
            if row.get("F") != "계" and not row.get("I", "").startswith("동대문구 "):
                raise ValueError("동대문 축약 구명의 주소 근거 불일치")
            gu = "동대문구"
            aliases.append(row.get("F"))
        if gu not in districts:
            raise ValueError(f"시장 자치구 범위 불일치: {gu}")
        if row.get("F") == "계":
            if gu in totals:
                raise ValueError("구별 총계 중복")
            totals[gu] = positive_integer(row.get("G", ""))
            continue
        positive_integer(row.get("F", ""), zero=False)
        if row.get("H") not in included | excluded or not row.get("G") or not row.get("I"):
            raise ValueError("시장 형태·이름·주소 미확인")
        entries[gu].append(row)
    if set(totals) != set(districts) or any(len(entries[g]) != totals[g] for g in districts):
        raise ValueError("시장 구별 총계와 상세 목록 불일치")
    result, checks = {}, []
    for gu in districts:
        rs = entries[gu]
        names = Counter(r["G"] for r in rs)
        serials = Counter(r["F"] for r in rs)
        if any(n > 1 for n in names.values()):
            raise ValueError(f"{gu} 시장명 중복 후보")
        selected = [r for r in rs if r["H"] in included]
        addresses = Counter(re.sub(r"\s+", "", r["I"]) for r in selected)
        collisions = [r["G"] for r in selected if addresses[re.sub(r"\s+", "", r["I"])] > 1]
        count = len(selected)
        result[gu] = {
            "markets": (
                None,
                "unresolved",
                "동일 주소의 서로 다른 시장명: " + ", ".join(collisions),
            )
            if collisions
            else (count, "verified", ""),
            "market_present": (int(count > 0), "verified", ""),
        }
        checks.append(
            {
                "source_id": "market",
                "gu_name": gu,
                "check": "형태·총계·중복 후보",
                "status": "unresolved" if collisions else "ok",
                "listed": len(rs),
                "types": dict(Counter(r["H"] for r in rs)),
                "same_address_names": collisions,
                "repeated_serials": [s for s, n in serials.items() if n > 1],
            }
        )
    return (
        result,
        checks,
        {
            "period": "2022H1",
            "exact_date": None,
            "definition": "형태=건물형·골목형·혼합형 포함; 상점가·지하도상가 제외. 법적 등록 지위는 판정하지 않음",
            "listed": sum(totals.values()),
            "included_rows": sum(r["H"] in included for rs in entries.values() for r in rs),
            "gu_alias": {"동대문": "동대문구"},
            "alias_address_rows_checked": len(aliases) - 1,
        },
    )


def inspect_stores(raw):
    required = [
        "기준_년분기_코드",
        "상권_구분_코드",
        "상권_구분_코드_명",
        "상권_코드",
        "서비스_업종_코드",
        "점포_수",
        "유사_업종_점포_수",
        "프랜차이즈_점포_수",
    ]
    with archive(raw) as z:
        files = [n for n in z.namelist() if n.endswith(".csv")]
        if files != ["서울시_상권분석서비스(점포-상권)_2022년.csv"]:
            raise ValueError("점포 ZIP 내부 파일명·연도 불일치")
        reader = csv.DictReader(io.StringIO(z.read(files[0]).decode("cp949")))
        if (
            not reader.fieldnames
            or len(reader.fieldnames) != len(set(reader.fieldnames))
            or not set(required) <= set(reader.fieldnames)
        ):
            raise ValueError("점포 필수 열 부재/중복")
        selected, periods, keys, all_areas = [], set(), set(), set()
        total_rows = 0
        for r in reader:
            total_rows += 1
            period = r["기준_년분기_코드"]
            if period not in {"20221", "20222", "20223", "20224"}:
                raise ValueError("점포 분기 범위 불일치")
            periods.add(period)
            if period != "20224" or r["상권_구분_코드"] != "A":
                continue
            if r["상권_구분_코드_명"] != "골목상권" or not r["상권_코드"]:
                raise ValueError("골목상권 분류 불일치")
            all_areas.add(r["상권_코드"])
            key = (r["상권_코드"], r["서비스_업종_코드"])
            if key in keys:
                raise ValueError("2022Q4 골목상권×업종 중복")
            keys.add(key)
            if r["서비스_업종_코드"] not in INDUSTRIES:
                continue
            ordinary, total, franchise = [
                positive_integer(r[c])
                for c in ["점포_수", "유사_업종_점포_수", "프랜차이즈_점포_수"]
            ]
            if total != ordinary + franchise:
                raise ValueError("전체 점포 ≠ 일반 + 프랜차이즈")
            selected.append({"area": key[0], "industry": key[1], "total": total})
    if periods != {"20221", "20222", "20223", "20224"} or set(
        r["industry"] for r in selected
    ) != set(INDUSTRIES):
        raise ValueError("점포 분기·업종 누락")
    missing = [(a, i) for a in sorted(all_areas) for i in INDUSTRIES if (a, i) not in keys]
    return selected, {
        "source_id": "stores",
        "check": "2022Q4 골목상권 점포 원본",
        "status": "ok",
        "file_rows": total_rows,
        "selected_rows": len(selected),
        "observed_alley_areas": len(all_areas),
        "missing_area_industry_pairs": len(missing),
        "missing_pairs": missing,
        "note": "누락된 상권×업종 행은 0으로 채우지 않음; 구별 집계는 공간 버전 확인 전 보류",
    }


def inspect_territory(raw, districts):
    """ZIP의 DBF 속성만 읽는다. 코드 일치로 공간 버전 호환을 확정하지 않는다."""
    with archive(raw) as z:
        names = [n for n in z.namelist() if n.endswith(".dbf")]
        if len(names) != 1 or z.read(names[0][:-4] + ".cpg").decode().strip() != "UTF-8":
            raise ValueError("영역 DBF·문자 인코딩 불일치")
        raw = z.read(names[0])
    if len(raw) < 32:
        raise ValueError("영역 DBF 헤더 잘림")
    n, header, width = struct.unpack_from("<IHH", raw, 4)
    if (
        header < 33
        or header > len(raw)
        or (header - 33) % 32
        or len(raw) < header + n * width
        or raw[header - 1] != 13
    ):
        raise ValueError("영역 DBF 길이·헤더 불일치")
    fields = []
    for offset in range(32, header - 1, 32):
        descriptor = raw[offset : offset + 32]
        fields.append((descriptor[:11].split(b"\0")[0].decode("ascii"), descriptor[16]))
    required = {"TRDAR_SE_C", "TRDAR_CD", "SIGNGU_CD", "SIGNGU_CD_"}
    if not required <= {f[0] for f in fields} or sum(f[1] for f in fields) + 1 != width:
        raise ValueError("영역 DBF 열 불일치")
    mapping, gu_codes = {}, {}
    for index in range(n):
        record = raw[header + index * width : header + (index + 1) * width]
        if record[:1] != b" ":
            raise ValueError("영역 삭제/비정상 레코드")
        offset, values = 1, {}
        for name, size in fields:
            values[name] = record[offset : offset + size].decode("utf-8").strip()
            offset += size
        code, gu = values["SIGNGU_CD"], values["SIGNGU_CD_"]
        if (
            gu not in districts
            or not re.fullmatch(r"11\d{3}", code)
            or (gu in gu_codes and gu_codes[gu] != code)
        ):
            raise ValueError("영역의 자치구명·코드 대응 불일치")
        gu_codes[gu] = code
        if values["TRDAR_SE_C"] == "A":
            area = values["TRDAR_CD"]
            if not area or area in mapping:
                raise ValueError("상권 코드 중복/복수 연결")
            mapping[area] = gu
    if set(gu_codes) != set(districts) or len(set(gu_codes.values())) != 25:
        raise ValueError("영역 자료 자치구 누락/복수 연결")
    return mapping, {
        "source_id": "territory",
        "check": "영역 코드 대응",
        "status": "ok",
        "records": n,
        "alley_areas": len(mapping),
        "gu_codes": gu_codes,
        "version_status": "unresolved",
        "reason": "2023년 공개 영역과 2022Q4 점포의 공간 버전 호환성 미확인",
    }
