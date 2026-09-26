"""에이전트 툴 (JSON 입출력). LangGraph/MCP tool 로 그대로 래핑할 수 있는 얇은 함수들."""

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
