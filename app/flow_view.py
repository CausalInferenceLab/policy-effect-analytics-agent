"""Flow view: normalize and render core.agent's flow_log.json (schema_version "1").

The adapter (`normalize_flow_log`) is the only place that knows the log layout, so a
schema change in core/agent/state.py stays a local fix here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
FLOW_LOG = "flow_log.json"

# Mirrors core.agent.state.STEPS (copied so the app renders logs even without core).
STEPS: list[tuple[str, str]] = [
    ("define_problem", "① 문제 정의"),
    ("collect", "② 데이터 수집"),
    ("structure_metrics", "③ 지표 구조화·품질 점검"),
    ("estimate", "④ 효과 추정"),
    ("guard", "⑤ 과잉해석 가드"),
    ("report", "⑥ 리포트·재현 기록"),
]
WEEKS = {  # program week each step is taught (README "Flow" table)
    "define_problem": "W3",
    "collect": "W2",
    "structure_metrics": "W3",
    "estimate": "W4–5",
    "guard": "W6",
    "report": "W7",
}
STATUS_BADGE = {
    "ok": ("OK", "green"),
    "warn": ("WARN", "orange"),
    "failed": ("FAILED", "red"),
    "needs_human": ("NEEDS HUMAN", "violet"),
    "blocked": ("BLOCKED", "red"),
    "running": ("RUNNING", "blue"),
    "skipped": ("SKIPPED", "gray"),
}
VERDICT_LABEL = {
    "identified": ("식별됨", "green"),
    "conditional": ("조건부", "orange"),
    "not_identified": ("식별 불가", "red"),
}
LLM_KEY_ENVS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_BASE_URL")


def cases_dir() -> Path:
    """Cases root; PEA_CASES_DIR overrides it (used by tests)."""
    return Path(os.environ.get("PEA_CASES_DIR") or ROOT / "cases")


def list_cases(root: Path | None = None) -> list[Path]:
    root = root or cases_dir()
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / "plan.yaml").exists())


def llm_available() -> bool:
    return any(os.environ.get(k) for k in LLM_KEY_ENVS)


def badge(status: str | None) -> str:
    text, color = STATUS_BADGE.get(status or "skipped", (str(status).upper(), "gray"))
    return f":{color}-background[{text}]"


def verdict_badge(verdict: str | None) -> str:
    if not verdict:
        return ":gray-background[판정 없음]"
    text, color = VERDICT_LABEL.get(verdict, (verdict, "gray"))
    return f":{color}-background[**{text}**]"


def normalize_flow_log(raw: dict[str, Any]) -> dict[str, Any]:
    """Return a log with exactly six steps in order; missing steps become 'skipped'."""
    by_name = {s.get("step"): s for s in raw.get("steps") or [] if isinstance(s, dict)}
    steps = []
    for i, (name, title) in enumerate(STEPS, start=1):
        s = dict(by_name.get(name) or {})
        s.setdefault("index", i)
        s.setdefault("step", name)
        s.setdefault("title", title)
        s.setdefault("status", "skipped")
        s.setdefault("message", "")
        s["artifacts"] = s.get("artifacts") or {}
        steps.append(s)
    return {
        "schema_version": str(raw.get("schema_version", "1")),
        "case_dir": raw.get("case_dir"),
        "question": raw.get("question"),
        "status": raw.get("status"),
        "verdict": raw.get("verdict"),
        "started_at": raw.get("started_at"),
        "ended_at": raw.get("ended_at"),
        "steps": steps,
        "quality": raw.get("quality") or [],
        "results": raw.get("results") or [],
        "guard": raw.get("guard") or {},
        "report_path": raw.get("report_path"),
    }


def load_flow_log(case: Path) -> dict[str, Any] | None:
    path = case / FLOW_LOG
    if not path.exists():
        return None
    return normalize_flow_log(json.loads(path.read_text(encoding="utf-8")))


def load_plan_dict(case: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load((case / "plan.yaml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def run_flow_for(case: Path, allow_uncommitted: bool, use_llm: bool) -> dict[str, Any]:
    """Run core.agent's flow and return the normalized log."""
    from core.agent import run_flow  # imported lazily: the app works without the agent

    state = run_flow(case, allow_uncommitted=allow_uncommitted, use_llm=use_llm)
    return normalize_flow_log(state.to_log() if hasattr(state, "to_log") else state)


def _resolve(case: Path, rel: str | None) -> Path | None:
    if not rel:
        return None
    p = Path(rel)
    if not p.is_absolute():
        p = case / p
    return p if p.exists() else None


# ---------- rendering ----------


def _plan_summary(st: Any, plan: dict[str, Any], step: dict[str, Any]) -> None:
    st.markdown(f"**질문** {plan.get('question', '-')}")
    t = plan.get("treatment") or {}
    c = plan.get("control") or {}
    est = plan.get("estimator") or {}
    st.markdown(
        f"- 처치: {t.get('definition', '-') if isinstance(t, dict) else t}\n"
        f"- 대조: {c.get('definition', '-') if isinstance(c, dict) else c}\n"
        f"- 추정: `{est.get('method', '-') if isinstance(est, dict) else est}`\n"
        f"- 사전 등록(커밋): {'예' if step['artifacts'].get('committed') else '아니오'}"
    )


