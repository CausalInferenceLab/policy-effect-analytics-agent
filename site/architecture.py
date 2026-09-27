"""구조 페이지 본문 — 한 장 그림 → 층 → 결정 → 필요한 것 → 폴더 → 상태 → 관련 오픈소스 순서로 보여준다."""

from __future__ import annotations

REPO = "https://github.com/CausalInferenceLab/policy-effect-analytics-agent"

GOALS = [
    ("문제를 데이터로 정의하고 효과를 추정", "공공·사회 문제의 해법이 실제로 효과를 냈는지"),
    ("전 과정을 AI 에이전트로 자동화", "수집 → 지표 정리 → 효과 추정 → 리포트"),
    ("누구나 바로 쓰는 오픈소스", "GitHub와 분석 사이트로 공유"),
]

# 한 장 그림: 두 개의 고리. (이름, 설명, 코드 위치)
LOOP_TALK = [
    ("질문", "사이트 대화창에 궁금한 정책을 적는다", "site/ask.js"),
    ("정리", "주제·데이터·조심할 점·계획 초안을 함께 만든다", "catalog/ · 가이드/AI 모드"),
    (
        "제안",
        "대화가 GitHub 이슈가 된다 (라벨 from-site)",
        ".github/ISSUE_TEMPLATE/site-question.yml",
    ),
    ("반영", "검토 후 카탈로그·케이스 PR로 들어가고 순위가 갱신된다", "scripts/refresh_trends.py"),
]
LOOP_ANALYZE = [
    ("주제", "주제의 정책을 전부 모으고 세 가지를 확인한다", "catalog/topics.yaml"),
    ("계획", "데이터를 보기 전에 plan.yaml을 커밋한다", "cases/<내ID>-<주제>/"),
    ("계산", "규칙이 고른 방법으로 효과를 계산하고 점검한다", "core/estimators · core/agent"),
    ("공개", "판정과 그림이 사이트에 자동으로 올라간다", "site/build.py · Actions"),
]

LAYERS = [
    (
        "화면",
        "누가 보나",
        [
            ("대화창", "가이드 모드(키 없이) · 내 AI 키 모드"),
            ("요즘 궁금한 주제", "사이트 질문 수 · 검색 관심도 순위"),
            ("주제 · 이슈 · 데이터 지도", "정적 페이지, 누구나"),
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
            ("데이터셋", "역할 · 단위 · 받는 법 · 이용 조건"),
            ("수집기", "국토부 · KOSIS · 법제처 · 파일"),
        ],
    ),
]

# (질문, 근거, 결정, 코드 위치)
DECISIONS = [
    (
        "소셜 반응으로 무엇을 정하나?",
        "출발 키트: 화제가 된 정책만 고르면 결과를 보고 사례를 고르는 셈이 되어 효과가 부풀려진다",
        "소셜 반응은 <b>주제까지만</b> 정한다. 순위도 주제를 고르는 데만 쓰고, 분석은 그 주제의 정책 전체로",
        "catalog/topics.yaml · core/discovery",
    ),
    (
        "대화창의 AI는 어떻게 부르나?",
        "사이트는 서버가 없는 GitHub Pages다. 공용 키를 사이트에 넣으면 누구나 볼 수 있다",
        "키 없이도 되는 <b>가이드 모드</b>가 기본. AI 대화는 사용자가 <b>자기 키</b>를 넣으면 브라우저가 직접 부르고, 키는 저장하지 않는다",
        "site/ask.js",
    ),
    (
        "대화를 어떻게 오픈소스에 반영하나?",
        "대화가 브라우저 안에만 있으면 쌓이지 않는다. 반대로 자동 저장하면 개인정보 위험이 있다",
        "사용자가 <b>직접 누를 때만</b> GitHub 이슈로 올린다. 사람이 검토해 카탈로그·케이스 PR로 넣는다",
        "site-question.yml · CONTRIBUTING.md",
    ),
    (
        "순위는 무엇으로 매기나?",
        "지어낸 인기도는 신뢰를 깎는다. 확인 가능한 신호만 쓴다",
        "최근 30일 사이트 질문 수 → 네이버 검색 관심도(키가 있을 때) → 최근 시행·발표일. 쓴 기준을 화면에 적는다",
        "scripts/refresh_trends.py",
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
        "core/adapters/law.py",
    ),
    (
        "AI에게 어디까지 맡기나?",
        "인과 판단을 AI에 맡기면 과장 위험이 크다. 비슷한 오픈소스(CAIS)도 규칙으로 방법을 고른다",
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
        "GitHub Actions가 매일 사이트를 만들어 Pages로 공개한다. Streamlit은 개발용",
        "site/ · .github/workflows/pages.yml",
    ),
]

