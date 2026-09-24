"""흐름 실행기: LangGraph StateGraph(있으면) 또는 순수 Python 순차 실행 — 의미는 동일.

    from core.agent import run_flow
    state = run_flow("cases/_example_night_clinic", allow_uncommitted=True)
    state.to_log()   # flow_log.json 과 같은 dict

두 실행기 모두 '마지막 단계가 ok/warn 일 때만 다음 단계로' 규칙을 따른다
(failed / needs_human / blocked 이면 즉시 종료).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict

from .nodes import NODES
from .state import FlowState


class GraphState(TypedDict):
    flow: FlowState  # LangGraph 채널은 하나만 쓰고, 그 안에 FlowState 전체를 담는다


def _init(case_dir, question, allow_uncommitted, use_llm) -> FlowState:
    return FlowState(
        case_dir=Path(case_dir).resolve(),
        question=question,
        allow_uncommitted=allow_uncommitted,
        use_llm=use_llm,
    )


def write_flow_log(s: FlowState) -> Path:
    path = s.case_dir / "flow_log.json"
    if s.case_dir.exists():
        path.write_text(json.dumps(s.to_log(), ensure_ascii=False, indent=2, default=str), "utf-8")
    return path


def langgraph_available() -> bool:
    try:
        import langgraph.graph  # noqa: F401
    except ImportError:
        return False
    return True


def build_graph():
    """LangGraph StateGraph: ①→②→…→⑥, 각 단계 뒤 조건부 엣지로 중단 여부 결정."""
    from langgraph.graph import END, START, StateGraph

    g = StateGraph(GraphState)
    for fn in NODES:
        g.add_node(fn.__name__, lambda d, fn=fn: {"flow": fn(d["flow"])})
    g.add_edge(START, NODES[0].__name__)
    names = [fn.__name__ for fn in NODES]
    for a, b in zip(names, names[1:], strict=False):
        g.add_conditional_edges(a, lambda d, b=b: b if d["flow"].can_continue else END, [b, END])
    g.add_edge(NODES[-1].__name__, END)
    return g.compile()


def run_flow(
    case_dir,
    question: str | None = None,
    allow_uncommitted: bool = False,
    use_llm: bool = False,
    engine: str = "python",
    write_log: bool = True,
) -> FlowState:
    """engine: "python"(기본, 의존성 없음) | "langgraph" | "auto"(설치돼 있으면 langgraph)."""
    s = _init(case_dir, question, allow_uncommitted, use_llm)
    if engine == "auto":
        engine = "langgraph" if langgraph_available() else "python"
    if engine == "langgraph":
        s = build_graph().invoke({"flow": s})["flow"]
    else:
        for node in NODES:
            s = node(s)
            if not s.can_continue:
                break
    if write_log:
        write_flow_log(s)
    return s
