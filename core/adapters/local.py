"""로컬/다운로드 파일 어댑터 (CSV·XLSX).

공공데이터포털의 '파일데이터'는 대부분 API 없이 CSV 로 내려받는다. 이 어댑터로 읽으면
한글 인코딩(cp949/euc-kr) 자동 판별 + 출처 메타 기록을 통일할 수 있다.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .base import BaseAdapter, SourceMeta


class LocalFileAdapter(BaseAdapter):
    def __init__(self, path: str | Path, meta: SourceMeta):
        self.path, self.meta = Path(path), meta

    def fetch(self, **read_kwargs) -> pd.DataFrame:
        if self.path.suffix.lower() in {".xlsx", ".xls"}:
            return pd.read_excel(self.path, **read_kwargs)
        for enc in ("utf-8-sig", "cp949"):  # 공공데이터 CSV 는 cp949 가 흔함
            try:
                return pd.read_csv(self.path, encoding=enc, **read_kwargs)
            except UnicodeDecodeError:
                continue
        raise UnicodeDecodeError("utf-8/cp949", b"", 0, 1, f"인코딩 판별 실패: {self.path}")