def _collect(st: Any, plan: dict[str, Any], step: dict[str, Any]) -> None:
    a = step["artifacts"]
    rows = [
        {
            "데이터": s.get("name"),
            "제공": s.get("provider"),
            "라이선스": s.get("license"),
            "URL": s.get("url") or "",
        }
        for s in plan.get("data_sources") or []
        if isinstance(s, dict)
    ]
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
    if a.get("licenses"):
        st.caption("라이선스: " + ", ".join(map(str, a["licenses"])))
    if a.get("method"):
        st.caption(f"수집 방식: {a['method']}")


def _quality(st: Any, log: dict[str, Any], step: dict[str, Any]) -> None:
    if log["quality"]:
        rows = [
            {
                "상태": q.get("status"),
                "점검": q.get("check"),
                "값": str(q.get("value")),
                "메시지": q.get("message", ""),
            }
            for q in log["quality"]
        ]
        st.dataframe(rows, hide_index=True, width="stretch")
    a = step["artifacts"]
    if a:
        st.caption(" · ".join(f"{k}={v}" for k, v in a.items()))


def _fmt(x: Any) -> str:
    return f"{x:.3f}" if isinstance(x, int | float) else "-"


def _estimate(st: Any, log: dict[str, Any]) -> None:
    for r in log["results"]:
        st.markdown(
            f"**{r.get('method')}** · `{r.get('outcome')}` → {verdict_badge(r.get('verdict'))}"
        )
        cols = st.columns(3)
        cols[0].metric("추정치", _fmt(r.get("estimate")))
        cols[1].metric("95% CI", f"[{_fmt(r.get('ci_low'))}, {_fmt(r.get('ci_high'))}]")
        cols[2].metric("p", _fmt(r.get("p_value")))
        checks = r.get("assumptions_checked") or {}
        for name, chk in checks.items():
            if isinstance(chk, dict) and "passed" in chk:
                mark = "통과" if chk["passed"] else "실패"
                st.caption(f"{name}: {mark} (p={_fmt(chk.get('p_value'))})")
        for w in r.get("warnings") or []:
            st.warning(w)


def _guard(st: Any, log: dict[str, Any]) -> None:
    g = log["guard"]
    violations = g.get("violations") or []
    if violations:
        st.error(f"과잉해석 표현 {len(violations)}건 발견")
        for v in violations:
            st.markdown(f"- **{v.get('phrase')}** — {v.get('reason')}  \n  > {v.get('sentence')}")
    elif g:
        st.success("과잉해석 표현 없음")
    if g.get("narrative"):
        st.info(g["narrative"])
        st.caption(f"서술 출처: {g.get('narrative_source', '-')}")


def _report(st: Any, case: Path, log: dict[str, Any], step: dict[str, Any]) -> None:
    a = step["artifacts"]
    # report_path may be absolute on the machine that ran the flow; resolve by name instead.
    report_name = Path(log["report_path"]).name if log.get("report_path") else None
    report = _resolve(case, a.get("report")) or _resolve(case, report_name)
    for fig in a.get("figures") or []:
        p = _resolve(case, fig)
        if p:
            st.image(str(p), caption=p.name)
    if report:
        with st.expander("report.md 미리보기", expanded=False):
            st.markdown(report.read_text(encoding="utf-8"))


def render_flow(st: Any, case: Path, log: dict[str, Any], plan: dict[str, Any]) -> None:
    if plan.get("synthetic_data"):
        st.error("## ⚠ SYNTHETIC DATA\n합성 데이터입니다. 결과는 실제 정책 효과가 아닙니다.")

    top = st.columns(3)
    top[0].markdown(f"**전체 상태** {badge(log.get('status'))}")
    top[1].markdown(f"**판정** {verdict_badge(log.get('verdict'))}")
    top[2].caption(f"{log.get('started_at') or '-'} → {log.get('ended_at') or '-'}")

    for step in log["steps"]:
        name = step["step"]
        dur = step.get("duration_s")
        header = f"{step['title']} ({WEEKS.get(name, '')})  ·  {STATUS_BADGE.get(step['status'], (step['status'],))[0]}"
        expanded = step["status"] not in {"ok", "skipped"} or name in {"estimate", "guard"}
        with st.expander(header, expanded=expanded):
            st.markdown(
                f"{badge(step['status'])}  {step.get('message', '')}"
                + (f"  \n:gray[{dur:.2f}s]" if isinstance(dur, int | float) else "")
            )
            if step["status"] == "skipped":
                continue
            if name == "define_problem":
                _plan_summary(st, plan, step)
            elif name == "collect":
                _collect(st, plan, step)
            elif name == "structure_metrics":
                _quality(st, log, step)
            elif name == "estimate":
                _estimate(st, log)
            elif name == "guard":
                _guard(st, log)
            elif name == "report":
                _report(st, case, log, step)
