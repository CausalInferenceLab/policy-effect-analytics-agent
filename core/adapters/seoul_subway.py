"""서울 열린데이터광장 — 지하철 호선별 역별 승하차 인원(OA-12914) 파일 수집기.

키가 필요 없습니다. 데이터셋 페이지의 월별 파일 목록(CARD_SUBWAY_MONTH_YYYYMM.csv)을 읽어
사이트의 '다운로드' 버튼과 같은 주소로 받습니다. 역 × 일 단위이며 서울 관할 노선과 함께
코레일 등 수도권 구간 역(경부선·분당선·경의선 등)도 들어 있습니다.

    from core.adapters.seoul_subway import SeoulSubwayDailyAdapter
    df = SeoulSubwayDailyAdapter().fetch(start="2024-01", end="2025-12", cache_dir="data/raw")
    # columns: date, line, station, on, off

- 이용 조건: 공공누리 제1유형(출처표시). 원자료·가공 파일은 레포에 커밋하지 않습니다(fetch.py 로 각자 받기).
- 공개 자료에는 권종(기후동행카드·K-패스·일반) 구분이 없습니다.
- 서버에 부담을 주지 않도록 월별 파일을 한 번씩만 받고 cache_dir 에 보관합니다.
"""

from __future__ import annotations

import io
import re
import time
from pathlib import Path

import pandas as pd

from .base import BaseAdapter, SourceMeta

PAGE = "https://data.seoul.go.kr/dataList/OA-12914/F/1/datasetView.do"
DOWNLOAD = "https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do?&useCache=false"
FILE_RE = re.compile(
    r"CARD_SUBWAY_MONTH_(\d{6})\.csv\" onclick=\"javascript:downloadFile\('(\d+)'\)"
)


def parse_file_list(html: str) -> dict[str, str]:
    """데이터셋 페이지 HTML → {YYYYMM: 파일 번호}."""
    return {ym: seq for ym, seq in FILE_RE.findall(html)}


def read_month(raw: bytes) -> pd.DataFrame:
    """월별 CSV(UTF-8 BOM 또는 CP949, 끝에 빈 열이 붙음) → date, line, station, on, off."""
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    d = pd.read_csv(io.StringIO(text), dtype=str, index_col=False).iloc[:, :5]
    d.columns = ["date", "line", "station", "on", "off"]
    d["date"] = pd.to_datetime(d["date"], format="%Y%m%d", errors="coerce")
    for c in ("on", "off"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    for c in ("line", "station"):
        d[c] = d[c].str.strip()
    return d.dropna(subset=["date"])


def months(start: str, end: str) -> list[str]:
    return [p.strftime("%Y%m") for p in pd.period_range(start, end, freq="M")]


class SeoulSubwayDailyAdapter(BaseAdapter):
    meta = SourceMeta(
        name="서울시 지하철호선별 역별 승하차 인원 정보 (OA-12914)",
        provider="서울특별시 (서울 열린데이터광장)",
        license="KOGL-1",
        url="https://data.seoul.go.kr/dataList/OA-12914/S/1/datasetView.do",
    )

    def __init__(self, session=None, pause: float = 1.0):
        if session is None:
            import requests

            session = requests.Session()
        self.s = session
        self.pause = pause

    def file_list(self) -> dict[str, str]:
        r = self.s.get(PAGE, timeout=30)
        r.raise_for_status()
        files = parse_file_list(r.text)
        if not files:
            raise RuntimeError(
                "파일 목록을 찾지 못했습니다 — 데이터셋 페이지 구조가 바뀌었는지 확인하세요"
            )
        return files

    def download(self, seq: str) -> bytes:
        r = self.s.post(
            DOWNLOAD,
            data={"infId": "OA-12914", "seqNo": "", "seq": seq, "infSeq": "3"},
            timeout=120,
        )
        r.raise_for_status()
        return r.content

    def fetch(
        self, start: str = "2024-01", end: str = "2025-12", cache_dir: str | Path | None = None
    ) -> pd.DataFrame:
        files, frames = None, []
        cache = Path(cache_dir) if cache_dir else None
        for ym in months(start, end):
            path = cache / f"subway_{ym}.csv" if cache else None
            if path and path.exists():
                raw = path.read_bytes()
            else:
                files = files or self.file_list()
                if ym not in files:
                    print(f"[seoul_subway] {ym} 파일이 아직 없습니다 — 건너뜀")
                    continue
                raw = self.download(files[ym])
                if path:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(raw)
                time.sleep(self.pause)
            frames.append(read_month(raw))
        if not frames:
            return pd.DataFrame(columns=["date", "line", "station", "on", "off"])
        return pd.concat(frames, ignore_index=True)
