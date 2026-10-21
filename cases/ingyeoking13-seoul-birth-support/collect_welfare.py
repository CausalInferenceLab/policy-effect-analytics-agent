"""복지로 현행 사업 목록·상세 스냅샷. 과거 정책 이력이나 분석 패널은 생성하지 않는다."""

from __future__ import annotations

import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

import requests

BASE_URL = "https://apis.data.go.kr/B554287/LocalGovernmentWelfareInformations"
SOURCE_URL = "https://www.data.go.kr/data/15108347/openapi.do"
CANDIDATE_PATTERN = "출산|출생|신생아|임신|임산부|산모|산후|첫만남"
CANDIDATE_FIELDS = ("servNm", "servDgst", "lifeNmArray")
PAGE_SIZE = 100


def parse_response(content: bytes) -> ET.Element:
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        raise ValueError("복지 API가 XML 응답을 반환하지 않았습니다") from None
    code = root.findtext(".//resultCode")
    if code != "0":
        # 오류 본문·요청 URL에는 인증키가 포함될 수 있으므로 출력하지 않는다.
        raise ValueError("복지 API 응답 실패: 활용승인·인증키·호출 한도를 확인하세요")
    return root


def xml_record(element: ET.Element) -> dict:
    """반복되는 문의처·웹사이트·근거법령도 손실 없이 보존한다."""
    record = {}
    for child in element:
        value = xml_record(child) if len(child) else (child.text or "")
        if child.tag in record:
            if not isinstance(record[child.tag], list):
                record[child.tag] = [record[child.tag]]
            record[child.tag].append(value)
        else:
            record[child.tag] = value
    return record


def is_candidate(record: dict) -> bool:
    return bool(
        re.search(CANDIDATE_PATTERN, " ".join(record.get(field, "") for field in CANDIDATE_FIELDS))
    )


def request_xml(session, operation: str, query: dict, key: str) -> tuple[bytes, ET.Element]:
    try:
        response = session.get(
            f"{BASE_URL}/{operation}",
            params={"serviceKey": key, **query},
            timeout=(10, 45),
            allow_redirects=False,
        )
    except requests.RequestException:
        raise ValueError("복지 API 연결 실패. 네트워크 상태를 확인하고 다시 실행하세요") from None
    if response.status_code != 200:
        raise ValueError(f"복지 API HTTP {response.status_code}: 수집을 중단했습니다")
    content = response.content
    if any(secret.encode() in content for secret in (key, quote(key, safe=""))):
        raise ValueError("응답에 인증값이 포함되어 저장을 중단했습니다")
    return content, parse_response(content)


def collect(case_dir: Path, key: str, districts: tuple[str, ...], *, session=None) -> dict:
    if not key:
        raise ValueError("로컬 .env에 DATA_GO_KR_API_KEY를 설정하세요")
    if session is None:
        with requests.Session() as client:
            return collect(case_dir, key, districts, session=client)

    started = datetime.now(UTC)
    target = case_dir / "data" / "raw" / "welfare" / started.strftime("%Y%m%dT%H%M%S%fZ")
    target.mkdir(parents=True)
    files = {}

    def save(name: str, content: bytes) -> None:
        (target / name).write_bytes(content)
        files[name] = hashlib.sha256(content).hexdigest()

    def save_json(name: str, value) -> None:
        save(name, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())

    records, seen = [], set()
    total, page = None, 1
    while total is None or len(records) < total:
        query = {"ctpvNm": "서울특별시", "numOfRows": PAGE_SIZE, "pageNo": page}
        content, root = request_xml(session, "LcgvWelfarelist", query, key)
        try:
            reported_total = int(root.findtext("totalCount", ""))
            reported_page = int(root.findtext("pageNo", ""))
            reported_size = int(root.findtext("numOfRows", ""))
        except ValueError:
            raise ValueError("복지 API 목록의 페이지 정보가 유효하지 않습니다") from None
        if total is None:
            total = reported_total
        if total <= 0 or reported_total != total:
            raise ValueError("목록이 비어 있거나 수집 중 전체 건수가 변경되었습니다")
        if reported_page != page or reported_size != PAGE_SIZE:
            raise ValueError("복지 API의 응답 페이지·페이지 크기가 요청과 다릅니다")
        batch = [xml_record(row) for row in root.findall("servList")]
        if len(batch) != min(PAGE_SIZE, total - len(records)):
            raise ValueError("복지 API 페이지에 누락된 행이 있습니다")
        for record in batch:
            service_id = record.get("servId", "")
            if not re.fullmatch(r"[A-Za-z0-9_-]+", service_id) or service_id in seen:
                raise ValueError("사업 식별자가 비어 있거나 중복되었습니다")
            if record.get("ctpvNm") != "서울특별시":
                raise ValueError("서울특별시 외 사업이 응답에 포함되었습니다")
            seen.add(service_id)
        save(f"list-{page:03}.xml", content)
        records.extend(batch)
        page += 1

    candidates = [record for record in records if is_candidate(record)]
    details = []
    for candidate in candidates:
        service_id = candidate["servId"]
        content, root = request_xml(session, "LcgvWelfaredetailed", {"servId": service_id}, key)
        detail = xml_record(root)
        if any(
            detail.get(field, "") != candidate.get(field, "")
            for field in ("servId", "ctpvNm", "sggNm")
        ):
            raise ValueError("목록과 상세의 사업 식별자·지역이 일치하지 않습니다")
        save(f"detail-{service_id}.xml", content)
        details.append(detail)
        time.sleep(0.1)

    save_json("services.json", records)
    save_json("candidates.json", candidates)
    save_json("details.json", details)
    all_counts = Counter(record.get("sggNm") or "서울시(구 미지정)" for record in records)
    candidate_counts = Counter(record.get("sggNm") or "서울시(구 미지정)" for record in candidates)
    manifest = {
        "source_url": SOURCE_URL,
        "license": "이용허락범위 제한 없음",
        "api_base_url": BASE_URL,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "list_query": {"ctpvNm": "서울특별시", "numOfRows": PAGE_SIZE},
        "list_pages": page - 1,
        "total_services": total,
        "candidate_services": len(candidates),
        "detail_services": len(details),
        "candidate_pattern": CANDIDATE_PATTERN,
        "candidate_fields": CANDIDATE_FIELDS,
        "district_counts": {
            district: {
                "all_services": all_counts[district],
                "candidates": candidate_counts[district],
            }
            for district in (*districts, "서울시(구 미지정)")
        },
        # sggNm에는 '서울특별시교육청'처럼 자치구가 아닌 기관명도 들어온다.
        "other_region_labels": {
            label: {"all_services": all_counts[label], "candidates": candidate_counts[label]}
            for label in sorted(set(all_counts) - set(districts) - {"서울시(구 미지정)"})
        },
        "files_sha256": files,
        "scope": "현행 사업 탐색용. 후보는 자체 현금지원 확정 목록이 아니며 미검색은 미지원을 뜻하지 않음.",
        "history_verified": False,
    }
    # 이 파일이 없는 디렉터리는 실패한 부분 수집이며 완성된 스냅샷으로 사용하지 않는다.
    (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return {"directory": str(target), **manifest}
