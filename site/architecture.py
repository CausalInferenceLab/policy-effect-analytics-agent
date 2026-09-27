"""구조 페이지 본문 — 과정 목표에서 출발해 어떤 판단을 거쳐 지금 구조가 됐는지 순서대로 보여준다."""

from __future__ import annotations

REPO = "https://github.com/CausalInferenceLab/policy-effect-analytics-agent"

GOALS = [
    ("문제를 데이터로 정의하고 효과를 추정", "공공·사회 문제의 해법이 실제로 효과를 냈는지"),
    ("전 과정을 AI 에이전트로 자동화", "수집 → 지표 정리 → 효과 추정 → 리포트"),
    ("누구나 바로 쓰는 오픈소스", "GitHub와 분석 사이트로 공유"),
]

# (질문, 근거, 결정, 코드 위치)
DECISIONS = [
    (
        "소셜 반응으로 무엇을 정하나?",
        "출발 키트: 화제가 된 정책만 고르면 결과를 보고 사례를 고르는 셈이 되어 효과가 부풀려진다",
        "소셜 반응은 <b>주제까지만</b> 정한다. 분석은 그 주제의 정책 전체로",
        "catalog/topics.yaml · core/discovery",
    ),
    (
        "필요한 데이터를 어떻게 정리하나?",
        "효과를 재려면 '누가 언제 받았나', '무엇이 변했나', '다른 요인' 세 종류가 모두 있어야 한다",
        "데이터셋마다 <b>역할·단위·받는 법·이용 조건</b>을 붙여 데이터 지도로 관리한다",
        "catalog/datasets.yaml · core/discovery/ontology.py",
    ),
    (
        "정책 목록은 어떻게 모으나?",
        "출발 키트: 법제처 조례 API는 무료·즉시 승인이고 '어느 지역이 언제부터'가 한 줄에 나온다",
        "조례형 주제는 법제처 API로 자동 수집, 나머지는 고시·발표 자료로 정리",
        "core/adapters/law.py · 매주 자동 갱신",
    ),
    (
        "분석해도 되는 주제인지 어떻게 거르나?",
        "출발 키트의 세 가지 확인: 언제 시작했나 · 누가 받았나 · 무엇으로 재나",
        "주제마다 세 가지 상태를 기록하고, 통과하지 못하면 계산하지 않는다",
        "topics.yaml gates · 사이트 배지",
    ),
    (
        "AI에게 어디까지 맡기나?",
        "자동화가 목표지만 인과 판단을 AI에 맡기면 과장 위험이 크다. 비슷한 오픈소스(CAIS)도 규칙으로 방법을 고른다",
        "AI는 주제 찾기와 글쓰기만. 방법은 데이터 모양을 보고 <b>규칙</b>이, 숫자는 검증된 라이브러리가 계산",
        "core/estimators · core/agent/guard.py",
    ),
    (
        "결과를 보고 계획을 바꾸면?",
        "공공 평가 기관의 사전 등록 관행(미국 GSA OES, 세계은행 DIME)",
        "plan.yaml을 git에 커밋해야 계산 단계가 실행된다",
        "core/agent/nodes.py",
    ),
    (
        "정책 지역이 몇 곳뿐이면?",
        "토허구역 예시는 25개 구 중 4개. 기존 방식은 추세 차이가 없어도 50~80% '차이 있음'으로 판정했다",
        "정책 지역이 10곳 미만이면 무작위화 추론으로 자동 전환",
        "core/estimators/ri.py",
    ),
    (
        "누구나 보려면 어디에 공개하나?",
        "출발 키트: Streamlit은 서버가 켜져 있어야 한다. 서버 없이 GitHub Pages로도 된다",
        "이 사이트를 GitHub Actions가 만들어 Pages로 공개한다. Streamlit은 개발용",
        "site/ · .github/workflows/pages.yml",
    ),
]

LAYERS = [
    (
        "화면",
        "누가 보나",
        [
            ("이 사이트", "GitHub Pages · 누구나"),
            ("Streamlit", "개발·점검용"),
            ("명령어", "make flow CASE=…"),
        ],
    ),
    (
        "에이전트",
        "순서대로 실행",
        [
            ("① 계획 확인", "plan.yaml 검증 + 커밋 확인"),
            ("② 수집 · ③ 정리", "데이터 받기, 품질 점검"),
            ("④ 계산", "규칙이 고른 방법으로"),
            ("⑤ 점검 · ⑥ 리포트", "과장 차단, 재현 기록"),
        ],
    ),
    (
        "분석 엔진",
        "AI 없이 계산만",
        [
            ("계획 양식", "core/schema"),
            ("추정", "이중차분 · 단절 시계열"),
            ("추론", "무작위화 추론(정책 지역 소수)"),
            ("판정", "근거 있음 · 조건부 · 판단 불가"),
        ],
    ),
    (
        "데이터 지도",
        "무엇을 어디서",
        [
            ("주제 · 이슈", "topics.yaml · issues.yaml"),
            ("데이터셋", "역할 · 단위 · 받는 법"),
            ("수집기", "국토부 · KOSIS · 법제처 · 파일"),
        ],
    ),
]

