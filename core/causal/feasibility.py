"""가설·데이터 점검 — "이 질문, 지금 있는 데이터로 분석할 수 있나?" (추가 설치 없음).

주제(topics.yaml) 하나를 받아 카탈로그만 보고 판단한다. 데이터를 받거나 숫자를 계산하지 않는다.

    가설      정책(처치) ─▶ 결과 지표, 예상 방향
    점검 6개  ① 언제(처치 시점 근거) ② 누가(받은 곳·안 받은 곳) ③ 결과 데이터 ④ 공통 원인(통제) 데이터
              ⑤ 공간 단위 ⑥ 시간 단위 — 처치 근거와 결과 데이터가 같은 단위로 만날 수 있나
    판정      바로 분석 가능 · 데이터 한 가지 더 필요 · 아직 어려움

인과 그래프는 PyWhy(DoWhy)가 쓰는 모양(노드·화살표)으로 만든다: 정책 → 결과, 공통 원인 → 정책·결과.
공통 원인 데이터가 있으면 뒷문(backdoor) 경로를 막을 후보가 있다는 뜻이고, 없으면 이중차분의
'정책 전 추세가 나란했다'는 가정에 더 기대야 한다는 뜻이다.
"""

from __future__ import annotations

import re

READY = {"즉시", "자동승인", "없음"}
SPACE = [  # 굵은 단위 → 세밀한 단위
    ("전국", 0),
    ("시도", 1),
    ("시군구", 2),
    ("자치구", 2),
    ("시군", 2),
    ("읍면동", 3),
    ("법정동", 3),
    ("행정동", 3),
    ("상권", 4),
    ("지점", 4),
    ("도로", 4),
    ("개별", 5),
]
SPACE_KO = {0: "전국", 1: "시도", 2: "시군구", 3: "읍면동", 4: "지점·상권", 5: "개별 건"}
TIME = [
    ("연", 0),
    ("반기", 1),
    ("분기", 1),
    ("월", 2),
    ("주", 3),
    ("일", 4),
    ("시간", 5),
    ("실시간", 5),
]
TIME_KO = {0: "연", 1: "분기", 2: "월", 3: "주", 4: "일", 5: "시간"}
GATE_OK = {"pass": "ok", "check": "warn", "key": "warn", "fail": "miss"}


def space_level(text: str) -> int | None:
    """데이터셋 space 글 → 단위 단계. 시군구(법정동)처럼 둘이면 더 세밀한 쪽."""
    hits = [lv for k, lv in SPACE if k in (text or "")]
    return max(hits) if hits else None


def time_level(text: str) -> int | None:
    t = text or ""
    if "실시간" in t:
        return 5
    hits = [lv for k, lv in TIME if re.search(rf"(^|[^가-힣]){k}($|[^가-힣])", t) or t == k]
    return max(hits) if hits else None


def _ready(d) -> bool:
    return d.approval in READY or "자동승인" in d.approval or d.approval.startswith("없음")


