"""법제처 API로 주제별 조례 스냅샷을 갱신한다 → catalog/snapshots/law_<topic>.csv

GitHub Actions(pages.yml)에서 LAW_OC 시크릿이 있을 때만 실행된다. 로컬: LAW_OC=... python scripts/refresh_law_snapshots.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.adapters.base import MissingAPIKey  # noqa: E402
from core.adapters.law import LawOrdinanceAdapter  # noqa: E402
from core.discovery import load_topics  # noqa: E402


def main() -> int:
    out_dir = ROOT / "catalog" / "snapshots"
    ad = LawOrdinanceAdapter()
    for t in load_topics():
        if t.collect.method != "law_ordinance":
            continue
        try:
            df = ad.fetch(t.collect.query)
        except MissingAPIKey as e:
            print(f"건너뜀: {e}")
            return 0
        path = ad.save(df, out_dir / f"law_{t.id}.csv", {"queries": t.collect.query})
        print(f"{t.id}: 조례 {len(df)}건 → {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
