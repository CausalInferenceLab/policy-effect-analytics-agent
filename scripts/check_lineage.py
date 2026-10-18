"""데이터 계보(catalog/lineage/*.yaml) 검사 — 트랙 A 산출물이 다른 카탈로그와 제대로 이어지는지 확인합니다.

    python scripts/check_lineage.py          # 또는 make lineage
오류(없는 이슈·데이터셋 참조, 순서 틀림)가 있으면 실패하고, 경고(카탈로그에 없는 새 데이터 등)는 안내만 합니다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.discovery.lineage import LINEAGE_DIR, Lineage, validate  # noqa: E402


def main() -> int:
    failed = 0
    files = sorted(p for p in LINEAGE_DIR.glob("*.yaml") if not p.name.startswith("_"))
    for f in files:
        try:
            lin = Lineage.model_validate(yaml.safe_load(f.read_text(encoding="utf-8")))
        except (ValidationError, yaml.YAMLError) as e:
            print(f"✗ {f.name}: 형식 오류\n{e}")
            failed += 1
            continue
        errors, warns = validate(lin, f.stem)
        mark = "✗" if errors else "✓"
        print(f"{mark} {f.name}: 단계 {len(lin.steps)}개 ({lin.title})")
        for m in errors:
            print(f"   오류: {m}")
        for m in warns:
            print(f"   참고: {m}")
        failed += bool(errors)
    print(f"\n계보 {len(files)}개, 실패 {failed}개")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