def topic_feasibility(topic, datasets, issues=(), n_results: int = 0) -> dict:
    ds = [d for d in datasets if topic.id in d.topics]
    by = {r: [d for d in ds if r in d.roles] for r in ("treatment", "outcome", "covariate")}
    outs_ready = [d for d in by["outcome"] if _ready(d)]
    my_issues = [i for i in issues if i.topic == topic.id]
    legal = bool(topic.legal and (topic.legal.laws or topic.legal.admin_rules))
    events = list(getattr(topic, "events", []) or [])

    checks: list[dict] = []

    def add(key, status, label, detail):
        checks.append({"key": key, "status": status, "label": label, "detail": detail})

    gates = topic.gates
    when_src = []
    if my_issues:
        when_src.append(f"지금 이슈 {len(my_issues)}개의 공식 시행일")
    if legal:
        when_src.append("법제처 법령·행정규칙 개정일")
    if events:
        when_src.append(f"정리된 정책 사건 {len(events)}개")
    if by["treatment"]:
        when_src.append(f"처치 데이터 {len(by['treatment'])}개")
    g = gates.get("when")
    st = GATE_OK.get(g.status, "warn") if g else ("ok" if when_src else "miss")
    if not when_src:
        st = "miss"
    add(
        "when",
        st,
        "언제 시작했나 (처치 시점)",
        ", ".join(when_src) or "시행일 근거를 아직 못 찾았어요",
    )
    g = gates.get("who")
    add(
        "who",
        GATE_OK.get(g.status, "warn") if g else "warn",
        "누가 받았고 누가 안 받았나 (비교 대상)",
        (g.note if g and g.note else "받은 곳과 안 받은 곳을 나눌 기준을 확인해야 해요"),
    )
    if outs_ready:
        add(
            "what",
            "ok",
            "무엇으로 재나 (결과 데이터)",
            f"결과 데이터 {len(by['outcome'])}개 중 {len(outs_ready)}개는 오늘 받을 수 있어요",
        )
    elif by["outcome"]:
        add(
            "what",
            "warn",
            "무엇으로 재나 (결과 데이터)",
            f"결과 데이터 {len(by['outcome'])}개 — 키 발급·신청이 필요해요",
        )
    else:
        add(
            "what", "miss", "무엇으로 재나 (결과 데이터)", "결과를 잴 공공데이터를 아직 못 찾았어요"
        )
    add(
        "confounders",
        "ok" if by["covariate"] else "warn",
        "공통 원인 (통제 데이터)",
        f"인구·기상 같은 통제 데이터 {len(by['covariate'])}개 — 인과 그래프의 뒷문 경로를 막을 후보"
        if by["covariate"]
        else "통제 데이터가 없어요. '정책 전 추세가 나란했다'는 가정에 더 기대야 해요",
    )
    # 단위: 결과 데이터가 처치 근거와 만날 수 있는 가장 세밀한 단위
    o_space = [lv for d in by["outcome"] if (lv := space_level(d.space)) is not None]
    o_time = [lv for d in by["outcome"] if (lv := time_level(d.time)) is not None]
    # 정책은 지역 단위로 배정된다 — 처치 자료가 개별 건이어도 읍면동보다 세밀하게 나누지 않는다
    t_space = [min(lv, 3) for d in by["treatment"] if (lv := space_level(d.space)) is not None]
    t_time = [lv for d in by["treatment"] if (lv := time_level(d.time)) is not None]
    if legal or my_issues:  # 법령·고시·조례 시행일은 시군구·일 단위로 나뉜다고 본다
        t_space.append(2)
        t_time.append(4)
    space_common = min(max(o_space), max(t_space)) if o_space and t_space else None
    time_common = min(max(o_time), max(t_time)) if o_time and t_time else None
    add(
        "space",
        "ok"
        if space_common is not None and space_common >= 2
        else "warn"
        if space_common is not None
        else "miss",
        "공간 단위가 맞나",
        f"{SPACE_KO[space_common]} 단위까지 처치와 결과를 맞출 수 있어요"
        if space_common is not None
        else "처치·결과 데이터의 공간 단위를 확인해야 해요",
    )
    add(
        "time",
        "ok"
        if time_common is not None and time_common >= 2
        else "warn"
        if time_common is not None
        else "miss",
        "시간 단위가 맞나",
        f"{TIME_KO[time_common]} 단위 전후 비교가 가능해요 (정책 전 최소 3시점 필요)"
        if time_common is not None
        else "결과 데이터의 시간 단위를 확인해야 해요",
    )
    miss = sum(c["status"] == "miss" for c in checks)
    warn = sum(c["status"] == "warn" for c in checks)
    if miss == 0 and warn == 0:
        verdict, label = "go", "바로 분석 가능"
    elif miss == 0:
        verdict, label = "warn", f"확인 {warn}가지 뒤 가능"
    elif miss == 1:
        verdict, label = "warn", "데이터 한 가지 더 필요"
    else:
        verdict, label = "stop", "아직 어려움"
    outcome_name = (my_issues[0].outcomes[0] if my_issues and my_issues[0].outcomes else None) or (
        by["outcome"][0].measures[0] if by["outcome"] and by["outcome"][0].measures else "결과 지표"
    )
    policy_name = my_issues[0].name if my_issues else f"{topic.name} 정책"
    covs = [d.name for d in by["covariate"]][:4]
    sentence = (
        f"'{policy_name}'(처치)이 '{outcome_name}'(결과)을 바꿨다 — 받은 곳과 안 받은 곳의 전후 변화 차이로 확인"
        if my_issues
        else f"{topic.question} — 정책을 받은 곳과 안 받은 곳의 전후 변화 차이로 확인 (결과 후보: {outcome_name})"
    )
    return {
        "topic": topic.id,
        "hypothesis": {
            "question": topic.question,
            "treatment": policy_name,
            "outcome": outcome_name,
            "sentence": sentence,
        },
        "checks": checks,
        "verdict": verdict,
        "label": label,
        "n_results": n_results,
        "graph": {  # PyWhy(DoWhy) 그래프와 같은 모양: 노드 · 화살표
            "nodes": ["정책", "결과", *[f"공통 원인: {c}" for c in covs], "시간 추세"],
            "edges": [["정책", "결과"], ["시간 추세", "결과"]]
            + [[f"공통 원인: {c}", "정책"] for c in covs]
            + [[f"공통 원인: {c}", "결과"] for c in covs],
        },
    }
