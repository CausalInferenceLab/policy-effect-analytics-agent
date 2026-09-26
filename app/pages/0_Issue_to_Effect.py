"""이슈 → 데이터 → 효과: 소셜 반응 한 건을 정책·데이터셋·효과 분석까지 잇는 화면."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
for p in (APP_DIR, APP_DIR.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import flow_view as fv  # noqa: E402

from core.discovery import discover  # noqa: E402

EXAMPLES = {  # 직접 작성한 예시 문장 (실제 게시글 인용 아님)
    "부동산": "토허제 강남3구·용산까지 확대하고 나서 집값 진짜 잡힌 거 맞음? 옆 동네만 올랐다는 얘기도 있던데",
    "교통안전": "민식이법 시행되고 스쿨존 어린이 사고가 줄었다는 게 사실인가요?",
    "속도제한": "5030 속도 줄이고 나서 보행자 교통사고 줄었다는데 체감이 안 됨",
    "대기질": "사대문 안 5등급 차 운행제한하고 도심 공기 좋아졌나?",
}

st.set_page_config(page_title="이슈 → 데이터 → 효과", layout="wide")
st.title("이슈 → 데이터 → 효과")
st.caption(
    "소셜 반응(뉴스 제목·SNS 글)에서 정책을 찾고 → 공공데이터를 추천하고 → 효과를 분석합니다."
)

with st.sidebar:
    st.markdown("**예시 입력** (직접 작성한 문장)")
    for label, text in EXAMPLES.items():
        if st.button(label, use_container_width=True):
            st.session_state["issue"] = text
    live = st.checkbox(
        "공공데이터포털 실시간 검색",
        value=False,
        help="data.go.kr 검색 결과를 함께 보여줍니다(네트워크 필요).",
    )
    use_llm = st.toggle("LLM 보조", value=False, disabled=not fv.llm_available())

text = st.text_area(
    "① 소셜 반응", key="issue", height=90, placeholder="예: 토허제 확대하고 강남 집값 잡혔나요?"
)
if not text.strip():
    st.info("왼쪽 예시를 누르거나 뉴스 제목·SNS 글을 붙여 넣으세요.")
    st.stop()

res = discover(text, live_search=live, use_llm=use_llm)
if not res.matches:
    st.warning(res.next_step)
    st.stop()

# ② 정책 식별 -------------------------------------------------------------------------
st.subheader("② 정책 식별")
idx = st.radio(
    "후보",
    range(len(res.matches)),
    format_func=lambda i: (
        f"{res.matches[i].policy.id} · {res.matches[i].policy.name}  (점수 {res.matches[i].score:.0f})"
    ),
    horizontal=True,
    label_visibility="collapsed",
)
m = res.matches[idx]
p = m.policy
c = st.columns([3, 2])
with c[0]:
    st.markdown(f"**{p.name}**  \n{p.summary}")
    st.caption(m.reason)
    if p.sources:
        st.markdown("출처: " + " · ".join(f"[{i + 1}]({u})" for i, u in enumerate(p.sources)))
with c[1]:
    dates = [
        f"발표 {p.announced}" if p.announced else "",
        f"시행 {p.effective}" if p.effective else "",
    ]
    st.markdown(f"**시점** {' / '.join(d for d in dates if d) or '확인 필요'}")
    st.markdown(f"**분석 단위** {p.unit}")
    st.markdown(
        f"**설계** {p.design_ko} — "
        + (f":green[{p.support}]" if p.support == "지원" else f":orange[{p.support}]")
    )
if p.pitfalls:
    with st.expander(f"식별상 함정 {len(p.pitfalls)}개", expanded=True):
        for x in p.pitfalls:
            st.markdown(f"- {x}")

# ③ 데이터셋 추천 ---------------------------------------------------------------------
st.subheader("③ 추천 데이터셋")
access_ko = {"api_key": "API 키(자동승인)", "file": "파일", "manual": "수동 수집"}
st.dataframe(
    [
        {
            "데이터셋": d.name,
            "제공": d.provider,
            "용도": {"outcome": "결과", "treatment": "처치", "covariate": "공변량"}[d.role],
            "단위": d.granularity,
            "접근": access_ko[d.access],
            "라이선스": d.license,
            "링크": d.url,
        }
        for d in p.datasets
    ],
    column_config={"링크": st.column_config.LinkColumn()},
    hide_index=True,
    use_container_width=True,
)
if live and idx == 0:
    st.caption(res.live_status)
    if res.live_hits:
        st.dataframe(
            [
                {
                    "공공데이터포털 검색": h.title,
                    "유형": h.kind,
                    "제공": h.provider,
                    "수정일": h.modified,
                    "링크": h.url,
                }
                for h in res.live_hits
            ],
            column_config={"링크": st.column_config.LinkColumn()},
            hide_index=True,
            use_container_width=True,
        )

# ④ 분석 ------------------------------------------------------------------------------
st.subheader("④ 효과 분석")
case = fv.ROOT / p.sample_case if p.sample_case else None
if case is None or not (case / "plan.yaml").exists():
    st.info(
        res.next_step
        if idx == 0
        else "이 정책은 아직 사전 등록된 분석계획이 없습니다. cases/_template 으로 시작하세요."
    )
    st.stop()

plan = fv.load_plan_dict(case)
st.markdown(
    f"사전 등록된 분석계획: `{p.sample_case}/plan.yaml`  \n> {plan.get('question', '').strip()}"
)
run = st.button("효과 분석 실행", type="primary")
log = None
if run:
    with st.spinner("수집 → 품질 점검 → 추정(무작위화 추론) → 가드 → 리포트 ..."):
        try:
            log = fv.run_flow_for(case, allow_uncommitted=False, use_llm=use_llm)
        except Exception as exc:  # noqa: BLE001
            st.exception(exc)
else:
    log = fv.load_flow_log(case)
    if log:
        st.caption("저장된 실행 결과를 표시합니다. 다시 돌리려면 '효과 분석 실행'.")
if log:
    fv.render_flow(st, case, log, plan)
