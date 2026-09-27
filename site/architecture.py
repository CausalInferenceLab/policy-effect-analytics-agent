"""아키텍처 페이지 본문 — 지침에서 출발해 어떤 판단을 거쳐 지금 구조가 됐는지 순서대로 설명한다."""

from __future__ import annotations

REPO = "https://github.com/CausalInferenceLab/policy-effect-analytics-agent"

GOALS = [
    ("문제를 데이터로 정의하고 효과를 추정", "공공·사회 문제의 해법이 실제로 어떤 효과를 냈는지"),
    ("전 과정을 LLM 에이전트로 자동화", "수집 → 지표 구조화 → 효과 추정 → 리포팅"),
    ("누구나 바로 쓰는 오픈소스", "GitHub와 분석 플랫폼으로 공유"),
]

# (질문, 근거, 결정, 어디에 반영됐나)
DECISIONS = [
    (
        "소셜 신호로 무엇을 정하나?",
        "출발 키트 05: 화제성으로 사례를 고르면 결과를 보고 고르는 셈 → 효과 과대 추정",
        "신호는 <b>주제까지만</b> 정한다. 분석은 그 주제의 정책 전체로",
        "catalog/topics.yaml · core/discovery",
    ),
    (
        "정책 목록은 어떻게 모으나?",
        "출발 키트 05: 법제처 조례 API는 무료·즉시 승인, '어느 지역이 언제부터'가 한 줄에",
        "조례형 주제는 법제처 API로 자동 수집, 고시형 주제는 에이전트가 고시문에서 이력 수집",
        "core/adapters/law.py · 주간 Actions",
    ),
    (
        "분석해도 되는 주제인지 어떻게 거르나?",
        "출발 키트의 세 관문: 언제 시작했나 · 누가 받았나 · 무엇으로 재나",
        "주제마다 관문 상태를 기록하고, 통과 못 하면 추정하지 않는다",
        "topics.yaml gates · 대시보드 배지",
    ),
    (
        "LLM에게 어디까지 맡기나?",
        "목표 2(자동화) vs 인과 판단의 과장 위험. 선행 시스템 CAIS도 규칙 기반 방법 선택을 택함",
        "LLM은 주제 매칭 보조·서술만. 추정 방법은 데이터 모양으로 <b>규칙</b>이 고르고, 수치는 라이브러리가 계산",
        "core/estimators · core/agent/guard.py",
    ),
    (
        "결과를 보고 계획을 바꾸면?",
        "공공 평가 기관의 사전 등록 관행(GSA OES, World Bank DIME)",
        "plan.yaml을 git에 커밋해야 추정 단계가 실행된다",
        "core/agent/nodes.py ① 게이트",
    ),
    (
        "처치 지역이 몇 곳뿐이면?",
        "토허구역 사례: 25개 구 중 4개. 기존 표준오차는 사전추세가 없어도 50~80% 기각",
        "처치 단위 10곳 미만이면 무작위화 추론으로 자동 전환",
        "core/estimators/ri.py",
    ),
    (
        "누구나 보려면 어디에 공개하나?",
        "출발 키트 04: Streamlit은 서버가 필요, 서버 없이 GitHub Pages로도 가능",
        "정적 대시보드를 Actions가 만들어 Pages로 배포. Streamlit은 개발용",
        "site/ · .github/workflows/pages.yml",
    ),
]

LAYERS = [
    (
        "인터페이스",
        "누가 보나",
        [
            ("대시보드", "GitHub Pages · 누구나"),
            ("Streamlit 앱", "개발·디버깅용"),
            ("CLI", "make flow CASE=…"),
        ],
    ),
    (
        "에이전트",
        "순서대로 실행",
        [
            ("① 문제 정의", "plan.yaml 검증 + 사전 등록 게이트"),
            ("② 수집 · ③ 지표", "어댑터 실행, 품질 점검"),
            ("④ 추정", "규칙이 고른 방법으로"),
            ("⑤ 가드 · ⑥ 리포트", "과장 차단, 재현 기록"),
        ],
    ),
    (
        "분석 코어",
        "LLM 없음, 결정론",
        [
            ("분석계획 스키마", "core/schema"),
            ("추정기", "DiD · 이벤트 스터디 · ITS"),
            ("추론", "무작위화 추론(소수 처치)"),
            ("판정", "식별됨 · 조건부 · 식별 불가"),
        ],
    ),
    (
        "데이터",
        "무엇을 모으나",
        [
            ("카탈로그", "주제 6 · 정책 8 · 데이터셋"),
            ("어댑터", "국토부 · KOSIS · 법제처 · 파일"),
            ("스냅샷", "출처·라이선스·해시 기록"),
        ],
    ),
]

