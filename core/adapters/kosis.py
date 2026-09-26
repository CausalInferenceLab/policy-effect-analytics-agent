"""KOSIS(국가통계포털) OpenAPI 어댑터.

문서: https://kosis.kr/openapi/  (통계자료 > 통계표 선택 방식 `statisticsParameterData.do`)
필요: 환경변수 KOSIS_API_KEY (KOSIS 공유서비스에서 무료 발급)
라이선스: KOSIS 제공 통계는 대부분 공공누리 제1유형 — 통계표별로 반드시 확인하세요.

예:
    KosisAdapter().fetch(orgId="101", tblId="DT_1B040A3", itmId="T20",
                         objL1="ALL", prdSe="Y", startPrdDe="2015", endPrdDe="2023")
"""

from __future__ import annotations

import pandas as pd
import requests

from .base import BaseAdapter, SourceMeta

URL = "https://kosis.kr/openapi/Param/statisticsParameterData.do"


class KosisAdapter(BaseAdapter):
    api_key_env = "KOSIS_API_KEY"
    meta = SourceMeta(name="KOSIS 통계표", provider="통계청 KOSIS", license="KOGL-1", url=URL)

    def fetch(
        self,
        *,
        orgId: str,
        tblId: str,
        itmId: str = "ALL",
        objL1: str = "ALL",
        prdSe: str = "Y",
        startPrdDe: str | None = None,
        endPrdDe: str | None = None,
        timeout: int = 30,
        **extra,
    ) -> pd.DataFrame:
        params = {
            "method": "getList",
            "apiKey": self.api_key(),
            "format": "json",
            "jsonVD": "Y",
            "orgId": orgId,
            "tblId": tblId,
            "itmId": itmId,
            "objL1": objL1,
            "prdSe": prdSe,
            "startPrdDe": startPrdDe,
            "endPrdDe": endPrdDe,
            **extra,
        }
        r = requests.get(
            URL, params={k: v for k, v in params.items() if v is not None}, timeout=timeout
        )
        r.raise_for_status()
        data = r.json()
        if (
            isinstance(data, dict) and "err" in data
        ):  # KOSIS 는 오류도 200 + {"err": .., "errMsg": ..}
            raise RuntimeError(f"KOSIS 오류 {data.get('err')}: {data.get('errMsg')}")
        return self.tidy(pd.DataFrame(data))

    @staticmethod
    def tidy(raw: pd.DataFrame) -> pd.DataFrame:
        """KOSIS 응답 → (region_code, region, item, period, value) 롱포맷."""
        cols = {
            "C1": "region_code",
            "C1_NM": "region",
            "ITM_NM": "item",
            "PRD_DE": "period",
            "DT": "value",
        }
        out = raw.rename(columns=cols)
        out = out[[c for c in cols.values() if c in out.columns]].copy()
        out["value"] = pd.to_numeric(out["value"], errors="coerce")  # '-', 'X'(비밀보호) → NaN
        return out
