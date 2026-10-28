"""설정·실자료 실행 관문·원본 메타데이터의 준비 상태를 출력한다."""

from __future__ import annotations

import argparse
import json
import sys

from gangnam.common import (
    CASE,
    holiday_dates,
    read_yaml,
    require_data_contract,
    require_registration,
)
from gangnam.topis import check_corridors, check_metadata
from gangnam.windows import validate_config


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--structural-only", action="store_true", help="미해결 근거를 보고하되 구조 검증 성공 시 종료 코드 0")
    args = p.parse_args()
    sys.path.insert(0, str(CASE.parents[1]))
    from core.schema.plan import load_plan
    plan = load_plan(CASE / "plan.yaml")
    cfg = read_yaml("corridors.yaml")
    if plan.case_id != CASE.name:
        raise ValueError("케이스 이름 불일치")
    validate_config(read_yaml("ml_config.yaml"))
    holiday_dates()
    blockers = []
    for test in (lambda: require_data_contract(read_yaml("data_contract.yaml")), require_registration):
        try:
            test()
        except ValueError as e:
            blockers.append(str(e))
    if any(v["status"] != "verified" for v in cfg["corridors"].values()):
        blockers.append("처치·비교 도로의 역사적 노출 근거 검증 미완료")
    paths = sorted((CASE / "data/metadata").glob("*.json"))
    summaries = [json.loads(p.read_text(encoding="utf-8")) for p in paths]
    if summaries:
        try:
            check_metadata(summaries)
            check_corridors(summaries, cfg)
        except ValueError as e:
            blockers.append(str(e))
    print(json.dumps({"schema": "passed", "metadata_months": len(paths), "real_analysis_ready": not blockers,
                      "blockers": blockers}, ensure_ascii=False, indent=2))
    return 0 if args.structural_only or not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
