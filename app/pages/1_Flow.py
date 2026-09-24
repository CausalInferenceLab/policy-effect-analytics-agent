"""Flow page: run the 6-step agent flow on a case, or render its existing flow_log.json."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
for p in (APP_DIR, APP_DIR.parent):  # app/ for flow_view, repo root for core
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import flow_view as fv  # noqa: E402

st.set_page_config(page_title="Flow · 정책 효과 분석", layout="wide")
st.title("Flow — 6단계 분석 흐름")
st.caption("문제 정의 → 수집 → 지표 구조화 → 추정 → 과잉해석 가드 → 리포트")

cases = fv.list_cases()
if not cases:
    st.info("plan.yaml이 있는 케이스가 없습니다. `cases/_template`을 복사해 시작하세요.")
    st.stop()

case = st.sidebar.selectbox("케이스", cases, format_func=lambda p: p.name)
allow_uncommitted = st.sidebar.checkbox(
    "allow uncommitted plan (demo)",
    value=False,
    help="사전 등록(plan.yaml 커밋) 게이트를 건너뜁니다. 데모 전용.",
)
llm_ok = fv.llm_available()
use_llm = st.sidebar.toggle(
    "LLM 서술 사용",
    value=False,
    disabled=not llm_ok,
    help=None if llm_ok else "LLM 키 환경변수(OPENAI_API_KEY 등)가 없어 비활성화됨",
)
run = st.sidebar.button("Run flow", type="primary")

plan = fv.load_plan_dict(case)
log = None
if run:
    with st.spinner("흐름 실행 중..."):
        try:
            log = fv.run_flow_for(case, allow_uncommitted, use_llm)
        except ImportError:
            st.error("core.agent를 불러올 수 없습니다. `make install` 후 다시 시도하세요.")
        except Exception as exc:  # show, don't crash the page
            st.exception(exc)
else:
    log = fv.load_flow_log(case)

if log is None:
    st.info(f"`{case.name}/flow_log.json`이 없습니다. 사이드바에서 **Run flow**를 누르세요.")
    if plan.get("synthetic_data"):
        st.warning("이 케이스는 합성 데이터(SYNTHETIC)입니다.")
else:
    if not run:
        st.caption(f"저장된 `{case.name}/flow_log.json`을 표시합니다 (재실행 안 함).")
    fv.render_flow(st, case, log, plan)