# (무엇, 왜, 누가, 상태 배지, 상태)
NEEDS = [
    (
        "법제처 OC 인증값",
        "조례형 주제의 정책 목록 자동 수집",
        "운영진 · 레포 Secrets",
        "warn",
        "등록 대기",
    ),
    (
        "공공데이터포털 인증키",
        "실거래가 등 실제 데이터로 분석 (지금 예시는 시뮬레이션)",
        "멘티 각자 · .env",
        "warn",
        "각자 신청",
    ),
    (
        "네이버 데이터랩 키",
        "순위의 검색 관심도, '미리 반응했나' 점검",
        "운영진 · 레포 Secrets",
        "info",
        "선택",
    ),
    (
        "모두가 쓰는 AI 대화",
        "지금은 사용자 본인 키가 있어야 AI 모드. 키 없이 모두 쓰게 하려면 사용량 제한이 있는 작은 중계 서버와 비용 부담 주체가 필요",
        "운영진 결정",
        "info",
        "결정 필요",
    ),
    (
        "사이트 질문 검토",
        "올라온 질문을 새 주제 · 데이터 · 분석으로 나누고 PR로 반영",
        "멘토 + 멘티 순번 · 주 1회",
        "warn",
        "시작 전",
    ),
    (
        "공공데이터포털 검색 전환",
        "지금 검색은 웹 페이지를 읽는 방식. 공식 목록 API로 바꾼다",
        "개발",
        "info",
        "다음",
    ),
    (
        "시차 도입 이중차분 · 합성통제",
        "지역마다 시작일이 다르거나 정책 지역이 한두 곳인 이슈",
        "개발 · 4~5주차",
        "info",
        "다음",
    ),
]

# (폴더, 하는 일, 누가 고치나)
CODE_MAP = [
    ("cases/", "멘티별 분석 폴더 (<내ID>-<주제>, _template에서 시작)", "폴더 주인"),
    ("catalog/", "주제 · 이슈 · 데이터셋 목록 (데이터 지도)", "누구나 (PR)"),
    ("site/", "이 사이트 · 대화창(ask.js)", "메인테이너"),
    ("scripts/", "조례 · 순위 갱신, 활동 확인", "메인테이너"),
    ("core/discovery/", "소셜 반응 → 주제 → 정책 · 데이터", "메인테이너"),
    ("core/adapters/", "공공데이터 · 법제처 수집기", "메인테이너"),
    ("core/schema/", "분석 계획(plan.yaml) 규칙", "메인테이너"),
    ("core/estimators/", "효과 계산 · 점검 · 판정", "메인테이너"),
    ("core/agent/", "6단계 실행, 과장 차단", "메인테이너"),
]

STATUS = [
    (
        "go",
        "완성",
        "대화창(가이드 · 내 AI 키) · 대화 → 이슈 · 주제 순위 · 데이터 지도 · 6단계 실행 · 계획 커밋 확인 · 이중차분/단절 시계열 · 무작위화 추론 · 과장 차단 · 사이트 자동 공개",
    ),
    (
        "warn",
        "키 대기",
        "국토부 실거래가(토허구역 예시는 지금 시뮬레이션) · 법제처 조례 자동 수집 · 검색 관심도(선택)",
    ),
    (
        "info",
        "다음",
        "시차 도입 이중차분(4주차) · 합성통제(5주차) · 검색량으로 '미리 반응했나' 점검",
    ),
]

# (이름, 무엇을, 관계, 라이선스)
RELATED = [
    (
        "CAIS (causal-agent)",
        "자연어 인과 질문 → 방법 선택 → 추정",
        "방법 선택 규칙을 참고. 한국 공공데이터·사전 등록은 없음",
        "MIT",
    ),
    (
        "Causal-Copilot",
        "LLM 인과 분석 에이전트",
        "보완 관계. 우리는 한국 공공데이터·사전 등록에 집중",
        "MIT",
    ),
    (
        "PublicDataReader · kpubdata",
        "공공데이터 API 파이썬 래퍼",
        "필요하면 수집기로 가져다 쓸 수 있음",
        "MIT",
    ),
    ("data-go-mcp-servers", "공공데이터포털 MCP 서버", "AI 도구 연결 시 후보", "Apache-2.0"),
    (
        "PolicyEngine · OpenFisca",
        "세금·복지 제도 시뮬레이터",
        "목적이 다름(사전 시뮬레이션). AGPL이라 코드 가져오지 않음",
        "AGPL-3.0",
    ),
    (
        "hollobit/PAX",
        "공공 AI 도입 사례 아카이브",
        "화면 구성만 참고. 라이선스 표기가 없어 코드·글은 가져오지 않음",
        "표기 없음",
    ),
    (
        "국회예산정책처 · 기획재정부 평가",
        "공식 재정사업 평가",
        "우리 결과는 공식 평가가 아니며 그렇게 보이지 않게 표시",
        "—",
    ),
]


