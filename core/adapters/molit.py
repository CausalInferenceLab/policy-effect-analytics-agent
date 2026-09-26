"""국토교통부 아파트 매매 실거래가 상세 자료 (data.go.kr 15126468) 어댑터.

- 인증키: 공공데이터포털에서 활용신청(자동승인) 후 DATA_GO_KR_API_KEY 에 넣는다.
- 조회 단위: 시군구코드(법정동코드 앞 5자리) × 계약년월(YYYYMM). 1회 최대 1,000건 → 페이지 순회.
- 해제(취소)된 거래(cdealType == "O")는 제외한다.
- ⚠️ 2026-09 작성 시점에 실제 호출로 검증하지 못했다(작성 환경에서 apis.data.go.kr 접속 불가).
  키를 넣고 처음 돌릴 때 응답 필드명을 확인하고, 다르면 FIELD_MAP 만 고친다.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET

import pandas as pd

from .base import BaseAdapter, SourceMeta

ENDPOINT = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"

# 서울 25개 자치구 시군구코드
SEOUL_GU = {
    "11110": "종로구", "11140": "중구", "11170": "용산구", "11200": "성동구", "11215": "광진구",
    "11230": "동대문구", "11260": "중랑구", "11290": "성북구", "11305": "강북구", "11320": "도봉구",
    "11350": "노원구", "11380": "은평구", "11410": "서대문구", "11440": "마포구", "11470": "양천구",
    "11500": "강서구", "11530": "구로구", "11545": "금천구", "11560": "영등포구", "11590": "동작구",
    "11620": "관악구", "11650": "서초구", "11680": "강남구", "11710": "송파구", "11740": "강동구",
}  # fmt: skip

FIELD_MAP = {  # API 응답 태그 → 컬럼
    "sggCd": "gu_code",
    "dealYear": "year",
    "dealMonth": "month",
    "dealAmount": "price_10k_won",
    "excluUseAr": "area_m2",
    "cdealType": "cancelled",
}


def months(start: str, end: str) -> list[str]:
    """'2024-01', '2025-09' → ['202401', ..., '202509']"""
    return [p.strftime("%Y%m") for p in pd.period_range(start, end, freq="M")]


class MolitAptTradeAdapter(BaseAdapter):
    meta = SourceMeta(
        name="국토교통부_아파트 매매 실거래가 상세 자료",
        provider="국토교통부 (공공데이터포털 15126468)",
        license="KOGL-1",
        url="https://www.data.go.kr/data/15126468/openapi.do",
    )
    api_key_env = "DATA_GO_KR_API_KEY"

    def _page(self, lawd: str, ym: str, page: int) -> tuple[list[dict], int]:
        import requests

        r = requests.get(
            ENDPOINT,
            params={
                "serviceKey": self.api_key(),
                "LAWD_CD": lawd,
                "DEAL_YMD": ym,
                "pageNo": page,
                "numOfRows": 1000,
            },
            timeout=30,
        )
        r.raise_for_status()
        root = ET.fromstring(r.content)
        code = root.findtext(".//resultCode")
        if code not in (None, "00", "000"):
            raise RuntimeError(f"API 오류 {code}: {root.findtext('.//resultMsg')}")
        rows = [
            {col: (it.findtext(tag) or "").strip() for tag, col in FIELD_MAP.items()}
            for it in root.iter("item")
        ]
        return rows, int(root.findtext(".//totalCount") or 0)

    def fetch(self, start: str, end: str, gu_codes: list[str] | None = None) -> pd.DataFrame:
        """거래 단위 원자료 (gu_code, year, month, price_10k_won, area_m2)."""
        rows: list[dict] = []
        for lawd in gu_codes or list(SEOUL_GU):
            for ym in months(start, end):
                page, total = 1, None
                while total is None or (page - 1) * 1000 < total:
                    got, total = self._page(lawd, ym, page)
                    rows += [{**g, "gu_code": g["gu_code"] or lawd} for g in got]
                    page += 1
                    time.sleep(0.1)
        df = pd.DataFrame(rows, columns=list(FIELD_MAP.values()))
        df = df[df["cancelled"].ne("O")].drop(columns="cancelled")
        df["price_10k_won"] = pd.to_numeric(df["price_10k_won"].str.replace(",", ""))
        df["area_m2"] = pd.to_numeric(df["area_m2"])
        df[["year", "month"]] = df[["year", "month"]].astype(int)
        return df


def to_gu_month_panel(trades: pd.DataFrame, start: str) -> pd.DataFrame:
    """거래 단위 → 자치구 × 월 패널 (거래건수, ㎡당 가격 중위값)."""
    t = trades.assign(ym=trades["year"].astype(str) + trades["month"].astype(str).str.zfill(2))
    t["price_per_m2"] = t["price_10k_won"] * 10_000 / t["area_m2"]
    g = t.groupby(["gu_code", "ym"]).agg(
        trades=("price_per_m2", "size"), price_m2_median=("price_per_m2", "median")
    )
    return g.reset_index().assign(month_idx=lambda d: month_index(d["ym"], start))


def month_index(ym: pd.Series, start: str) -> pd.Series:
    """'202401' → 0, '202402' → 1 … (core 는 정수 시간축을 요구)"""
    p0 = pd.Period(start, freq="M")
    return ym.map(lambda s: (pd.Period(f"{s[:4]}-{s[4:]}", freq="M") - p0).n).astype(int)