CODE_MAP = [
    ("catalog/", "주제·정책·데이터셋 카탈로그", "문제 정의", "W2–W3"),
    ("core/discovery/", "소셜 신호 → 주제 → 정책 목록", "문제 정의", "W3"),
    ("core/adapters/", "공공데이터·법제처 수집", "데이터 수집", "W2"),
    ("core/schema/", "분석계획(plan.yaml) 규칙", "문제 정의", "W3"),
    ("core/estimators/", "추정·검증·판정", "추정", "W4–W5"),
    ("core/agent/", "6단계 Flow, 과잉해석 가드", "리포트·에이전트", "W5–W6"),
    ("cases/<조>/", "조별 분석 케이스", "조 전체", "W3–W7"),
    ("site/", "공개 대시보드", "리포트·에이전트", "W7"),
]

STATUS = [
    (
        "go",
        "구현됨",
        "주제 매칭 · 6단계 Flow · 사전 등록 게이트 · 이벤트 스터디/DiD/ITS · 무작위화 추론 · 과장 표현 가드 · 대시보드 자동 배포",
    ),
    (
        "warn",
        "키 대기",
        "국토부 실거래가(실데이터 전환) · 법제처 조례 자동 수집(시크릿 등록 후 다음 배포부터)",
    ),
    (
        "info",
        "다음 단계",
        "시차 도입 추정(Callaway–Sant'Anna, W4) · 합성통제(W5) · 검색량으로 선반영 점검(데이터랩 키)",
    ),
]


def body(e) -> str:
    goals = "".join(
        f'<div class="card"><div class="icon">{i + 1}</div><h3>{e(a)}</h3><p class="muted">{e(b)}</p></div>'
        for i, (a, b) in enumerate(GOALS)
    )
    decisions = "".join(
        f'<div class="card"><span class="n" style="font:700 12px var(--mono);color:var(--accent)">'
        f"결정 {i + 1:02d}</span><h3>{q}</h3>"
        f'<p class="muted" style="margin:4px 0">근거 — {why}</p><p style="margin:4px 0">→ {what}</p>'
        f'<p class="muted" style="margin:0"><code>{where}</code></p></div>'
        for i, (q, why, what, where) in enumerate(DECISIONS)
    )
    layers = "".join(
        f'<div class="card" style="display:grid;grid-template-columns:minmax(110px,160px) 1fr;gap:14px;align-items:center">'
        f'<div><h3 style="margin:0">{name}</h3><span class="muted">{hint}</span></div>'
        f'<div class="grid3" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px">'
        + "".join(
            f'<div style="background:var(--sunk);border-radius:10px;padding:8px 10px"><b style="font-size:14px">{a}</b>'
            f'<div class="muted" style="font-size:12.5px">{b}</div></div>'
            for a, b in items
        )
        + "</div></div>"
        for name, hint, items in LAYERS
    )
    code = "".join(
        f"<tr><td><a href='{REPO}/tree/main/{p.replace('<조>/', '')}'><code>{e(p)}</code></a></td>"
        f"<td>{e(r)}</td><td>{e(w)}</td><td>{e(wk)}</td></tr>"
        for p, r, w, wk in CODE_MAP
    )
    status = "".join(
        f'<div class="card"><span class="badge {c}">{lab}</span><p style="margin:8px 0 0">{e(t)}</p></div>'
        for c, lab, t in STATUS
    )
    return f"""
<div class="hero" style="padding-bottom:0"><span class="eyebrow">ARCHITECTURE</span>
<h1>어떻게 동작하나</h1>
<p class="lede">과정 목표 세 가지에서 출발해, 어떤 질문에 어떤 근거로 답했는지 순서대로 적었습니다.
지금 구조는 그 답들을 쌓은 결과입니다.</p></div>

<section style="padding-top:36px"><h2>출발점: 과정 목표</h2><div class="grid3" style="margin-top:14px">{goals}</div></section>

<section><h2>결정의 흐름</h2><p class="sub">목표를 코드로 옮기면서 부딪힌 질문 일곱 개입니다.</p>
<div class="grid">{decisions}</div></section>

<section><h2>네 개의 층</h2><p class="sub">위에서 아래로 호출합니다. LLM은 에이전트 층에서 서술과 주제 매칭만 돕고, 분석 코어에는 들어가지 않습니다.</p>
<div style="display:flex;flex-direction:column;gap:8px">{layers}</div>
<p class="muted" style="margin-top:10px">옆에서 GitHub Actions가 돕습니다: 테스트(CI) · 매주 데이터 갱신 · 대시보드 배포.</p></section>

<section><h2>코드 지도</h2><p class="sub">폴더마다 맡는 조원 역할과 주차입니다.</p>
<div class="tablewrap"><table><tr><th>폴더</th><th>하는 일</th><th>조원 역할</th><th>주차</th></tr>{code}</table></div></section>

<section><h2>지금 상태</h2><div class="grid3" style="margin-top:14px">{status}</div></section>
"""