def _loop(title: str, steps, e) -> str:
    cells = []
    for i, (a, b, where) in enumerate(steps):
        if i:
            cells.append('<div class="arrow" aria-hidden="true">→</div>')
        cells.append(
            f'<div class="step"><span class="n">{i + 1:02d}</span><b>{e(a)}</b><p>{e(b)}</p>'
            f'<code class="where">{e(where)}</code></div>'
        )
    return f'<div class="loop"><h3>{title}</h3><div class="steps">{"".join(cells)}</div></div>'


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
        '<div class="card layer">'
        f'<div><h3 style="margin:0">{name}</h3><span class="muted">{hint}</span></div>'
        '<div class="cells">'
        + "".join(
            f'<div class="cell"><b>{a}</b><div class="muted small">{b}</div></div>'
            for a, b in items
        )
        + "</div></div>"
        for name, hint, items in LAYERS
    )
    needs = "".join(
        f"<tr><td><b>{e(a)}</b></td><td>{e(why)}</td><td>{e(who)}</td>"
        f'<td><span class="badge {c}">{e(st)}</span></td></tr>'
        for a, why, who, c, st in NEEDS
    )
    code = "".join(
        f"<tr><td><a href='{REPO}/tree/main/{p}'><code>{e(p)}</code></a></td><td>{e(r)}</td><td>{e(w)}</td></tr>"
        for p, r, w in CODE_MAP
    )
    status = "".join(
        f'<div class="card"><span class="badge {c}">{lab}</span><p style="margin:8px 0 0">{e(t)}</p></div>'
        for c, lab, t in STATUS
    )
    related = "".join(
        f"<tr><td><b>{e(n)}</b></td><td>{e(w)}</td><td>{e(r)}</td><td>{e(lic)}</td></tr>"
        for n, w, r, lic in RELATED
    )
    return f"""
<div class="hero" style="padding-bottom:0"><span class="eyebrow">구조</span>
<h1>한 장으로 보는 구조</h1>
<p class="lede">두 개의 고리로 움직입니다. 사람들의 질문이 <b>대화 고리</b>로 들어와 주제와 데이터가 쌓이고,
멘티가 <b>분석 고리</b>로 그 주제의 효과를 확인해 다시 사이트에 올립니다.</p></div>

<section style="padding-top:28px">
{_loop("대화 고리 · 질문이 쌓이는 길", LOOP_TALK, e)}
<div class="loop-join" aria-hidden="true">↓ 검토를 거친 주제·데이터가 분석의 출발점이 됩니다</div>
{_loop("분석 고리 · 효과를 확인하는 길", LOOP_ANALYZE, e)}
</section>

<section><h2>네 개의 층</h2><p class="sub">위에서 아래로 부릅니다. AI는 화면(대화)과 에이전트(글쓰기)에서만 돕고, 분석 엔진에는 들어가지 않습니다.</p>
<div style="display:flex;flex-direction:column;gap:8px">{layers}</div>
<p class="muted" style="margin-top:10px">GitHub Actions가 옆에서 돕습니다: 코드 검사 · 매일 순위 갱신과 사이트 공개 · 조례 수집(키가 있을 때).</p></section>

<section><h2>무엇이 더 필요한가</h2><p class="sub">지금 구조를 끝까지 돌리려면 아래가 필요합니다. 비밀값은 레포에 적지 않고 Settings → Secrets에만 넣습니다.</p>
<div class="tablewrap"><table><tr><th>무엇</th><th>왜</th><th>누가 · 어디에</th><th>상태</th></tr>{needs}</table></div></section>

<section><h2>질문과 결정</h2><p class="sub">과정 목표를 코드로 옮기면서 부딪힌 질문 {len(DECISIONS)}개와, 어떤 근거로 답했는지입니다.</p>
<div class="grid3" style="margin:0 0 14px">{goals}</div>
<div class="grid">{decisions}</div></section>

<section><h2>폴더 안내</h2><p class="sub">멘티는 <code>cases/</code>의 내 폴더와 <code>catalog/</code>만 고치면 됩니다.</p>
<div class="tablewrap"><table><tr><th>폴더</th><th>하는 일</th><th>누가 고치나</th></tr>{code}</table></div></section>

<section><h2>지금 상태</h2><div class="grid3" style="margin-top:14px">{status}</div></section>

<section><h2>관련 오픈소스와의 관계</h2><p class="sub">비슷한 프로젝트와 겹치거나 부딪히는 부분이 있는지 확인했습니다. 라이선스 충돌은 없고, 서로 보완하는 관계입니다.
GPL·AGPL 코드는 필수 의존성으로 가져오지 않습니다.</p>
<div class="tablewrap"><table><tr><th>프로젝트</th><th>무엇을</th><th>우리와의 관계</th><th>라이선스</th></tr>{related}</table></div></section>
"""
