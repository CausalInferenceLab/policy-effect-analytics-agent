"""에이전트 흐름 상태(FlowState)와 flow_log.json 스키마.

flow_log.json (schema_version "1") — Streamlit Flow 페이지·CI 가 읽는 계약:
{
  "schema_version": "1",
  "case_dir": "cases/_example_night_clinic",
  "question": str | null,
  "status": "ok" | "warn" | "failed" | "needs_human" | "blocked" | "running",
  "verdict": "identified" | "conditional" | "not_identified" | null,   # 가장 보수적인 판정
  "started_at": ISO8601, "ended_at": ISO8601 | null,
  "steps": [                                   # 실행된 단계만 순서대로 (중단 시 이후 단계 없음)
    {"index": 1, "step": "define_problem", "title": "① 문제 정의",
     "status": "ok"|"warn"|"failed"|"needs_human"|"blocked",
     "started_at": ISO8601, "ended_at": ISO8601, "duration_s": float,
     "message": str (한국어), "artifacts": {name: 경로(케이스 기준) 또는 값}}
  ],
  "quality": [{"check": str, "value": any, "status": "ok"|"warn"|"failed", "message": str}],
  "results": [EffectResult.to_dict()],        # 대용량 배열(extra.fitted 등)은 제외
  "guard": {"verdict": str, "narrative_source": "template"|"llm", "passed": bool,
            "violations": [{"phrase": str, "sentence": str, "reason": str}], "narrative": str},
  "report_path": str | null
}
run_flow() 는 FlowState 를 반환하고, FlowState.to_log() 가 위 dict 를 만든다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..estimators.result import EffectResult
from ..schema.plan import Plan

Status = Literal["ok", "warn", "failed", "needs_human", "blocked", "running"]
CONTINUE = {"ok", "warn"}  # 이 상태일 때만 다음 단계로 진행
STEPS = [
    ("define_problem", "① 문제 정의"),
    ("collect", "② 데이터 수집"),
    ("structure_metrics", "③ 지표 구조화·품질 점검"),
    ("estimate", "④ 효과 추정"),
    ("guard", "⑤ 과잉해석 가드"),
    ("report", "⑥ 리포트·재현 기록"),
]
_ORDER = ["ok", "warn", "needs_human", "blocked", "failed"]


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class StepLog(BaseModel):
    index: int
    step: str
    title: str
    status: Status = "running"
    started_at: str = Field(default_factory=now)
    ended_at: str | None = None
    duration_s: float | None = None
    message: str = ""
    artifacts: dict[str, Any] = {}


class FlowState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    case_dir: Path
    question: str | None = None
    allow_uncommitted: bool = False
    use_llm: bool = False
    started_at: str = Field(default_factory=now)
    plan: Plan | None = None
    data_path: Path | None = None
    quality: list[dict[str, Any]] = []
    results: list[EffectResult] = []
    guard: dict[str, Any] = {}
    report_path: Path | None = None
    steps: list[StepLog] = []

    @property
    def last_status(self) -> str:
        return self.steps[-1].status if self.steps else "running"

    @property
    def can_continue(self) -> bool:
        return not self.steps or self.last_status in CONTINUE

    @property
    def status(self) -> str:
        if not self.steps:
            return "running"
        worst = max((s.status for s in self.steps), key=_ORDER.index)
        done = len(self.steps) == len(STEPS) or worst not in CONTINUE
        return worst if done else "running"

    @property
    def verdict(self) -> str | None:
        v = [r.verdict for r in self.results]
        order = ["identified", "conditional", "not_identified"]
        return max(v, key=order.index) if v else None

    def to_log(self) -> dict:
        def _res(r: EffectResult) -> dict:
            d = r.to_dict()
            d["extra"] = {
                k: v for k, v in d["extra"].items() if k not in {"fitted", "counterfactual"}
            }
            return d

        def _rel(p: Path | None) -> str | None:
            # 공개 레포에 실행자의 로컬 경로가 남지 않도록 케이스 폴더 기준 상대경로만 기록
            if p is None:
                return None
            p = Path(p)
            try:
                return str(p.resolve().relative_to(Path(self.case_dir).resolve()))
            except ValueError:
                return p.name

        return {
            "schema_version": "1",
            "case_dir": f"cases/{Path(self.case_dir).name}",
            "question": self.question or (self.plan.question if self.plan else None),
            "status": self.status,
            "verdict": self.verdict,
            "started_at": self.started_at,
            "ended_at": self.steps[-1].ended_at if self.steps else None,
            "steps": [s.model_dump() for s in self.steps],
            "quality": self.quality,
            "results": [_res(r) for r in self.results],
            "guard": self.guard,
            "report_path": _rel(self.report_path),
        }