CODE_MAP = [
    ("catalog/", "주제 · 이슈 · 데이터셋 목록 (데이터 지도)", "문제 정의", "2~3주"),
    ("core/discovery/", "소셜 반응 → 주제 → 정책 · 데이터", "문제 정의", "3주"),
    ("core/adapters/", "공공데이터 · 법제처 수집기", "데이터 수집", "2주"),
    ("core/schema/", "분석 계획(plan.yaml) 규칙", "문제 정의", "3주"),
    ("core/estimators/", "효과 계산 · 점검 · 판정", "추정", "4~5주"),
    ("core/agent/", "6단계 실행, 과장 차단", "리포트 · 에이전트", "5~6주"),
    ("cases/", "조별 분석 폴더", "조 전체", "3~7주"),
    ("site/", "이 사이트", "리포트 · 에이전트", "7주"),
]

STATUS = [
    (
        "go",
        "완성",
        "주제 찾기 · 데이터 지도 · 6단계 실행 · 계획 커밋 확인 · 이중차분/단절 시계열 · 무작위화 추론 · 과장 차단 · 사이트 자동 공개",
    ),
    (
        "warn",
        "데이터 키 대기",
        "국토부 실거래가(토허구역 예시는 지금 시뮬레이션) · 법제처 조례 자동 수집(인증값 등록 후 다음 갱신부터)",
    ),
    (
        "info",
        "다음",
        "시차 도입 이중차분(4주차) · 합성통제(5주차) · 검색량으로 '미리 반응했나' 점검",
    ),
]


def body(e) -> str:
    goals = "".join(
        f'<div class="card"><div class="icon">{i + 1}</div><h3>{e(a)}</h3><p class="muted" style="margin:0">{e(b)}</p></div>'
        for i, (a, b) in enumerate(GOALS)
    )
    decisions = "".join(
        f'<div class="card"><span style="font:700 12px var(--mono);color:var(--accent)">질문 {i + 1:02d}</span>'
        f"<h3>{q}</h3><p class='muted' style='margin:4px 0'>근거 · {why}</p>"
        f"<p style='margin:6px 0'>→ {what}</p><p class='muted small' style='margin:0'><code>{where}</code></p></div>"
        for i, (q, why, what, where) in enumerate(DECISIONS)
    )
    layers = "".join(
        '<div class="card" style="display:grid;grid-template-columns:minmax(110px,150px) 1fr;gap:14px;align-items:center">'
        f'<div><h3 style="margin:0">{name}</h3><span class="muted">{hint}</span></div>'
        '<div class="grid3" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px">'
        + "".join(
            f'<div style="background:var(--sunk);border-radius:10px;padding:8px 10px"><b style="font-size:14px">{a}</b>'
            f'<div class="muted small">{b}</div></div>'
            for a, b in items
        )
        + "</div></div>"
        for name, hint, items in LAYERS
    )
    code = "".join(
        f"<tr><td><a href='{REPO}/tree/main/{p}'><code>{e(p)}</code></a></td>"
        f"<td>{e(r)}</td><td>{e(w)}</td><td>{e(wk)}</td></tr>"
        for p, r, w, wk in CODE_MAP
    )
    status = "".join(
        f'<div class="card"><span class="badge {c}">{lab}</span><p style="margin:8px 0 0">{e(t)}</p></div>'
        for c, lab, t in STATUS
    )
    return f"""
<div class="hero" style="padding-bottom:0"><span class="eyebrow">구조</span>
<h1>어떻게 만들어졌나</h1>
<p class="lede">과정 목표 세 가지에서 출발해, 만들면서 부딪힌 질문에 어떤 근거로 답했는지 순서대로 적었습니다.
지금의 구조는 그 답을 쌓은 결과입니다.</p></div>

<section style="padding-top:32px"><h2>출발점: 과정 목표</h2><div class="grid3" style="margin-top:14px">{goals}</div></section>

<section><h2>질문과 결정</h2><p class="sub">목표를 코드로 옮기면서 부딪힌 질문 {len(DECISIONS)}개입니다.</p>
<div class="grid">{decisions}</div></section>

<section><h2>네 개의 층</h2><p class="sub">위에서 아래로 부릅니다. AI는 에이전트 층에서 주제 찾기와 글쓰기만 돕고, 분석 엔진에는 들어가지 않습니다.</p>
<div style="display:flex;flex-direction:column;gap:8px">{layers}</div>
<p class="muted" style="margin-top:10px">GitHub Actions가 옆에서 돕습니다: 코드 검사 · 매주 데이터 갱신 · 사이트 공개.</p></section>

<section><h2>폴더 안내</h2><p class="sub">폴더마다 맡는 조원 역할과 주차입니다.</p>
<div class="tablewrap"><table><tr><th>폴더</th><th>하는 일</th><th>조원 역할</th><th>주차</th></tr>{code}</table></div></section>

<section><h2>지금 상태</h2><div class="grid3" style="margin-top:14px">{status}</div></section>
"""
