"""정책 전 특성자료: 공개 통계·XLSX·ZIP 취득과 오프라인 검사 (로컬 검토).

가구·면적·시장 값을 검사하고 점포·영역은 공간 버전 미확인으로 집계를 보류한다.
매출 panel.csv 생성이나 make flow 호출은 하지 않는다.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

import characteristics_population as population
import requests
from characteristics_files import (
    DOWNLOAD,
    FILE_SPECS,
    file_query,
    inspect_market,
    inspect_stores,
    inspect_territory,
)

HERE = Path(__file__).resolve().parent
BASE = "https://stat.eseoul.go.kr/statHtml/"
DISTRICTS = tuple(
    "종로구 중구 용산구 성동구 광진구 동대문구 중랑구 성북구 강북구 도봉구 노원구 은평구 서대문구 마포구 양천구 강서구 구로구 금천구 영등포구 동작구 관악구 서초구 강남구 송파구 강동구".split()
)
SPECS = {
    "household": {
        "table": "DT_201004_B010004",
        "columns": ["일반가구 (가구)", "1인 가구 (가구)"],
        "classes": ["001", "001001"],
        "row_label": "동별",
        "page": "https://data.seoul.go.kr/dataList/DT201004B010004/S/2/datasetView.do",
        "metrics": ["households", "single_households", "single_household_pct"],
    },
    "area": {
        "table": "DT_201004_O010001",
        "columns": ["면적 (km²)"],
        "classes": ["001001"],
        "row_label": "자치구별",
        "page": "https://data.seoul.go.kr/dataList/DT201004O010001/S/2/datasetView.do",
        "metrics": ["area_km2"],
    },
}
# 목표 시점이며 실제 관측 기준시점·정의는 자료별로 검증한다.
METRICS = {
    "population": ("주민등록인구", "명", "2022-12-31", "population"),
    "population_65plus": ("65세 이상 인구", "명", "2022-12-31", "population"),
    "older_population_pct": ("고령인구 비율", "%", "2022-12-31", "population"),
    "population_density": ("인구밀도", "명/km²", "2022", "population+area"),
    "households": ("일반가구", "가구", "2022-11-01", "household"),
    "single_households": ("1인 일반가구", "가구", "2022-11-01", "household"),
    "single_household_pct": ("1인 가구 비율", "%", "2022-11-01", "household"),
    "area_km2": ("행정면적", "km²", "2022", "area"),
    "alley_areas": ("골목상권 수", "개", "2022Q4", "territory"),
    "food_stores": ("4업종 점포 합계", "개", "2022Q4", "stores"),
    "markets": ("전통시장 수", "개", "2022H1", "market"),
    "market_present": ("전통시장 존재 여부", "0/1", "2022H1", "market"),
}
for industry in ("CS300007", "CS300008", "CS300009", "CS300010"):
    METRICS[f"stores_{industry}"] = (f"{industry} 점포 수", "개", "2022Q4", "stores")
    METRICS[f"share_{industry}"] = (f"{industry} 점포 구성비", "%", "2022Q4", "stores")


class DataError(ValueError):
    """원자료·응답이 사전 조건을 충족하지 않음."""


class Inputs(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.form = False
        self.hidden = {}
        self.labels = {}
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.form = a.get("id") == "ParamInfo"
        if tag == "input" and self.form:
            if a.get("type") == "hidden" and a.get("name"):
                self.hidden[a["name"]] = a.get("value", "")
            if a.get("id") and a.get("title"):
                self.labels[a["id"]] = (a.get("value", ""), a["title"])

    def handle_endtag(self, tag):
        if tag == "form":
            self.form = False


def dump(path, obj):
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def digest(data):
    return hashlib.sha256(data).hexdigest()


def region_map(data, table):
    if not isinstance(data, dict) or not isinstance(data.get("result"), list):
        raise DataError("자치구 분류 응답 구조 불일치")
    entries = data.get("result", [])
    if any(not isinstance(r, dict) for r in entries):
        raise DataError("자치구 분류 행 구조 불일치")
    names = [r.get("scrKor") for r in entries]
    codes = [r.get("itmId") for r in entries]
    if len(entries) != 25 or set(names) != set(DISTRICTS) or len(set(codes)) != 25:
        raise DataError("자치구 분류의 25개 구·코드 유일성 불일치")
    if any(not isinstance(c, str) or not c for c in codes) or any(
        r.get("tblId") != table or r.get("objVarId") != "A" or r.get("lvl") != 2 for r in entries
    ):
        raise DataError("공식 분류 코드의 통계표·축·지역 수준 불일치")
    return dict(zip(names, codes, strict=True))


def request_artifact(
    session, folder, record, role, endpoint, params, method="POST", extension=None
):
    response = session.request(
        method, endpoint, **{"params" if method == "GET" else "data": params}, timeout=30
    )
    raw = response.content
    filename = role + (
        extension
        or (
            ".csv"
            if role == "data"
            else ".json"
            if role in {"regions", "download", "area_classes"}
            else ".html"
        )
    )
    (folder / filename).write_bytes(raw)
    record["artifacts"][role] = {
        "file": filename,
        "url": endpoint,
        "method": method,
        "query": params.copy(),
        "sha256": digest(raw),
        "bytes": len(raw),
        "http_status": response.status_code,
        "fetched_at": datetime.now(UTC).isoformat(),
    }
    response.raise_for_status()
    return raw


def fetch_source(source, folder, session):
    spec = SPECS[source]
    folder.mkdir(parents=True)
    record = {
        "source_id": source,
        "table": spec["table"],
        "period": "2022",
        "provider": "서울특별시",
        "license": "KOGL-1",
        "url": spec["page"],
        "reference_period": "2022-11-01 00:00"
        if source == "household"
        else "2022（정확한 기준일 미확인）",
        "definition": "인구총조사 일반가구·1인 일반가구"
        if source == "household"
        else "자치구 전체 행정면적, km²",
        "transformation": "1인 일반가구 / 일반가구 × 100"
        if source == "household"
        else "연간 값 보존; 인구밀도 계산 보류",
        "spatial_code_system": "서울통계 orgId=201, 자치구 분류 A (전국 자치구 코드 아님)",
        "industry_version": None,
        "artifacts": {},
        "status": "failed",
    }
    try:
        meta = request_artifact(
            session, folder, record, "metadata", spec["page"], {}, "GET"
        ).decode("utf-8")
        if not any(t in meta for t in ("공공누리 1유형", "공공누리 제1유형")):
            raise DataError("제공 페이지의 공공누리 1유형 표시 확인 실패")
        page = request_artifact(
            session,
            folder,
            record,
            "page",
            BASE + "statHtml.do",
            {"orgId": "201", "tblId": spec["table"], "conn_path": "I2", "mode": "tab"},
            "GET",
        )
        inputs = Inputs(page.decode("utf-8"))
        params = inputs.hidden
        if (
            params.get("tblId") != spec["table"]
            or params.get("orgId") != "201"
            or "dbUser" not in params
        ):
            raise DataError("통계표 조회 폼 식별 실패")
        if inputs.labels.get("itemChkLi0", (None,))[0] != "T001":
            raise DataError("통계 항목 코드 변경")
        query = {
            "orgId": "201",
            "tblId": spec["table"],
            "itmId": "001",
            "objVarId": "A",
            "lvl": "1",
            "searchCondition": "J",
            "dataOpt": "ko",
            "language": "ko",
            "dbUser": params["dbUser"],
        }
        raw_regions = request_artifact(
            session, folder, record, "regions", BASE + "classDivSelect.do", query
        )
        mapping = region_map(json.loads(raw_regions), spec["table"])
        if source == "household":
            for code, label in [("001", "일반가구"), ("001001", "1인 가구")]:
                if inputs.labels.get(f"classChkLi2_1_{code}") != (code + "=", label):
                    raise DataError("가구 분류 코드·정의 변경")
        else:
            query = {**query, "objVarId": "B"}
            classes = json.loads(
                request_artifact(
                    session, folder, record, "area_classes", BASE + "classDivSelect.do", query
                )
            )
            if not any(
                r.get("itmId") == "001001" and r.get("scrKor") == "면적"
                for r in classes.get("result", [])
            ):
                raise DataError("면적 분류 코드·정의 변경")
        fields = [
            {"targetId": "PRD", "targetValue": "", "prdValue": "Y,2022,@"},
            {"targetId": "ITM_ID", "targetValue": "T001", "prdValue": ""},
        ]
        fields += [
            {"targetId": "OV_L1_ID", "targetValue": c, "prdValue": ""} for c in mapping.values()
        ]
        fields += [
            {"targetId": "OV_L2_ID", "targetValue": c, "prdValue": ""} for c in spec["classes"]
        ]
        params.update(
            fieldList=json.dumps(fields),
            rowAxis="A",
            colAxis="TIME,B",
            classAllArr=json.dumps(
                [{"objVarId": "A", "ovlSn": "1"}, {"objVarId": "B", "ovlSn": "2"}]
            ),
            view="csv",
            viewKind="2",
            viewSubKind="2_3",
            periodCo="99",
            smblYn="Y",
            isFirst="N",
        )
        response = json.loads(
            request_artifact(session, folder, record, "download", BASE + "downGrid.do", params)
        )
        filename = response.get("file", "")
        if not isinstance(filename, str) or not filename.lower().endswith(".csv"):
            raise DataError("CSV 생성 응답의 파일명 불일치")
        record["original_filename"] = filename
        params["file"] = filename
        raw = request_artifact(session, folder, record, "data", BASE + "downNormal.do", params)
        parse_csv(raw, spec)  # HTTP 200인 오류 HTML도 성공으로 표시하지 않는다.
        record["status"] = "downloaded"
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError) as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        dump(folder / "source.json", record)
    return record


def parse_csv(raw, spec):
    try:
        rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    except UnicodeError as exc:
        raise DataError("UTF-8 CSV 해석 실패") from exc
    n = len(spec["columns"])
    if (
        len(rows) < 3
        or rows[0] != [spec["row_label"], *(["2022"] * n)]
        or rows[1] != [spec["row_label"], *spec["columns"]]
    ):
        raise DataError("CSV의 연도·열 이름·단위 불일치 또는 오류 응답")
    data = {}
    for row in rows[2:]:
        if not row:
            continue
        if len(row) != n + 1 or row[0] not in DISTRICTS:
            raise DataError("CSV 행 구조 또는 자치구 범위 불일치")
        if row[0] in data:
            raise DataError(f"자치구 중복: {row[0]}")
        data[row[0]] = row[1:]
    return data


def numeric(raw, integer=True):
    raw = raw.strip()
    if raw.lower() == "x":
        return None, "suppressed", "제공기관 비공개 표기 x"
    if raw in {"", "-", "..", "..."}:
        return None, "unresolved", f"원문 결측·기호: {raw!r}"
    if not re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?", raw):
        raise DataError(f"숫자 형식 불일치: {raw!r}")
    try:
        value = float(raw.replace(",", ""))
    except ValueError as exc:
        raise DataError(f"숫자·기호 해석 불가: {raw!r}") from exc
    if not math.isfinite(value) or value < 0 or (integer and not value.is_integer()):
        raise DataError(f"유효하지 않은 {'정수' if integer else '수치'}: {raw!r}")
    return int(value) if integer else value, "verified", ""


def verified_bytes(folder, record, role):
    artifact = record["artifacts"][role]
    path = (folder / artifact["file"]).resolve()
    if not path.is_relative_to(folder.resolve()):
        raise DataError("스냅샷 외부 파일 경로")
    raw = path.read_bytes()
    if artifact.get("http_status") != 200:
        raise DataError(f"정상 HTTP 응답이 아님: {role}")
    if digest(raw) != artifact["sha256"]:
        raise DataError(f"원본 해시 불일치: {role}")
    return raw


def fetch_file(source, folder, session):
    spec = FILE_SPECS[source]
    folder.mkdir(parents=True)
    record = {
        "source_id": source,
        "dataset_id": spec["id"],
        "period": spec["period"],
        "url": spec["page"],
        "license": "KOGL-1",
        "original_filename": spec["filename"],
        "status": "failed",
        "artifacts": {},
    }
    try:
        meta = request_artifact(
            session, folder, record, "metadata", spec["page"], {"view": "detail"}, "GET"
        ).decode("utf-8")
        if "공공누리 1유형" not in meta:
            raise DataError("제공 페이지의 이용 조건 확인 실패")
        params = file_query(meta, spec)
        raw = request_artifact(
            session,
            folder,
            record,
            "data",
            DOWNLOAD,
            params,
            extension=Path(spec["filename"]).suffix,
        )
        if source == "market":
            _, _, record["definition"] = inspect_market(raw, DISTRICTS)
        elif source == "stores":
            _, record["inspection"] = inspect_stores(raw)
        else:
            _, record["inspection"] = inspect_territory(raw, DISTRICTS)
        record["status"] = "downloaded"
    except (
        requests.RequestException,
        ValueError,
        KeyError,
        TypeError,
        OSError,
        BadZipFile,
        ParseError,
    ) as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        dump(folder / "source.json", record)
    return record


def build_files(snapshot, rows, sources, quality):
    failed = False
    store_records, territory_mapping = None, None
    store_missing = []
    for source, spec in FILE_SPECS.items():
        folder = snapshot / source
        if not (folder / "source.json").exists():
            continue
        metrics = [m for m, definition in METRICS.items() if definition[3] == source]
        reason = "2022Q4 점포와 2023년 공개 영역의 공간 버전 호환성 미확인"
        try:
            record = json.loads((folder / "source.json").read_text(encoding="utf-8"))
            sources.append({**record, "snapshot": str(folder.resolve())})
            if any(
                record.get(k) != v
                for k, v in {
                    "source_id": source,
                    "dataset_id": spec["id"],
                    "period": spec["period"],
                    "license": "KOGL-1",
                    "original_filename": spec["filename"],
                    "status": "downloaded",
                }.items()
            ):
                raise DataError(record.get("error", "파일 출처·시점·취득 상태 불일치"))
            for role in record["artifacts"]:
                verified_bytes(folder, record, role)
            raw = verified_bytes(folder, record, "data")
            if source == "market":
                result, checks, definition = inspect_market(raw, DISTRICTS)
                quality.extend(checks)
                quality.append(
                    {"source_id": source, "check": "대상·기준시점", "status": "ok", **definition}
                )
                for gu, values in result.items():
                    for metric, (value, status, why) in values.items():
                        rows[gu, metric].update(value=value, status=status, reason=why)
                continue
            if source == "stores":
                store_records, check = inspect_stores(raw)
                store_missing = check["missing_pairs"]
                if store_missing:
                    reason += "; 누락된 상권×업종 행의 의미 미확인(0 대체 금지)"
                    quality.append(
                        {
                            "source_id": source,
                            "check": "상권×업종 누락",
                            "status": "unresolved",
                            "count": len(store_missing),
                            "reason": "행 부재가 점포 0을 뜻하는지 미확인",
                        }
                    )
            else:
                territory_mapping, check = inspect_territory(raw, DISTRICTS)
            quality.append(check)
            quality.append(
                {
                    "source_id": source,
                    "check": "공간 버전",
                    "status": "unresolved",
                    "reason": reason,
                }
            )
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            BadZipFile,
            ParseError,
        ) as exc:
            failed = True
            reason = str(exc)
            quality.append(
                {"source_id": source, "check": "원본·스키마", "status": "failed", "reason": reason}
            )
        for gu in DISTRICTS:
            for metric in metrics:
                rows[gu, metric].update(status="unresolved", reason=reason)
    if store_records is not None and territory_mapping is not None:
        missing = sorted({r["area"] for r in store_records} - territory_mapping.keys())
        quality.append(
            {
                "source_id": "stores+territory",
                "check": "상권 코드 연결 진단",
                "status": "unresolved",
                "missing_codes": missing,
                "missing_pairs_by_gu": {
                    gu: sum(territory_mapping.get(area) == gu for area, _ in store_missing)
                    for gu in DISTRICTS
                },
                "reason": "코드 연결 여부와 공간 버전 호환성은 별개; 구별 합산 보류",
            }
        )
    return failed


def fetch_population(folder, session):
    folder.mkdir(parents=True)
    record = {
        "source_id": "population",
        "period": "2022-12",
        "provider": "행정안전부 주민과",
        "url": population.PAGE,
        "license": "other",
        "license_notes": "이용허락범위 제한 없음",
        "license_url": population.LICENSE_PAGE,
        "status": "failed",
        "artifacts": {},
    }
    try:
        license_page = request_artifact(
            session, folder, record, "metadata", population.LICENSE_PAGE, {}, "GET"
        ).decode("utf-8")
        if "이용허락범위 제한 없음" not in license_page or population.PAGE not in license_page:
            raise DataError("동일 인구 통계의 이용 조건·제공 URL 확인 실패")
        regions = request_artifact(session, folder, record, "regions", population.REGIONS, {})
        mapping = population.region_codes(regions, DISTRICTS)
        page = request_artifact(
            session, folder, record, "page", population.PAGE, population.QUERY
        ).decode("utf-8")
        params = population.download_query(page)
        raw = request_artifact(session, folder, record, "data", population.DOWNLOAD, params)
        _, record["inspection"] = population.inspect_population(raw, mapping)
        record["original_filename"] = "downloadCsvAge.do 응답 CSV (서버 파일명 미기록)"
        record["status"] = "downloaded"
    except (
        requests.RequestException,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        OSError,
    ) as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        dump(folder / "source.json", record)
    return record


def build_population(snapshot, rows, sources, quality):
    folder = snapshot / "population"
    if not (folder / "source.json").exists():
        return False
    try:
        record = json.loads((folder / "source.json").read_text(encoding="utf-8"))
        sources.append({**record, "snapshot": str(folder.resolve())})
        expected = {
            "source_id": "population",
            "period": "2022-12",
            "url": population.PAGE,
            "license": "other",
            "license_notes": "이용허락범위 제한 없음",
            "status": "downloaded",
        }
        if any(record.get(k) != v for k, v in expected.items()):
            raise DataError(record.get("error", "인구 출처 기록 불일치"))
        for role in record["artifacts"]:
            verified_bytes(folder, record, role)
        page = verified_bytes(folder, record, "page").decode("utf-8")
        if record["artifacts"]["data"]["query"] != population.download_query(page):
            raise DataError("인구 CSV 요청과 조회 화면의 조건 불일치")
        mapping = population.region_codes(verified_bytes(folder, record, "regions"), DISTRICTS)
        result, check = population.inspect_population(
            verified_bytes(folder, record, "data"), mapping
        )
        quality.append(check)
        for gu, values in result.items():
            for metric in ("population", "population_65plus", "older_population_pct"):
                value = values[metric]
                rows[gu, metric].update(
                    value=value,
                    status="verified" if value is not None else "undefined",
                    reason="" if value is not None else "총인구 분모 0",
                    source_gu_code=values["source_gu_code"],
                    source_gu_code_system="행안부 주민등록 행정기관 코드 10자리",
                )
            rows[gu, "older_population_pct"].update(
                numerator=values["population_65plus"], denominator=values["population"]
            )
        return False
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        quality.append(
            {
                "source_id": "population",
                "check": "원본·조건·합계",
                "status": "failed",
                "reason": str(exc),
            }
        )
        for gu in DISTRICTS:
            for metric in ("population", "population_65plus", "older_population_pct"):
                rows[gu, metric].update(value=None, status="unresolved", reason=str(exc))
        return True


def build(snapshot, output):
    if not any(
        (snapshot / source / "source.json").is_file()
        for source in [*SPECS, *FILE_SPECS, "population"]
    ):
        raise DataError("source.json이 없는 스냅샷")
    rows = {}
    for gu in DISTRICTS:
        for metric, (label, unit, period, source) in METRICS.items():
            reason = "이 검토본에서는 아직 수집하지 않은 자료"
            if source == "population":
                reason = "인구 이용 조건 확인 완료; 2022-12 CSV 취득·검사 미실행"
            rows[gu, metric] = {
                "gu_code": "",
                "gu_code_system": "",
                "gu_name": gu,
                "source_gu_code": "",
                "source_gu_code_system": "",
                "metric": metric,
                "label": label,
                "value": None,
                "unit": unit,
                "period": period,
                "numerator": None,
                "denominator": None,
                "raw_value": "",
                "status": "not_collected",
                "reason": reason,
                "source_id": source,
            }
    quality, sources, codes = [], [], {}
    failed = False
    for source, spec in SPECS.items():
        folder = snapshot / source
        if not (folder / "source.json").exists():
            quality.append(
                {
                    "source_id": source,
                    "status": "unresolved",
                    "check": "snapshot",
                    "reason": "미수집",
                }
            )
            continue
        try:
            record = json.loads((folder / "source.json").read_text(encoding="utf-8"))
            sources.append({**record, "snapshot": str(folder.resolve())})
            if record.get("status") != "downloaded":
                raise DataError(record.get("error", "취득 실패"))
            if (
                record.get("source_id") != source
                or record.get("table") != spec["table"]
                or record.get("period") != "2022"
                or record.get("license") != "KOGL-1"
            ):
                raise DataError("출처 기록의 자료원·연도·이용 조건 불일치")
            # 모든 취득 응답의 해시를 확인한다.
            for role in record["artifacts"]:
                verified_bytes(folder, record, role)
            mapping = region_map(
                json.loads(verified_bytes(folder, record, "regions")), spec["table"]
            )
            if codes and codes != mapping:
                raise DataError("두 통계표의 자치구 코드 대응 불일치")
            codes = mapping
            data = parse_csv(verified_bytes(folder, record, "data"), spec)
            quality.append(
                {
                    "source_id": source,
                    "check": "구 범위",
                    "status": "ok" if len(data) == 25 else "unresolved",
                    "missing": sorted(set(DISTRICTS) - set(data)),
                    "observed": len(data),
                }
            )
            for gu in DISTRICTS:
                if gu not in data:
                    for metric in spec["metrics"]:
                        rows[gu, metric].update(status="unresolved", reason="원자료 자치구 행 누락")
                    continue
                try:
                    parsed = [numeric(v, integer=source == "household") for v in data[gu]]
                    if source == "area" and parsed[0][0] == 0:
                        raise DataError("면적은 양수여야 함")
                    if (
                        source == "household"
                        and all(v[0] is not None for v in parsed)
                        and parsed[1][0] > parsed[0][0]
                    ):
                        raise DataError("1인 가구가 일반가구 합계보다 큼")
                    for metric, raw, (value, status, reason) in zip(
                        spec["metrics"], data[gu], parsed, strict=False
                    ):
                        rows[gu, metric].update(
                            value=value, status=status, reason=reason, raw_value=raw
                        )
                    if source == "household":
                        total, single = parsed
                        ratio = rows[gu, "single_household_pct"]
                        ratio.update(numerator=single[0], denominator=total[0])
                        if any(v[0] is None for v in parsed):
                            ratio.update(
                                status="suppressed"
                                if any(v[1] == "suppressed" for v in parsed)
                                else "unresolved",
                                reason="분자 또는 분모 미확인",
                            )
                        elif total[0] == 0:
                            ratio.update(status="undefined", reason="일반가구 분모 0")
                        else:
                            ratio.update(
                                value=100 * single[0] / total[0], status="verified", reason=""
                            )
                    quality.append(
                        {
                            "source_id": source,
                            "gu_name": gu,
                            "check": "수치·분모",
                            "status": "ok"
                            if all(rows[gu, m]["status"] == "verified" for m in spec["metrics"])
                            else "unresolved",
                        }
                    )
                except DataError as exc:
                    failed = True
                    for metric in spec["metrics"]:
                        rows[gu, metric].update(value=None, status="unresolved", reason=str(exc))
                    quality.append(
                        {
                            "source_id": source,
                            "gu_name": gu,
                            "check": "수치·분모",
                            "status": "failed",
                            "reason": str(exc),
                        }
                    )
            if source == "area":
                quality.append(
                    {
                        "source_id": source,
                        "check": "정확한 기준일",
                        "status": "unresolved",
                        "reason": "2022년 연간 면적과 km² 확인. 정확한 기준일 미확인으로 인구밀도 산출 보류",
                    }
                )
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            failed = True
            for gu in DISTRICTS:
                for metric in spec["metrics"]:
                    rows[gu, metric].update(value=None, status="unresolved", reason=str(exc))
            quality.append(
                {
                    "source_id": source,
                    "check": "원본·스키마",
                    "status": "failed",
                    "reason": str(exc),
                }
            )
    failed = build_files(snapshot, rows, sources, quality) or failed
    failed = build_population(snapshot, rows, sources, quality) or failed
    for gu in DISTRICTS:
        rows[gu, "population_density"].update(
            status="unresolved",
            reason="면적의 정확한 기준일 미확인"
            if rows[gu, "population"]["status"] == "verified"
            else "인구 미확인·면적의 정확한 기준일 미확인",
        )
        for metric in METRICS:
            rows[gu, metric].update(
                gu_code=codes.get(gu, ""),
                gu_code_system="서울통계 orgId=201, 자치구 분류 A" if codes else "",
            )
    output.mkdir(parents=True, exist_ok=True)
    with (output / "values.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(next(iter(rows.values()))))
        writer.writeheader()
        writer.writerows(rows.values())
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=HERE, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    dump(
        output / "sources.json",
        {
            "sources": sources,
            "code_commit": commit,
            "code_sha256": digest(Path(__file__).read_bytes()),
            "file_parser_sha256": digest((HERE / "characteristics_files.py").read_bytes()),
            "population_parser_sha256": digest(
                (HERE / "characteristics_population.py").read_bytes()
            ),
            "generated_at": datetime.now(UTC).isoformat(),
            "note": "미커밋 코드도 code_sha256으로 식별한다",
        },
    )
    counts = {
        state: sum(r["status"] == state for r in rows.values())
        for state in ("verified", "not_collected", "suppressed", "unresolved", "undefined")
    }
    dump(
        output / "quality.json",
        {"status": "failed" if failed else "partial", "counts": counts, "checks": quality},
    )
    with (output / "review.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        metrics = [
            "population",
            "population_65plus",
            "older_population_pct",
            "households",
            "single_households",
            "single_household_pct",
            "area_km2",
            "markets",
            "market_present",
            "food_stores",
            "alley_areas",
        ]
        writer.writerow(
            [
                "구",
                *[f"{METRICS[m][0]} ({METRICS[m][1]}, {METRICS[m][2]})" for m in metrics],
                "보류·미수집 지표 수",
                "보류 사유",
            ]
        )
        for gu in DISTRICTS:
            writer.writerow(
                [
                    gu,
                    *[rows[gu, m]["value"] for m in metrics],
                    sum(rows[gu, m]["status"] != "verified" for m in METRICS),
                    " / ".join(
                        dict.fromkeys(
                            rows[gu, m]["reason"]
                            for m in metrics
                            if rows[gu, m]["status"] != "verified"
                        )
                    ),
                ]
            )
    print(
        json.dumps(
            {"output": str(output), "counts": counts, "input_errors": failed}, ensure_ascii=False
        )
    )
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="공개 특성자료를 새 스냅샷에 취득하고 로컬 출력 생성")
    fetch.add_argument(
        "--sources",
        nargs="+",
        choices=[*SPECS, *FILE_SPECS, "population"],
        default=[*SPECS, *FILE_SPECS, "population"],
    )
    fetch.add_argument("--raw-root", type=Path, default=HERE / "data/raw/characteristics")
    fetch.add_argument("--output", type=Path, default=HERE / "data/characteristics")
    offline = sub.add_parser("build", help="스냅샷에서 네트워크 없이 다시 검사·계산")
    offline.add_argument("--snapshot", type=Path, required=True)
    offline.add_argument("--output", type=Path, default=HERE / "data/characteristics")
    args = parser.parse_args()
    if args.command == "fetch":
        args.raw_root.mkdir(parents=True, exist_ok=True)
        snapshot = Path(
            tempfile.mkdtemp(
                prefix=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-"), dir=args.raw_root
            )
        )
        print(f"snapshot: {snapshot}", flush=True)
        with requests.Session() as session:
            for source in dict.fromkeys(args.sources):
                if source == "population":
                    fetch_population(snapshot / source, session)
                elif source in FILE_SPECS:
                    fetch_file(source, snapshot / source, session)
                else:
                    fetch_source(source, snapshot / source, session)
        return build(snapshot, args.output)
    return build(args.snapshot, args.output)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DataError as exc:
        raise SystemExit(f"입력 오류: {exc}") from exc
