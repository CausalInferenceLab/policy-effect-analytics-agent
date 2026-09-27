"""공공데이터 어댑터 기본 클래스.

모든 어댑터는 `fetch(**query) -> pandas.DataFrame` 을 구현하고, 출처·라이선스를
`meta` 로 노출한다. 결과는 `save()` 로 case 의 data/ 아래에 CSV + 출처 JSON 으로 저장해
재현성을 확보한다 (원본 API 응답이 바뀌어도 분석은 스냅샷으로 재현).
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd


@dataclass
class SourceMeta:
    name: str
    provider: str
    license: str  # plan.py 의 License 값 (KOGL-1 등)
    url: str | None = None


class MissingAPIKey(RuntimeError):
    pass


def load_env(path: Path | None = None) -> None:
    """레포 루트의 .env 를 읽어 아직 없는 환경변수만 채운다 (python-dotenv 없이). .env 는 커밋하지 않는다."""
    path = path or Path(__file__).resolve().parents[2] / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        if k.strip() and v and not os.getenv(k.strip()):
            os.environ[k.strip()] = v


class BaseAdapter(ABC):
    meta: SourceMeta
    api_key_env: str | None = None  # 필요한 환경변수 이름 (예: KOSIS_API_KEY)

    def api_key(self) -> str:
        load_env()
        key = os.getenv(self.api_key_env or "", "")
        if not key:
            raise MissingAPIKey(
                f"환경변수 {self.api_key_env} 가 필요합니다 (.env 에 설정, 커밋 금지)."
            )
        return key

    @abstractmethod
    def fetch(self, **query) -> pd.DataFrame:
        """원천 데이터를 tidy DataFrame 으로 반환."""

    def save(self, df: pd.DataFrame, path: str | Path, query: dict | None = None) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False, encoding="utf-8")
        prov = {
            **asdict(self.meta),
            "query": query or {},
            "rows": len(df),
            "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        path.with_suffix(".source.json").write_text(
            json.dumps(prov, ensure_ascii=False, indent=2), "utf-8"
        )
        return path
