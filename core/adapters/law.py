"""법제처 국가법령정보 공동활용 API — 자치법규(조례) 검색 어댑터.

- 인증: open.law.go.kr 에서 신청(무료, 즉시 승인)한 OC 값을 LAW_OC 환경변수에 넣는다.
- 용도: 주제(예: 지역사랑상품권)의 조례를 지자체별로 모아 '어느 지역이 언제부터'를 자동으로 만든다
  (출발 키트 05 관문 1).
- 주의: 검색 결과의 날짜는 **현행(최신 개정) 기준**이다. 처음 제정된 날은 연혁 조회로 확인해야 한다.
  그래서 이 어댑터가 만든 표는 '후보 처치표'이고, 제정일 확정은 사람이 검증한다.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET

import pandas as pd

from .base import BaseAdapter, SourceMeta

SEARCH_URL = "https://www.law.go.kr/DRF/lawSearch.do"
KEEP = [
    "자치법규ID",
    "자치법규명",
    "지자체기관명",
    "제개정구분명",
    "공포일자",
    "시행일자",
    "자치법규종류",
]


def parse_ordinance_xml(xml: bytes | str) -> tuple[list[dict], int]:
    root = ET.fromstring(xml)
    total = int(root.findtext("totalCnt") or 0)
    rows = [{c.tag: (c.text or "").strip() for c in item} for item in root.iter("law")]
    return rows, total


class LawOrdinanceAdapter(BaseAdapter):
    meta = SourceMeta(
        name="법제처 자치법규 검색",
        provider="법제처 국가법령정보 공동활용",
        license="other",  # 법령·자치법규 본문은 저작권 보호 대상이 아님(저작권법 제7조). 메타데이터만 사용
        url="https://open.law.go.kr",
    )
    api_key_env = "LAW_OC"

    def fetch(self, queries: list[str], per_page: int = 100, max_pages: int = 20) -> pd.DataFrame:
        import requests

        rows: list[dict] = []
        for q in queries:
            page, total = 1, None
            while page <= max_pages and (total is None or (page - 1) * per_page < total):
                r = requests.get(
                    SEARCH_URL,
                    params={
                        "OC": self.api_key(),
                        "target": "ordin",
                        "type": "XML",
                        "query": q,
                        "display": per_page,
                        "page": page,
                    },
                    timeout=30,
                )
                r.raise_for_status()
                got, total = parse_ordinance_xml(r.content)
                rows += [{**g, "query": q} for g in got]
                page += 1
                time.sleep(0.3)
        return tidy(pd.DataFrame(rows))


def tidy(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=[*KEEP, "query", "year"])
    df = df[[c for c in [*KEEP, "query"] if c in df.columns]].drop_duplicates("자치법규ID")
    date = pd.to_datetime(df["시행일자"], format="%Y%m%d", errors="coerce")
    return df.assign(year=date.dt.year).sort_values("시행일자").reset_index(drop=True)
