"""에이전트 툴 인터페이스 (스텁). W4~5 에 Develop 이 LangGraph tool 로 래핑.

규약: 각 툴은 JSON 직렬화 가능한 입력/출력만 사용한다.
  - validate_plan(path) -> {"ok": bool, "errors": [...]}
  - run_estimate(plan_path, data_path) -> EffectResult.to_dict()
LLM 은 plan.yaml 작성까지만 하고, 수치 계산은 반드시 core.estimators 를 호출한다.
"""

from __future__ import annotations

import pandas as pd
from pydantic import ValidationError

from ..schema.plan import load_plan


def validate_plan(path: str) -> dict:
    try:
        load_plan(path)
        return {"ok": True, "errors": []}
    except ValidationError as e:
        return {
            "ok": False,
            "errors": [f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()],
        }


def run_estimate(plan_path: str, data_path: str) -> list[dict]:
    from ..pipeline import run_plan  # 지연 import

    return [r.to_dict() for r in run_plan(load_plan(plan_path), pd.read_csv(data_path))]
