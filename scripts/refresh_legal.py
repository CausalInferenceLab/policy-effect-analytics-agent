"""주제별 법령·정책 온톨로지 스냅샷을 만든다 → catalog/snapshots/legal_<주제>.csv

topics.yaml 의 legal(근거 법률·행정규칙 검색어)에서 출발해 연혁·체계도·지정/해제 이력을 모두 모읍니다.
메타데이터(이름·날짜·종류)만 저장하고, 링크는 OC 없는 공개 주소로 바꿉니다. 출처: 법제처 국가법령정보센터.

    LAW_OC=... python scripts/refresh_legal.py              # 전체 주제
    LAW_OC=... python scripts/refresh_legal.py housing-regulation
GitHub Actions(pages.yml)에서는 LAW_OC 시크릿이 있을 때 매일 실행됩니다.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.adapters.base import MissingAPIKey  # noqa: E402
from core.adapters.legal import ATTRIBUTION, LawAPIError, LawClient, collect_topic  # noqa: E402
from core.discovery import load_topics  # noqa: E402

OUT = ROOT / "catalog" / "snapshots"


def main(argv: list[str]) -> int:
    try:
        c = LawClient()
    except MissingAPIKey as e:
        print(f"건너뜀: {e}")
        return 0
    only = set(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    failed = 0
    for t in load_topics():
        if only and t.id not in only:
            continue
        if not t.legal or not (t.legal.laws or t.legal.admin_rules):
            continue
        try:
            df = collect_topic(c, t.legal.laws, t.legal.admin_rules)
        except LawAPIError as e:
            print(f"{t.id}: 실패 — {e}")
            failed += 1
            continue
        path = OUT / f"legal_{t.id}.csv"
        df.to_csv(path, index=False, encoding="utf-8")
        meta = {
            "topic": t.id,
            "laws": t.legal.laws,
            "admin_rules": t.legal.admin_rules,
            "rows": len(df),
            "by_group": df["group"].value_counts().to_dict(),
            "fetched": date.today().isoformat(),
            "attribution": ATTRIBUTION,
        }
        path.with_suffix(".source.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"{t.id}: {len(df)}건 {meta['by_group']} → {path.relative_to(ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
