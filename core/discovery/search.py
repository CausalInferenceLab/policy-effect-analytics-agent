"""공공데이터포털(data.go.kr) 데이터셋 검색.

공개 검색 페이지 결과를 읽어 데이터셋 이름·유형·제공기관·링크만 뽑는다(데이터 자체는 받지 않음).
- 네트워크가 막혀 있거나 실패하면 빈 목록 + 사유를 돌려준다(추천은 카탈로그만으로 계속).
- 검색어당 1회, 요청 간 1초 간격. 대량 수집 용도로 쓰지 않는다.
- 공식 목록조회 API(키 필요)가 준비되면 이 모듈을 그 API 로 교체한다.
"""

from __future__ import annotations

import html
import re
import time
from dataclasses import asdict, dataclass

SEARCH_URL = "https://www.data.go.kr/tcs/dss/selectDataSetList.do"
UA = "policy-effect-analytics-agent/0.1 (+https://github.com/CausalInferenceLab/policy-effect-analytics-agent)"

_ITEM = re.compile(
    r'<div class="apply-result-item">(.*?)(?=<div class="apply-result-item">|$)', re.S
)
_LINK = re.compile(r'<a href="(/data/(\d+)/(openapi|fileData|standard)\.do)">(.*?)</a>', re.S)
_SUMMARY = re.compile(r'<span class="apply-result-summary">(.*?)</span>', re.S)
_PROVIDER = re.compile(r"<strong>제공기관</strong>(.*?)</li>", re.S)
_MODIFIED = re.compile(r"<strong>수정일</strong>\s*([0-9-]+)", re.S)

KIND_KO = {"openapi": "오픈API(키 필요)", "fileData": "파일", "standard": "표준데이터"}


@dataclass
class SearchHit:
    id: str
    title: str
    kind: str
    provider: str
    modified: str
    summary: str
    url: str

    def to_dict(self) -> dict:
        return asdict(self)


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip()


def parse_results(page: str, limit: int = 5) -> list[SearchHit]:
    hits: list[SearchHit] = []
    for block in _ITEM.findall(page):
        link = _LINK.search(block)
        if not link:
            continue
        path, did, kind, title = link.groups()
        prov, mod, summ = _PROVIDER.search(block), _MODIFIED.search(block), _SUMMARY.search(block)
        hits.append(
            SearchHit(
                id=did,
                title=_text(title),
                kind=KIND_KO.get(kind, kind),
                provider=_text(prov.group(1)) if prov else "",
                modified=mod.group(1) if mod else "",
                summary=_text(summ.group(1))[:160] if summ else "",
                url="https://www.data.go.kr" + path,
            )
        )
        if len(hits) >= limit:
            break
    return hits


def search_datago(
    terms: list[str], limit: int = 5, timeout: int = 10
) -> tuple[list[SearchHit], str]:
    """(검색 결과, 상태 메시지). 실패해도 예외를 던지지 않는다."""
    try:
        import requests
    except ImportError:
        return [], "requests 미설치"
    seen, out, errors = set(), [], []
    for i, term in enumerate(terms):
        if i:
            time.sleep(1)
        try:
            r = requests.get(
                SEARCH_URL, params={"keyword": term}, headers={"User-Agent": UA}, timeout=timeout
            )
            r.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"'{term}': {type(exc).__name__}")
            continue
        for h in parse_results(r.text, limit):
            if h.id not in seen:
                seen.add(h.id)
                out.append(h)
    msg = f"공공데이터포털 검색 {len(out)}건" + (f" (실패: {', '.join(errors)})" if errors else "")
    return out, msg
