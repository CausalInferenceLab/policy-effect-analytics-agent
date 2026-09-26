"""CLI: python -m core.agent <case_dir> [--allow-uncommitted] [--llm] [--question "..."]"""

from __future__ import annotations

import argparse
import sys

from .graph import run_flow

ICON = {"ok": "OK", "warn": "WARN", "failed": "FAIL", "needs_human": "HUMAN", "blocked": "BLOCK"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m core.agent", description="6단계 정책효과 분석 흐름 실행"
    )
    ap.add_argument("case_dir")
    ap.add_argument("--question", help="plan.yaml 이 없을 때 초안 작성에 쓸 분석 질문")
    ap.add_argument(
        "--allow-uncommitted", action="store_true", help="사전 등록 게이트 우회 (데모 전용)"
    )
    ap.add_argument(
        "--llm", action="store_true", help="LLM 사용 (OPENAI_BASE_URL/OPENAI_API_KEY/LLM_MODEL)"
    )
    ap.add_argument("--engine", choices=["auto", "python", "langgraph"], default="auto")
    a = ap.parse_args(argv)
    s = run_flow(a.case_dir, a.question, a.allow_uncommitted, a.llm, engine=a.engine)
    for st in s.steps:
        print(
            f"{st.title:<18} {ICON.get(st.status, st.status):<5} {st.duration_s or 0:>6.2f}s  {st.message}"
        )
    print(f"\n상태={s.status}  판정={s.verdict}  로그={s.case_dir / 'flow_log.json'}")
    return {"ok": 0, "warn": 0, "failed": 1}.get(s.status, 2)


if __name__ == "__main__":
    sys.exit(main())
