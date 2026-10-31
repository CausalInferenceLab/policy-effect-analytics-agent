"""정적 대시보드 빌더 → _site/ (GitHub Pages, 서버 없음)

    python site/build.py            # _site/ 에 HTML 생성
    python -m http.server -d _site  # http://localhost:8000 에서 미리보기

읽는 파일(모두 레포에 커밋된 것): catalog/topics.yaml · issues.yaml · datasets.yaml · policies.yaml,
catalog/snapshots/law_<주제>.csv(있으면), cases/<케이스>/flow_log.json · figures/*.png
"""

from __future__ import annotations

import html
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from core.discovery.catalog import GATE_STATUS_KO, load_catalog, load_topics  # noqa: E402
from core.discovery.ontology import (  # noqa: E402
    ACCESS_KO,
    DESIGN_PLAIN,
    PORTAL_KO,
    ROLE_KO,
    ROLE_SHORT,
    load_datasets,
    load_issues,
)

OUT = ROOT / "_site"
REPO = "https://github.com/CausalInferenceLab/policy-effect-analytics-agent"
SITE = "https://causalinferencelab.github.io/policy-effect-analytics-agent"
DESC = "뉴스 속 그 정책, 진짜 먹혔을까? 공공데이터로 직접 확인해 보는 시민 데이터 과학자 놀이터 (오픈소스)"
CSS = (HERE / "style.css").read_text(encoding="utf-8")

GATE_Q = {"when": "언제 시작했나", "who": "누가 받았나", "what": "무엇으로 재나"}
GATE_CLASS = {"pass": "go", "check": "warn", "key": "warn", "fail": "stop"}
VERDICT = {
    "identified": ("효과 근거 있음", "go"),
    "conditional": ("크기를 판별하지 못함", "warn"),
    "not_identified": ("판단 불가", "stop"),
}
DESIGN_SHORT = {
    "did_simultaneous": "이중차분",
    "did_staggered": "시차 도입 이중차분",
    "scm": "합성통제",
    "its": "단절 시계열",
}
SUPPORT = {
    "did_simultaneous": ("바로 분석 가능", "go"),
    "its": ("바로 분석 가능", "go"),
    "did_staggered": ("추정 모듈 준비 중 (4주차)", "warn"),
    "scm": ("추정 모듈 준비 중 (5주차)", "warn"),
}
COLLECT_KO = {
    "law_ordinance": "법제처 조례 API로 자동 수집",
    "notice": "고시·보도자료에서 이력 정리",
    "curated": "발표 자료를 표로 정리",
}
NAV = [
    ("results.html", "분석 결과"),
    ("index.html#topics", "이슈 보드"),
    ("issues.html", "지금 이슈"),
    ("data.html", "데이터"),
    ("projects.html", "참여"),
    ("impact.html", "성과"),
]


def goatcounter_code() -> str:
    """이용 통계(GoatCounter) 코드 — Actions 변수 GOATCOUNTER_CODE. 형식이 맞지 않으면 끈다."""
    import os
    import re

    code = os.getenv("GOATCOUNTER_CODE", "").strip().lower()
    return code if re.fullmatch(r"[a-z0-9][a-z0-9-]{1,40}", code) else ""


TERMS = [
    (
        "처치 · 대조",
        "정책을 받은 동네가 처치, 안 받은 '쌍둥이 동네'가 대조예요. 대조가 '정책이 없었다면?'을 대신 보여 줘요.",
    ),
    (
        "이중차분",
        "받은 동네의 전후 변화에서 쌍둥이 동네의 전후 변화를 빼요. 경기·계절처럼 다 같이 겪은 변화는 지워지고 정책 몫만 남아요.",
    ),
    (
        "평행 추세",
        "정책 전에 두 동네가 나란히 걷고 있었어야 비교가 공정해요. 그래서 제일 먼저 확인해요.",
    ),
    (
        "사전 등록",
        "답을 보기 전에 정답지를 봉인하기. 무엇을 어떻게 볼지 plan.yaml에 먼저 적어 커밋해요. 결과를 보고 말을 바꾸지 않으려고요.",
    ),
    (
        "무작위화 추론",
        "정책 지역이 몇 곳뿐이면, 가짜 정책 지역을 바꿔 가며 비교해 '이 정도 차이는 우연으로도 나오나?'를 봐요.",
    ),
    (
        "판정",
        "효과 근거 있음 · 크기를 판별하지 못함 · 판단 불가 세 가지예요. '판단 불가'도 정직한 답이에요.",
    ),
]

e = html.escape


# ─── 공통 ──────────────────────────────────────────────────────────────────────
def page(
    title: str,
    body: str,
    current: str,
    depth: int = 0,
    desc: str | None = None,
    path: str | None = None,
    image: str | None = None,
) -> str:
    """공통 틀. path(사이트 안 경로)를 주면 공유 미리보기(Open Graph)용 주소·그림을 붙인다."""
    up = "../" * depth
    d = e(desc or DESC)
    og = f'<meta property="og:type" content="website"><meta property="og:title" content="{e(title)}">'
    og += (
        f'<meta property="og:description" content="{d}"><meta property="og:locale" content="ko_KR">'
    )
    if path:
        og += f'<meta property="og:url" content="{SITE}/{e(path)}"><link rel="canonical" href="{SITE}/{e(path)}">'
    if image:
        og += f'<meta property="og:image" content="{SITE}/{e(image)}"><meta name="twitter:card" content="summary_large_image">'
    links = "".join(
        f'<a href="{up}{href}"{" aria-current=page" if href == current else ""}>{label}</a>'
        for href, label in NAV
    )
    gc = goatcounter_code()
    gc_attr = f' data-gc="{gc}"' if gc else ""
    privacy = (
        " · 이용 통계는 쿠키 없이 페이지·버튼 사용 수만 셉니다(GoatCounter, 브라우저의 '추적 안 함'을 따름)"
        if gc
        else ""
    )
    return f"""<!doctype html><html lang="ko"{gc_attr}><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>
<meta name="description" content="{d}">{og}
<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
<style>{CSS}</style><script src="{up}track.js" defer></script></head><body>
<a class="skip" href="#main">본문으로 건너뛰기</a>
<nav class="nav" aria-label="주 메뉴"><div class="in"><a class="brand" href="{up}index.html"><span class="mark" aria-hidden="true"></span>정책 효과 분석</a>
<span class="links">{links}<a href="{REPO}">GitHub</a></span></div></nav>
<main class="wrap" id="main">{body}
<footer>가짜연구소 인과추론팀 × 오픈업 오픈소스 AI 특화형 트랙3 · 이 사이트의 숫자와 판정은 레포의 <code>catalog/</code>·<code>cases/</code>에서
자동으로 만들어집니다. 시뮬레이션 결과에는 따로 표시가 붙습니다.<br>
<span class="foot-links"><a href="{up}results.html">분석 결과</a> <a href="{up}lineage.html">데이터 계보</a> <a href="{up}apps.html">서비스와 공개 API</a> <a href="{up}architecture.html">구조와 작동 방식</a> <a href="{up}projects.html">참여</a> <a href="{up}impact.html">성과</a> <a href="{REPO}/blob/main/docs/ops/mentee-guide.md">참여 가이드</a> <a href="{REPO}">소스 코드 (MIT)</a></span><br>
<b>공식 평가가 아닙니다.</b> 학습·연구용 오픈소스 분석이며 정부·공공기관의 공식 평가나 통계가 아니고, 데이터 제공 기관의 후원·보증을 뜻하지 않습니다.{privacy}</footer>
</main></body></html>"""


def gate_badges(t) -> str:
    return "".join(
        f'<span class="badge {GATE_CLASS[g.status]}" title="{e(g.note)}">{GATE_Q[k]} · {GATE_STATUS_KO[g.status]}</span>'
        for k, g in t.gates.items()
    )


def role_badges(roles) -> str:
    return "".join(f'<span class="badge r-{r}">{ROLE_SHORT[r]}</span>' for r in roles)


def dots(n: int) -> str:
    return f'<span class="dots" aria-label="난이도 {n}/3">{"●" * n}{"○" * (3 - n)}</span>'


def readiness(t) -> tuple[str, str, str]:
    st = {g.status for g in t.gates.values()}
    if "fail" in st:
        return "fail", "관문 탈락", "stop"
    if "check" in st:
        return "check", "확인할 것 있음", "warn"
    if "key" in st:
        return "key", "데이터 키만 있으면 됨", "warn"
    return "ready", "분석 가능", "go"


def dataset_table(ds) -> str:
    rows = "".join(
        f"<tr><td><a href='{e(d.url)}'>{e(d.name)}</a><div class='muted small'>{e(d.provider)} · {PORTAL_KO.get(d.portal, d.portal)}</div></td>"
        f"<td>{role_badges(d.roles)}</td><td>{e(d.space)} × {e(d.time)}</td>"
        f"<td>{ACCESS_KO[d.access]}<div class='muted small'>{e(d.approval)}</div></td></tr>"
        for d in ds
    )
    return (
        "<div class='tablewrap'><table><tr><th>데이터셋</th><th>역할</th><th>단위</th><th>받는 법</th></tr>"
        f"{rows}</table></div>"
    )


# ─── 그림 ─────────────────────────────────────────────────────────────────────
def timeline_svg(events) -> str:
    if not events:
        return ""
    d = pd.to_datetime([ev.date for ev in events])
    lo = pd.Timestamp(year=d.min().year, month=1, day=1)
    hi = pd.Timestamp(year=d.max().year + 1, month=1, day=1)
    x0, x1 = 20, 880

    def x(t):
        return x0 + (x1 - x0) * ((t - lo) / (hi - lo))

    def yx(y):
        return x(pd.Timestamp(year=y, month=1, day=1))

    ticks = "".join(
        f'<line x1="{yx(y):.0f}" y1="26" x2="{yx(y):.0f}" y2="32" stroke="var(--muted)"/>'
        f'<text x="{yx(y):.0f}" y="48" text-anchor="middle">{y}</text>'
        for y in range(lo.year, hi.year + 1)
    )
    marks = "".join(
        f'<circle cx="{x(t):.0f}" cy="26" r="7" fill="var(--accent)"/>'
        f'<text x="{x(t):.0f}" y="14" text-anchor="middle">{i + 1}</text>'
        for i, t in enumerate(d)
    )
    items = "".join(
        f"<li><b>{ev.label}</b> {e(ev.what)}"
        + (f' <a href="{e(ev.source)}">출처</a>' if ev.source else "")
        + "</li>"
        for ev in events
    )
    return (
        '<svg viewBox="0 0 900 56" width="100%" role="img" aria-label="정책 시점">'
        f'<line x1="{x0}" y1="26" x2="{x1}" y2="26" stroke="var(--ink2)"/>{ticks}{marks}</svg><ol>{items}</ol>'
    )


def bars_svg(counts: pd.Series, label: str) -> str:
    if counts.empty:
        return ""
    w, h, pad = 900, 220, 30
    bw = (w - 2 * pad) / len(counts)
    mx = counts.max()
    parts = []
    for i, (k, v) in enumerate(counts.items()):
        bh, cx = (h - 60) * v / mx, pad + i * bw + bw / 2
        parts.append(
            f'<rect x="{pad + i * bw + 3:.0f}" y="{h - 30 - bh:.0f}" width="{bw - 6:.0f}" height="{bh:.0f}" rx="3" fill="var(--accent)"/>'
            f'<text x="{cx:.0f}" y="{h - 12}" text-anchor="middle">{k}</text>'
            f'<text x="{cx:.0f}" y="{h - 36 - bh:.0f}" text-anchor="middle">{v}</text>'
        )
    return f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="{e(label)}">{"".join(parts)}</svg>'


# ─── 분석 결과 ────────────────────────────────────────────────────────────────
# ─── 홈 ──────────────────────────────────────────────────────────────────────
# 대화창 엔진은 site/ask.js (가이드 모드 + 사용자 키로 부르는 AI 모드). 여기서는 필터만 다룬다.
HOME_STEPS = [
    ("찾기", "대화창이나 지금 이슈에서 사람들이 궁금해하는 <b>주제</b>를 고릅니다", "트랙 A · B"),
    ("모으기", "그 주제의 정책과 데이터를 <b>전부</b> 모으고 계보로 잇습니다", "트랙 A"),
    ("거르기", "세 가지를 확인합니다. 언제 시작했나 · 누가 받았나 · 무엇으로 재나", "트랙 A · B"),
    ("계획하기", "데이터를 보기 전에 가설과 분석 계획을 먼저 적어 둡니다", "트랙 B"),
    ("비교하기", "정책을 받은 곳과 안 받은 곳의 변화를 비교합니다", "트랙 B"),
    (
        "말하기",
        "효과 근거 있음 · 크기를 판별하지 못함 · 판단 불가 중 하나로 쓰고, 결과는 API로 공개됩니다",
        "트랙 B → C",
    ),
]
HOME_EXAMPLES = [
    "토허제 확대하고 강남 집값 잡혔나요?",
    "소비쿠폰 받고 동네 가게 매출 늘었나?",
    "모두의 카드 나오고 지하철 더 타나?",
    "5030 속도 줄이고 사고 줄었나?",
]
REFLECT_STEPS = [
    ("대화", "궁금한 정책을 적으면 주제·데이터·조심할 점·분석 계획 초안을 함께 정리합니다."),
    ("제안", "'제안으로 올리기'를 누르면 대화가 GitHub 이슈로 올라갑니다. 로그인만 있으면 됩니다."),
    (
        "검토",
        "멘토·멘티가 이슈를 보고 새 주제·데이터셋은 카탈로그에, 분석은 케이스 폴더에 PR로 넣습니다.",
    ),
    (
        "반영",
        "합쳐지면 사이트가 다시 만들어집니다. 올라온 질문 수는 '요즘 궁금해하는 주제' 순위가 됩니다.",
    ),
]
TRENDS = ROOT / "catalog" / "snapshots" / "trends.json"


def catalog_json(topics, policies, issues, datasets, answers=()) -> str:
    """대화창(ask.js)이 읽는 카탈로그. </script> 가 끼어들지 않게 '</' 를 이스케이프한다."""
    import answers as ans

    data = {
        "repo": REPO,
        "results": ans.catalog(list(answers)),
        "topics": [
            {
                "id": t.id,
                "name": t.name,
                "question": t.question,
                "keywords": list(
                    dict.fromkeys(
                        t.keywords
                        + [
                            k
                            for pid in t.policies
                            for p in policies
                            if p.id == pid
                            for k in p.keywords
                        ]
                    )
                ),
                "gates": {k: {"status": g.status, "note": g.note} for k, g in t.gates.items()},
                "pitfalls": t.pitfalls,
                "legal": legal_summary(t),
            }
            for t in topics
        ],
        "issues": [
            i.model_dump(
                include={
                    "id",
                    "name",
                    "topic",
                    "issue",
                    "effective",
                    "treatment",
                    "control",
                    "outcomes",
                    "design",
                    "datasets",
                    "pitfalls",
                }
            )
            for i in issues
        ],
        "datasets": [
            d.model_dump(
                include={
                    "id",
                    "name",
                    "provider",
                    "url",
                    "roles",
                    "space",
                    "time",
                    "access",
                    "approval",
                    "license",
                    "topics",
                }
            )
            for d in datasets
        ],
    }
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def legal_summary(t) -> dict | None:
    """대화창에 보여줄 법령 요약: 근거 법률과 최근 바뀐 핵심 3건."""
    if not t.legal:
        return None
    df = legal_frame(t)
    recent = (
        legal_core(t, df).head(3)[["name", "change", "announced"]].to_dict("records")
        if df is not None
        else []
    )
    n = int(len(df)) if df is not None else 0
    return {
        "laws": t.legal.laws,
        "admin_rules": t.legal.admin_rules,
        "note": t.legal.note,
        "count": n,
        "recent": recent,
    }


def load_trends() -> dict:
    try:
        return json.loads(TRENDS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def latest_event(t, issues, today: str) -> str:
    """주제의 가장 최근 시행·발표일 (오늘 이후 예정일은 뺀다). ISO 문자열이라 사전순 비교가 곧 날짜순."""
    ds = [ev.date.isoformat() for ev in t.events] + [i.effective for i in issues if i.topic == t.id]
    ds = [d for d in ds if d <= today]
    return max(ds, default="")


def rank_topics(topics, issues, trends: dict, today: str | None = None):
    """사이트 질문 수 → 검색 관심도 → 최근 시행·발표일 순. 없는 신호는 0으로 두고 표시하지 않는다."""
    import datetime as _dt

    today = today or _dt.date.today().isoformat()
    tt = trends.get("topics", {})
    rows = [
        (
            t,
            tt.get(t.id, {}).get("questions", 0),
            tt.get(t.id, {}).get("search", 0.0),
            latest_event(t, issues, today),
        )
        for t in topics
    ]
    rows.sort(key=lambda r: (r[1], r[2], r[3]), reverse=True)
    srcs = set(trends.get("sources", []))
    has_q = "site_questions" in srcs and any(r[1] for r in rows)
    has_s = "naver_datalab" in srcs and any(r[2] for r in rows)
    if has_q or has_s:
        parts = (["최근 30일 사이트 질문 수"] if has_q else []) + (
            ["네이버 검색 관심도"] if has_s else []
        )
        basis = f"{' · '.join(parts)} 기준 · {e(trends.get('updated', ''))} 갱신"
    else:
        basis = "아직 모인 질문이 없어 최근 시행·발표 순입니다. 대화를 제안으로 올리면 순위에 반영됩니다."
    return rows, has_q, has_s, basis


def topic_rows(topics, issues, answers, trends: dict, datasets=(), lineages=()) -> tuple[str, str]:
    """홈의 흐름 지도: 질문 수 → 검색 관심도 → 최근 시행·발표 순으로 주제 × 다섯 단계. (HTML, 순서 기준 설명)"""
    import board

    rows, has_q, _has_s, basis = rank_topics(topics, issues, trends)
    issue_topics = {i.topic for i in issues}
    out = []
    for t, q, _s, last in rows:
        side = []
        if t.id in issue_topics:
            side.append('<span class="badge plain">지금 이슈</span>')
        if has_q and q:
            side.append(f'<span class="badge plain">질문 {q}</span>')
        if last:
            side.append(f'<span class="when">{last[:7].replace("-", ".")}</span>')
        out.append((t, board.topic_stages(t, issues, datasets, lineages, answers), "".join(side)))
    return board.flow_map(e, out), basis


def index_page(topics, policies, issues, datasets, projects=(), answers=(), lineages=()) -> str:
    import answers as ans
    import board

    chips = "".join(
        f'<button class="chip" type="button" data-ask="{e(x)}">{e(x)}</button>'
        for x in HOME_EXAMPLES
    )
    n_answers = sum(not a["mentor"] and not a["synthetic"] for a in answers)
    n_people = len({p["owner"] for p in projects if not p["mentor"]})
    topic_html, basis = topic_rows(topics, issues, answers, load_trends(), datasets, lineages)
    tot = board.totals(issues, datasets, lineages, answers)
    flow = board.flow_strip(
        e,
        tot,
        {
            "issue": "issues.html",
            "data": "data.html",
            "lineage": "lineage.html",
            "analysis": "results.html",
            "dashboard": "#topics",
        },
        board.ready_count(datasets),
    )
    issue_rows = "".join(
        f'<a class="issue-row" href="issues.html#{i.id}"><span class="when">{e(i.effective)}</span>'
        f"<b>{e(i.name)}</b>"
        f'<span class="side"><span class="badge {SUPPORT[i.design][1]}">{DESIGN_SHORT[i.design]}</span></span></a>'
        for i in issues[:4]
    )
    ready_rows = "".join(
        f'<a class="issue-row" href="{e(d.url)}"><span class="when">{e(d.provider[:20])}</span><b>{e(d.name)}</b>'
        f'<span class="side"><span class="badge plain">{e(d.time)}</span><span class="badge info">{e(d.approval)}</span></span></a>'
        for d in [d for d in datasets if d.approval in board.READY and "outcome" in d.roles][:4]
    )
    body = f"""
<div class="hero home">
<p class="sticker" aria-hidden="true">시민 데이터 과학자 모드 ON</p>
<h1>그 정책, 진짜 먹혔을까?</h1>
<p class="lede">뉴스 보다가 궁금했던 그 정책, 직접 확인해 봐요. 공공데이터를 찾아 드리고 '받은 동네 vs 안 받은 동네'를 비교하는 법을 알려 드려요.
데이터가 모른다고 하면 모른다고 말하는 것까지가 이 사이트의 규칙이에요.</p>
{flow}

<div class="ask" id="ask">
<div id="chat-log" class="chat-log" aria-live="polite" hidden></div>
<form id="chat-form" class="chat-form">
<label class="sr-only" for="q">궁금한 정책</label>
<textarea id="q" rows="2" placeholder="궁금한 정책을 적어 보세요"></textarea>
<button class="btn primary" type="submit">묻기</button></form>
<div class="chips" aria-label="예시 질문">{chips}</div>
<div class="chat-meta"><span id="mode" class="badge info">가이드 모드</span>
<button type="button" id="ai-toggle" class="linkish">내 AI 키로 대화하기</button>
<span class="muted small">대화는 이 브라우저 안에서만 쓰입니다. '제안으로 올리기'를 누를 때만 GitHub 이슈 화면이 열립니다. 법률 자문이 아닙니다.</span></div>
<div id="ai-panel" class="card ai-panel" hidden>
<p class="small" style="margin:0 0 8px">키를 넣으면 이 브라우저가 AI에 직접 묻습니다. 키는 이 페이지 메모리에만 있고 저장하지 않으며, 새로고침하면 사라집니다. 공용 PC에서는 쓰지 마세요.</p>
<div class="ai-grid">
<label>AI<select id="ai-provider"><option value="anthropic">Claude (Anthropic)</option><option value="openai">OpenAI 호환 (Ollama 등)</option></select></label>
<label id="ai-base-row" hidden>주소<input id="ai-base" placeholder="http://localhost:11434/v1"></label>
<label>모델<input id="ai-model" placeholder="비우면 기본값"></label>
<label>API 키<input id="ai-key" type="password" autocomplete="off" placeholder="sk-..."></label></div>
<div class="cta" style="margin-top:10px"><button type="button" id="ai-save" class="btn primary">연결</button>
<button type="button" id="ai-off" class="btn ghost">가이드 모드로</button></div>
<p class="muted small" style="margin:8px 0 0">로컬 Ollama는 <code>OLLAMA_ORIGINS=https://causalinferencelab.github.io</code>로 실행해야 브라우저에서 부를 수 있습니다.
AI도 결과를 계산하지 않습니다. 주제·데이터·계획을 함께 정리할 뿐이고, 숫자는 레포의 분석 코드가 냅니다. 법률 자문이 아닙니다.</p></div>
</div></div>

<section id="topics"><div class="sec-head"><h2>이슈 보드</h2></div>
<p class="sub">주제마다 이슈 → 공공데이터 → 계보 → 분석 → 대시보드가 어디까지 채워졌는지 보입니다. 칸의 숫자는 개수, 빈칸은 채울 곳입니다. {basis}</p>
{topic_html}</section>

{ans.strip(e, list(answers), topics)}

<div class="two">
<section id="issues"><div class="sec-head"><h2>지금 이슈</h2><a class="more" href="issues.html">{len(issues)}개 분석 가이드</a></div>
<p class="sub small">논쟁 중인 정책을 어떤 비교로, 어떤 데이터로 볼 수 있는지 정리했습니다.</p>
<div class="rows">{issue_rows}</div></section>
<section id="data-ready"><div class="sec-head"><h2>바로 받을 수 있는 데이터</h2><a class="more" href="data.html">{len(datasets)}개 전체</a></div>
<p class="sub small">정리한 공공데이터 {len(datasets)}개 중 {board.ready_count(datasets)}개는 키 발급 즉시 또는 키 없이 오늘 받을 수 있습니다. 데이터마다 단위·기간·받는 법·이용 조건을 적었습니다.</p>
<div class="rows">{ready_rows}</div></section>
</div>

<section id="next"><h2>나는 몇 레벨 시민 데이터 과학자?</h2>
<p class="sub">코딩을 몰라도 레벨 1부터 시작할 수 있어요. 한 칸씩 올라가 보세요.</p>
<ol class="levels">
<li><a href="#ask"><span class="lv">Lv.1</span><b>궁금해하기</b><span>대화창에 정책 하나 물어보기. 주제·데이터·조심할 점을 같이 정리해 드려요.</span></a></li>
<li><a href="results.html"><span class="lv">Lv.2</span><b>읽고 가져가기</b><span>결과 하나 열어 판정을 읽고, 인용문을 복사해 가기. 지금 {n_answers}개 있어요.</span></a></li>
<li><a href="data.html"><span class="lv">Lv.3</span><b>데이터 만져 보기</b><span>공공데이터 {len(datasets)}개 중 {board.ready_count(datasets)}개는 오늘 바로 받을 수 있어요. CSV로 같은 결과도 확인해 보기.</span></a></li>
<li><a href="projects.html"><span class="lv">Lv.4</span><b>같이 만들기</b><span>우리 동네 정책으로 분석 제안하기. 이미 {n_people}명이 하고 있어요.</span></a></li>
</ol>
<p class="small muted">이 사이트가 잘 쓰이고 있는지는 <a href="impact.html">성과</a>에서 매일 다시 세요.</p></section>
<script type="application/json" id="catalog">{catalog_json(topics, policies, issues, datasets, answers)}</script>
<script src="ask.js"></script><script src="board.js" defer></script>"""
    return page("정책 효과 분석 플랫폼", body, "index.html", path="index.html")


def how_sections() -> str:
    """홈에서 옮긴 '작동 방식' 설명 — 구조 페이지 아래에 붙인다."""
    flow = "".join(
        f'<div class="card"><span class="n">{i + 1:02d}</span><b>{a}</b><p>{b}</p><div class="who">{c}</div></div>'
        for i, (a, b, c) in enumerate(HOME_STEPS)
    )
    reflect = "".join(
        f'<div class="card"><span class="n">{i + 1:02d}</span><b>{a}</b><p>{b}</p></div>'
        for i, (a, b) in enumerate(REFLECT_STEPS)
    )
    return f"""
<section id="reflect"><h2>대화가 오픈소스가 되는 길</h2><p class="sub">여기서 나눈 질문이 새 주제·새 데이터·새 분석으로 쌓입니다. 없던 공공데이터 정책 분석을 함께 만드는 방식입니다.</p>
<div class="flow">{reflect}</div></section>

<section id="how"><h2>이렇게 확인합니다</h2><p class="sub">효과를 추정하는 한 바퀴(트랙 B의 Cycle)입니다. 1~2단계의 재료는 트랙 A의 데이터 계보가, 6단계의 결과는 트랙 C의 서비스가 이어받습니다.</p>
<div class="flow">{flow}</div></section>

<section id="why"><h2>왜 주제 단위로 보나</h2><p class="sub">화제가 된 정책 하나만 골라 분석하면, 결과를 보고 사례를 고르는 것과 같아집니다.</p>
<div class="split">
<div class="card"><h3><span class="badge stop">피하는 방식</span> 화제가 된 정책만 분석</h3>
<ul><li>조용했지만 효과가 컸던 정책이 빠집니다</li><li>화제가 되면 신청이 늘어 효과가 부풀려집니다</li>
<li>시행 전부터 화제였다면 사람들이 미리 움직여 비교가 흔들립니다</li></ul></div>
<div class="card"><h3><span class="badge go">우리 방식</span> 화제는 출발점으로만</h3>
<ul><li>화제는 <b>어느 주제를 볼지</b>만 정합니다. 순위도 주제를 고르는 데만 씁니다</li><li>그 주제의 정책을 <b>전부</b> 모아 비교합니다</li>
<li>검색량·기사 수는 '미리 반응했나'를 점검하는 데 다시 씁니다</li></ul></div></div></section>

<section id="trust"><h2>믿을 수 있게 만드는 장치</h2>
<div class="grid3">
<div class="card"><div class="icon">1</div><h3>계획을 먼저 적는다</h3><p class="muted">분석 계획을 커밋하지 않으면 계산 단계가 실행되지 않습니다.</p></div>
<div class="card"><div class="icon">2</div><h3>AI는 돕기만 한다</h3><p class="muted">AI는 주제 찾기와 글쓰기를 돕고, 분석 방법은 규칙이, 숫자는 검증된 라이브러리가 계산합니다.</p></div>
<div class="card"><div class="icon">3</div><h3>작은 표본도 정직하게</h3><p class="muted">정책 지역이 10곳 미만이면 가짜 정책 지역을 수백 번 뽑아 비교하는 방식으로 바꿉니다.</p></div>
<div class="card"><div class="icon">4</div><h3>과장하지 않는다</h3><p class="muted">근거가 부족하면 "입증", "때문에" 같은 말을 리포트에서 자동으로 막습니다.</p></div>
<div class="card"><div class="icon">5</div><h3>출처를 붙인다</h3><p class="muted">모든 데이터셋에 제공 기관, 이용 조건, 확인한 날짜를 적습니다.</p></div>
<div class="card"><div class="icon">6</div><h3>한계를 숨기지 않는다</h3><p class="muted">시뮬레이션, 키 대기, 확인 필요 상태를 배지로 그대로 보여줍니다.</p></div>
</div></section>

"""


# ─── 지금 이슈: 효과 추정 가이드 ───────────────────────────────────────────────
GUIDE_STEPS = [
    (
        "질문을 한 문장으로",
        "'이 정책이 누구의 무엇을 바꿨나'로 씁니다. 예: 토허구역 지정이 그 구의 아파트 거래를 줄였나?",
    ),
    ("비교할 두 집단 정하기", "정책을 받은 곳(처치)과 비슷하지만 안 받은 곳(대조)을 정합니다."),
    ("시작일 확인", "공식 발표·고시로 날짜를 확인합니다. 발표일과 시행일이 다르면 둘 다 적습니다."),
    (
        "데이터 받기",
        "아래 표의 오픈API로 받습니다. 대부분 공공데이터포털에서 자동승인 키를 받으면 됩니다.",
    ),
    (
        "계획 → 실행 → 판정",
        "plan.yaml을 먼저 커밋하고 실행합니다. 결과는 세 가지 판정 중 하나로 나옵니다.",
    ),
]


def issues_page(issues, datasets, topics) -> str:
    by_ds = {d.id: d for d in datasets}
    by_topic = {t.id: t for t in topics}
    guide = "".join(
        f'<div class="card"><span class="n" style="font:700 12px var(--mono);color:var(--accent)">{i + 1:02d}</span>'
        f"<h3>{a}</h3><p class='muted' style='margin:0'>{b}</p></div>"
        for i, (a, b) in enumerate(GUIDE_STEPS)
    )
    designs = "".join(
        f'<div class="card"><h3>{DESIGN_SHORT[k]}</h3><p class="muted" style="margin:0 0 8px">{v}</p>'
        f'<span class="badge {SUPPORT[k][1]}">{SUPPORT[k][0]}</span></div>'
        for k, v in DESIGN_PLAIN.items()
    )
    toc = "".join(f'<li><a href="#{i.id}">{e(i.name)}</a></li>' for i in issues)
    sections = []
    for i in issues:
        ds = [by_ds[x] for x in i.datasets if x in by_ds]
        t = by_topic[i.topic]
        sup, cls = SUPPORT[i.design]
        note = f" <span class='muted'>({e(i.effective_note)})</span>" if i.effective_note else ""
        pits = "".join(f"<li>{e(p)}</li>" for p in i.pitfalls)
        sections.append(
            f'<div class="issue" id="{i.id}"><a class="crumb" href="topics/{t.id}.html">{e(t.name)}</a><h2>{e(i.name)}</h2>'
            f'<p class="lede" style="font-size:17px">{e(i.issue)}</p>'
            f'<dl class="kv"><dt>시작일</dt><dd>{e(i.effective)}{note} · <a href="{e(i.source)}">공식 출처</a></dd>'
            f"<dt>정책 받은 곳</dt><dd>{e(i.treatment)}</dd>"
            f"<dt>비교할 곳</dt><dd>{e(i.control)}</dd>"
            f"<dt>무엇을 재나</dt><dd>{e(', '.join(i.outcomes))}</dd>"
            f"<dt>분석 방법</dt><dd><b>{DESIGN_SHORT[i.design]}</b> — {DESIGN_PLAIN[i.design]} "
            f'<span class="badge {cls}">{sup}</span></dd>'
            f"<dt>난이도</dt><dd>{dots(i.difficulty)}</dd></dl>"
            f"<h3>받을 수 있는 데이터</h3>{dataset_table(ds)}"
            f"<h3 style='margin-top:16px'>조심할 점</h3><ul>{pits}</ul>"
            f'<p class="muted"><a href="topics/{t.id}.html">{e(t.name)} 주제 전체 보기 →</a></p></div>'
        )
    body = f"""
<div class="hero" style="padding-bottom:0">
<h1>논쟁 중인 정책, 이렇게 분석합니다</h1>
<p class="lede">2025~2026년에 논쟁이 된 정책 {len(issues)}개를 골라, 누구와 누구를 비교할지, 어떤 방법을 쓸지,
어떤 데이터를 받을 수 있는지 정리했습니다. 시작일은 모두 정부 공식 자료에서 확인했습니다.</p></div>
<div class="banner info" style="margin-top:20px">분석은 이슈 하나가 아니라 그 이슈가 속한 <b>주제 전체</b>로 합니다.
이 목록은 멘티가 어디서부터 볼지 정하는 출발점입니다.</div>
<section style="padding-top:28px"><h2>효과 추정 5단계</h2><div class="grid3" style="margin-top:12px">{guide}</div></section>
<section><h2>분석 방법 고르기</h2><p class="sub">방법은 데이터 모양을 보고 규칙이 정합니다. 결과를 본 뒤 사람이나 AI가 고르지 않습니다.</p>
<div class="grid">{designs}</div></section>
<section><h2>정책별 가이드</h2><ol>{toc}</ol>{"".join(sections)}</section>"""
    return page("지금 이슈 · 정책 효과 분석 플랫폼", body, "issues.html")


# ─── 데이터 지도 (온톨로지) ─────────────────────────────────────────────────────
DATA_JS = """
const rows=[...document.querySelectorAll('#dtable tbody tr')];
const els={q:document.getElementById('dq'),role:document.getElementById('frole'),topic:document.getElementById('ftopic'),
  space:document.getElementById('fspace'),access:document.getElementById('faccess')};
function apply(){
  const q=els.q.value.trim().toLowerCase();let n=0;
  rows.forEach(r=>{const ok=(!q||r.dataset.text.includes(q))&&(!els.role.value||r.dataset.roles.split(' ').includes(els.role.value))
    &&(!els.topic.value||r.dataset.topics.split(' ').includes(els.topic.value))&&(!els.space.value||r.dataset.space===els.space.value)
    &&(!els.access.value||r.dataset.access===els.access.value);r.hidden=!ok;if(ok)n++;});
  document.getElementById('dcount').textContent=n;
}
Object.values(els).forEach(x=>x.addEventListener('input',apply));
document.getElementById('goportal').onsubmit=ev=>{ev.preventDefault();
  const k=document.getElementById('pq').value.trim();
  if(k)window.open('https://www.data.go.kr/tcs/dss/selectDataSetList.do?keyword='+encodeURIComponent(k),'_blank','noopener');};
"""
PORTALS = [
    (
        "공공데이터포털",
        "https://www.data.go.kr",
        "부처·지자체 데이터 대부분. 오픈API는 활용신청 후 자동승인 키로 받습니다.",
    ),
    (
        "KOSIS 국가통계포털",
        "https://kosis.kr",
        "인구·출생·경제 통계. 통계표 ID로 오픈API를 부릅니다.",
    ),
    (
        "서울 열린데이터광장",
        "https://data.seoul.go.kr",
        "서울 자치구·역·측정소 단위 자료가 많습니다.",
    ),
    (
        "법제처 국가법령정보",
        "https://open.law.go.kr",
        "조례의 지역·시행일 → '누가 언제 정책을 받았나'.",
    ),
    ("한국부동산원 R-ONE", "https://www.reb.or.kr/r-one/", "주택 가격지수 등 부동산 통계."),
]


def _options(pairs) -> str:
    return "".join(f'<option value="{v}">{e(k)}</option>' for v, k in pairs)


def data_page(datasets, topics, issues) -> str:
    tname = {t.id: t.name for t in topics}
    n_role = {r: sum(r in d.roles for d in datasets) for r in ROLE_KO}
    spaces = sorted({d.space for d in datasets})
    rows = []
    for d in datasets:
        text = " ".join([d.name, d.provider, *d.measures]).lower()
        meas = (
            f"<div class='muted small'>{e(', '.join(d.measures[:5]))}</div>" if d.measures else ""
        )
        rows.append(
            f'<tr data-roles="{" ".join(d.roles)}" data-topics="{" ".join(d.topics)}" data-space="{e(d.space)}" '
            f'data-access="{d.access}" data-text="{e(text)}">'
            f"<td><a href='{e(d.url)}'>{e(d.name)}</a><div class='muted small'>{e(d.provider)} · {PORTAL_KO.get(d.portal, d.portal)}</div>{meas}</td>"
            f"<td>{role_badges(d.roles)}</td>"
            f"<td>{e(d.space)} × {e(d.time)}<div class='muted small'>{e(d.period)}</div></td>"
            f"<td>{ACCESS_KO[d.access]}<div class='muted small'>{e(d.approval)}</div></td>"
            f"<td>{e(d.license)}</td>"
            f"<td class='small'>{' · '.join(e(tname.get(t, t)) for t in d.topics)}</td>"
            f"<td class='muted small' title='{e(d.verified)}'>{e(d.verified[:10])}</td></tr>"
        )
    portals = "".join(
        f'<div class="card"><h3><a href="{u}">{n}</a></h3><p class="muted" style="margin:0">{d}</p></div>'
        for n, u, d in PORTALS
    )
    terms = "".join(f"<div><dt>{a}</dt><dd>{b}</dd></div>" for a, b in TERMS)
    body = f"""
<div class="hero" style="padding-bottom:0">
<h1>재료부터 챙겨 볼까요</h1>
<p class="lede">정책 효과를 재는 데 필요한 재료는 세 가지예요. <b>누가 언제 정책을 받았는지</b>, <b>무엇이 달라졌는지</b>,
<b>결과를 흔드는 다른 요인</b>. 주제별로 받을 수 있는 공공데이터 {len(datasets)}개를 이 기준으로 정리했어요.</p></div>

<section style="padding-top:32px"><h2>데이터를 이렇게 연결합니다</h2>
<p class="sub">주제 → 이슈 → 데이터셋 → 제공 포털로 이어지고, 데이터셋마다 역할·단위·받는 법이 붙습니다.</p>
<div class="onto">
<div class="card"><span class="rel">주제</span><h3>무엇을 보나</h3><ul><li>{len(topics)}개 주제</li><li>세 가지 확인 사항</li></ul></div>
<div class="card"><span class="rel">이슈 → 주제에 속함</span><h3>지금 논쟁 중인 정책</h3><ul><li>{len(issues)}개 이슈</li><li>시작일 + 공식 출처</li></ul></div>
<div class="card"><span class="rel">데이터셋 → 이슈에 쓰임</span><h3>역할이 있는 데이터</h3><ul>
<li><span class="badge r-treatment">처치</span> 누가 언제 · {n_role["treatment"]}개</li>
<li><span class="badge r-outcome">결과</span> 무엇이 변했나 · {n_role["outcome"]}개</li>
<li><span class="badge r-covariate">통제</span> 다른 요인 · {n_role["covariate"]}개</li></ul></div>
<div class="card"><span class="rel">포털 → 데이터셋을 제공</span><h3>어디서 받나</h3><ul><li>공간 × 시간 단위</li><li>오픈API·파일, 승인 방식</li><li>이용 조건</li></ul></div>
</div></section>

<section><h2>데이터셋 찾기</h2>
<div class="search"><input id="dq" type="search" placeholder="이름·기관·측정 항목으로 찾기 (예: 실거래, 교통사고, 출생)"></div>
<div class="filters">
<select id="frole" aria-label="역할"><option value="">모든 역할</option>{_options(ROLE_KO.items())}</select>
<select id="ftopic" aria-label="주제"><option value="">모든 주제</option>{_options((t.id, t.name) for t in topics)}</select>
<select id="fspace" aria-label="공간 단위"><option value="">모든 공간 단위</option>{_options((s, s) for s in spaces)}</select>
<select id="faccess" aria-label="받는 법"><option value="">모든 방식</option>{_options(ACCESS_KO.items())}</select>
<span class="muted"><b id="dcount">{len(datasets)}</b>개</span></div>
<div class="tablewrap"><table id="dtable"><thead><tr><th>데이터셋</th><th>역할</th><th>단위</th><th>받는 법</th><th>이용 조건</th><th>주제</th><th>확인</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>
<p class="muted">이용 조건이 <code>other</code>인 것은 포털에 공공누리 유형 없이 "이용허락범위 제한 없음"으로만 적힌 경우입니다.
<code>KOGL-3</code>(변경금지)은 가공한 데이터를 다시 배포할 때 주의하세요.</p></section>

<section><h2>여기에 없는 데이터 찾기</h2>
<form id="goportal" class="search" style="display:flex;gap:8px"><input id="pq" type="search" placeholder="공공데이터포털에서 검색 (새 창)" style="flex:1">
<button class="btn primary" type="submit" style="border:0;cursor:pointer">검색</button></form>
<p class="muted">찾은 데이터는 <code>catalog/datasets.yaml</code>에 역할·단위·받는 법을 적어 PR로 추가해 주세요.</p>
<div class="grid" style="margin-top:14px">{portals}</div></section>

<section><h2>용어 풀이</h2><dl class="terms">{terms}</dl></section>
<script>{DATA_JS}</script>"""
    return page("데이터 지도 · 정책 효과 분석 플랫폼", body, "data.html")


# ─── 주제 페이지 ──────────────────────────────────────────────────────────────
def legal_frame(t) -> pd.DataFrame | None:
    """법제처에서 모은 주제의 법령·행정규칙·자치법규 스냅샷 (scripts/refresh_legal.py)."""
    path = ROOT / "catalog" / "snapshots" / f"legal_{t.id}.csv"
    if not t.legal or not path.exists():
        return None
    return pd.read_csv(path, dtype=str).fillna("")


def legal_core(t, df: pd.DataFrame) -> pd.DataFrame:
    """핵심만: 근거 법률 자체의 개정 + 행정규칙 지정·해제 이력. 체계도로 넓게 딸려 온 것은 뺀다."""
    laws = set(t.legal.laws)
    core = df[(df["relation"] == "이력") | ((df["relation"] == "연혁") & df["name"].isin(laws))]
    return core.sort_values("announced", ascending=False)


def legal_stale(fetched: str, today: str | None = None, days: int = 14) -> str:
    """법령 스냅샷이 오래됐으면 경고 한 줄. 자동 갱신(LAW_OC)이 켜지면 저절로 사라진다."""
    if not fetched:
        return ""
    try:
        age = (pd.Timestamp(today or pd.Timestamp.today().date()) - pd.Timestamp(fetched)).days
    except (ValueError, TypeError):
        return ""
    if age <= days:
        return ""
    return (
        f"<div class='banner warn'>이 법령 목록은 <b>{e(fetched)}</b> 이후 {age}일째 갱신되지 않았습니다. "
        "그 뒤의 개정·지정·해제는 빠져 있을 수 있으니 처치 시점을 정하기 전에 "
        "<a href='https://www.law.go.kr'>국가법령정보센터</a>에서 확인하세요.</div>"
    )


def legal_block(t) -> str:
    if not t.legal or not (t.legal.laws or t.legal.admin_rules):
        note = f"<p class='muted'>{e(t.legal.note)}</p>" if t.legal and t.legal.note else ""
        return f"<h3 style='margin-top:22px'>관련 법령</h3>{note}" if note else ""
    df = legal_frame(t)
    seeds = " · ".join(e(x) for x in t.legal.laws + t.legal.admin_rules)
    head = (
        "<h3 style='margin-top:22px'>관련 법령 · 행정규칙 (법제처 자동 수집)</h3>"
        f"<p class='muted'>출발점: {seeds}. 여기서 연혁·체계도·지정/해제 이력을 따라가 전부 모읍니다.</p>"
    )
    if df is None:
        return head + (
            "<p class='card'>법제처 인증값이 레포에 등록되면 다음 갱신 때 채워집니다.</p>"
        )
    cnt = df["group"].value_counts()
    src = ROOT / "catalog" / "snapshots" / f"legal_{t.id}.source.json"
    fetched = json.loads(src.read_text(encoding="utf-8")).get("fetched", "") if src.exists() else ""
    stale = legal_stale(fetched)
    core = legal_core(t, df).head(12)
    today = pd.Timestamp.today().strftime("%Y-%m-%d")
    rows = "".join(
        f"<tr><td>{e(r.announced)}</td><td>{e(r.kind)}</td><td><a href='{e(r.url)}'>{e(r.name)}</a></td>"
        f"<td>{e(r.change)}"
        + (" <span class='badge warn'>시행 예정</span>" if r.effective > today else "")
        + f"</td><td>{e(r.effective)}</td></tr>"
        for r in core.itertuples()
    )
    wide = df[df["relation"] == "체계도"]["group"].value_counts()
    csv = f"{REPO}/blob/main/catalog/snapshots/legal_{t.id}.csv"
    note = f"<p class='muted small'>{e(t.legal.note)}</p>" if t.legal.note else ""
    return (
        head
        + stale
        + '<div class="stats" style="margin-top:8px">'
        + "".join(
            f'<div class="stat"><div class="v">{cnt.get(g, 0)}</div><div class="l">{lab}</div></div>'
            for g, lab in (
                ("법령", "법령 개정 이력"),
                ("행정규칙", "행정규칙"),
                ("자치법규", "자치법규(조례 등)"),
            )
        )
        + "</div>"
        + "<p style='margin:14px 0 6px'><b>최근 바뀐 핵심</b> — 근거 법률 개정과 지정·해제 공고</p>"
        + f"<div class='tablewrap'><table><tr><th>공포·발령</th><th>종류</th><th>이름</th><th>변경</th><th>시행</th></tr>{rows}</table></div>"
        + f"<p class='muted small'>체계도로 연결된 하위 규정 {len(df[df['relation'] == '체계도'])}건"
        + (
            f" (행정규칙 {wide.get('행정규칙', 0)} · 자치법규 {wide.get('자치법규', 0)})"
            if len(wide)
            else ""
        )
        + f"까지 전체 목록: <a href='{csv}'>legal_{t.id}.csv</a> · {e(fetched)} 기준 · 출처: 법제처 국가법령정보센터</p>"
        + note
        + "<p class='muted small'>법령 개정이 곧 처치 시점은 아닙니다. 시행일·대상을 확인해 사람이 <code>events</code>에 옮깁니다.</p>"
    )


def topic_page(t, policies, issues, datasets, projects=(), answers=(), lineages=()) -> str:
    """이슈 보드: 이슈 → 공공데이터 → 계보 → 분석 → 대시보드 순서로 한 장에."""
    import answers as ans
    import board
    import projects as proj

    by_id = {p.id: p for p in policies}
    ps = [by_id[i] for i in t.policies]
    _, lab, cls = readiness(t)
    my_issues = [i for i in issues if i.topic == t.id]
    my_ds = [d for d in datasets if t.id in d.topics]
    my_lin = [lin for lin in lineages if lin.topic == t.id]
    mine = [a for a in answers if a["topic"] == t.id]
    st = board.topic_stages(t, issues, datasets, lineages, answers)
    tb = {t.id: t}
    body = [
        f"<div class='hero board-hero'><nav class='crumb' aria-label='위치'><a href='../index.html#topics'>이슈 보드</a></nav>"
        f"<h1>{e(t.name)}</h1><p class='lede'>{e(t.question)}</p></div>",
        board.rail(e, st),
    ]
    # 1. 이슈
    body.append(f"<section id='s-issue' class='stage'>{board.stage_head(e, 'issue')}")
    if my_issues:
        items = "".join(
            f'<a class="issue-row" href="../issues.html#{i.id}"><span class="when">{e(i.effective)}</span>'
            f"<b>{e(i.name)}</b><span class='q'>{e(i.issue)}</span></a>"
            for i in my_issues
        )
        body.append(f"<div class='rows'>{items}</div>")
    body.append(
        f"<h3>이 주제의 정책 시점</h3><p class='muted small'>모으는 방법: {COLLECT_KO[t.collect.method]} — {e(t.collect.note)}</p>"
    )
    body.append(timeline_svg(t.events))
    snap = ROOT / "catalog" / "snapshots" / f"law_{t.id}.csv"
    if t.collect.method == "law_ordinance":
        if snap.exists():
            df = pd.read_csv(snap)
            cnt = df.dropna(subset=["year"]).astype({"year": int}).groupby("year").size()
            body += [
                f"<h3>조례 시행 연도 (법제처, {len(df)}건)</h3>",
                bars_svg(cnt, "조례 시행 연도"),
                "<p class='muted'>현재 조례의 시행일 기준입니다. 처음 만든 날은 조례 연혁에서 확인합니다.</p>",
            ]
        else:
            body.append(
                "<p class='card'>법제처 API로 지역별 조례와 시행일을 자동으로 모을 주제입니다. "
                "법제처 인증값이 레포에 등록되면 다음 갱신 때 채워집니다.</p>"
            )
    body.append(
        "<details class='more-box'><summary>관련 법령·행정규칙 보기</summary>"
        + legal_block(t)
        + "</details>"
    )
    gates = "".join(
        f'<div><dt>{GATE_Q[k]}</dt><dd><span class="badge {GATE_CLASS[g.status]}">{GATE_STATUS_KO[g.status]}</span> {e(g.note)}</dd></div>'
        for k, g in t.gates.items()
    )
    body.append(
        f"<h3>분석 전에 확인할 세 가지 <span class='badge {cls}'>{lab}</span></h3><dl class='legend'>{gates}</dl></section>"
    )
    # 2. 공공데이터
    body.append(f"<section id='s-data' class='stage'>{board.stage_head(e, 'data')}")
    if my_ds:
        order = ["treatment", "outcome", "covariate"]
        body.append(
            board.access_summary(e, my_ds)
            + dataset_table(sorted(my_ds, key=lambda d: order.index(d.roles[0])))
            + "<p class='small muted'>역할: 처치(누가 언제 정책을 받았나) · 결과(무엇이 변했나) · 통제(다른 요인). 전체 목록은 <a href='../data.html'>데이터</a>에 있습니다.</p>"
        )
    else:
        body.append(
            f"<p class='empty'>아직 빈칸이에요. 첫 데이터를 찾아 줄래요? <a href='{REPO}/blob/main/docs/tracks/ontology.md'>데이터 찾기 안내(트랙 A)</a></p>"
        )
    body.append("</section>")
    # 3. 계보
    body.append(f"<section id='s-lineage' class='stage'>{board.stage_head(e, 'lineage')}")
    if my_lin:
        names = {}
        ds_name = {d.id: d.name for d in datasets}
        iss_name = {i.id: i.name for i in issues}
        verdicts = {a["case"]: a["verdict"] for a in answers}
        for lin in my_lin:
            for s in lin.steps:
                if s.kind == "issue":
                    names[s.id] = iss_name.get(s.ref, s.ref or s.title)
                elif s.kind == "dataset" and s.ref:
                    names[s.id] = ds_name.get(s.ref, s.ref)
            body.append(
                f"<h3>{e(lin.title)}</h3>"
                + board.lineage_svg(e, lin, names, verdicts, up="../")
                + f"<p class='small muted'>점선은 계획이거나 아직 없는 데이터(빈칸)입니다. 마우스를 올리면 설명이 보입니다. "
                f"<a href='../lineage.html#{e(lin.id)}'>단계별 설명</a> · <a href='{REPO}/blob/main/catalog/lineage/{e(lin.id)}.yaml'>YAML</a></p>"
            )
    else:
        body.append(
            f"<p class='empty'>아직 실이 안 이어졌어요. 이슈에서 지표까지 어떤 데이터를 어떻게 가공하는지 "
            f"<a href='{REPO}/blob/main/catalog/lineage/_template.yaml'>계보 템플릿</a>으로 그려 주세요.</p>"
        )
    body.append("</section>")
    # 4. 분석
    body.append(f"<section id='s-analysis' class='stage'>{board.stage_head(e, 'analysis')}")
    if mine:
        body.append(
            f'<div class="answers">{"".join(ans.card(e, a, tb, up="../") for a in mine)}</div>'
        )
        outs = "".join(f"<li>{e(ans.rule_out(a))}</li>" for a in mine if ans.rule_out(a))
        if outs:
            body.append(f"<h3>그래도 말할 수 있는 것</h3><ul class='said'>{outs}</ul>")
    else:
        body.append(
            f"<p class='empty'>아직 아무도 비교해 보지 않았어요. 첫 번째 시민 데이터 과학자가 되어 볼래요? <a class='btn primary' href='../index.html#ask'>이 주제로 질문하기</a> "
            f"<a class='btn ghost' href='{REPO}/issues/new?template=case-proposal.yml' data-track='propose-case'>분석 제안하기</a></p>"
        )
    pmine = [p for p in proj.by_topic(list(projects), t.id) if not p["stages"][2]]
    if pmine:
        body.append(
            "<h3>진행 중인 분석</h3><div class='grid proj-grid'>"
            + "".join(proj.project_card(e, p, tb, up="../") for p in pmine)
            + "</div>"
        )
    if ps:
        cards = []
        for p in ps:
            sup, scls = SUPPORT[p.design]
            pits = (
                "<details><summary>조심할 점</summary><ul>"
                + "".join(f"<li>{e(x)}</li>" for x in p.pitfalls)
                + "</ul></details>"
                if p.pitfalls
                else ""
            )
            cards.append(
                f'<div class="card"><h3>{e(p.name)}</h3><p class="muted">{e(p.summary)}</p>'
                f"<p><b>{DESIGN_SHORT[p.design]}</b> — {DESIGN_PLAIN[p.design]} "
                f'<span class="badge {scls}">{sup}</span></p>{pits}</div>'
            )
        body.append(
            "<details class='more-box'><summary>이 주제의 분석 설계 보기</summary><div class='grid'>"
            + "".join(cards)
            + "</div></details>"
        )
    body.append("</section>")
    # 5. 대시보드
    body.append(f"<section id='s-dashboard' class='stage'>{board.stage_head(e, 'dashboard')}")
    body.append(board.kpis(e, mine, len(my_ds), board.ready_count(my_ds)))
    charts = [board.event_chart(e, a) for a in mine]
    charts = [c for c in charts if c]
    if charts:
        body.append(
            "<div class='es-grid'>"
            + "".join(
                f"<div class='es-item'>{c}<p class='small'><a href='../{e(a['page'])}'>{e(a['title'])}</a></p></div>"
                for a, c in zip([a for a in mine if board.chart_result(a)], charts, strict=True)
            )
            + "</div><p class='small muted'>점은 시점별 차이, 세로선은 95% 구간, 회색 바탕은 정책 시작 뒤입니다. 시작 전 점들이 0 근처에 모여 있어야 비교가 믿을 만합니다.</p>"
        )
    else:
        body.append(
            "<p class='empty'>분석 결과가 나오면 여기에 시점별 효과 그림이 저절로 그려져요.</p>"
        )
    if t.pitfalls:
        items = "".join(f"<li>{e(x)}</li>" for x in t.pitfalls)
        body.append(f"<h3>이 주제에서 조심할 점</h3><ul>{items}</ul>")
    body.append("</section><script src='../board.js' defer></script>")
    return page(
        f"{t.name} · 정책 효과 분석 플랫폼",
        "\n".join(body),
        "index.html#topics",
        depth=1,
        desc=t.question,
        path=f"topics/{t.id}.html",
    )


# ─── 빌드 ────────────────────────────────────────────────────────────────────
def main() -> None:
    import architecture
    import projects as proj

    topics, policies = load_topics(), load_catalog()
    issues, datasets = load_issues(), load_datasets()
    projects = proj.load_projects()
    import answers as ans

    answers = ans.load_answers()
    proj.attach_next_steps(projects, answers)
    from core.discovery.lineage import load_lineages

    lineages = load_lineages()
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "topics").mkdir(parents=True)
    pages = {
        "index.html": index_page(topics, policies, issues, datasets, projects, answers, lineages),
        "issues.html": issues_page(issues, datasets, topics),
        "data.html": data_page(datasets, topics, issues),
        "architecture.html": page(
            "구조 · 정책 효과 분석 플랫폼",
            architecture.body(e) + how_sections(),
            "architecture.html",
        ),
    }
    for name, text in pages.items():
        (OUT / name).write_text(text, encoding="utf-8")
    for t in topics:
        (OUT / "topics" / f"{t.id}.html").write_text(
            topic_page(t, policies, issues, datasets, projects, answers, lineages),
            encoding="utf-8",
        )
    # 트랙 A·C: 공개 API, 데이터 계보, 서비스
    import api
    import tracks

    index = api.write_api(OUT, topics, issues, datasets, legal_summary)
    results = json.loads((OUT / "api" / "results.json").read_text(encoding="utf-8"))
    apps = api.copy_apps(OUT)
    (OUT / "lineage.html").write_text(
        page(
            "데이터 계보 · 정책 효과 분석 플랫폼",
            tracks.lineage_body(e, topics, issues, datasets, load_lineages(), results),
            "lineage.html",
        ),
        encoding="utf-8",
    )
    # 분석 결과: 목록 + 케이스별 답 페이지 (그림은 write_api 가 _site/cases/ 로 복사해 둠)
    (OUT / "results.html").write_text(
        page(
            "분석 결과 · 정책 효과 분석 플랫폼",
            ans.index_body(e, answers, topics),
            "results.html",
            desc="공공데이터로 정책을 받은 곳과 안 받은 곳을 비교한 결과 — 쉬운 말 답, 인용 문장, 쓴 데이터, 재현 방법",
            path="results.html",
        ),
        encoding="utf-8",
    )
    (OUT / "answers").mkdir(exist_ok=True)
    tb = {t.id: t for t in topics}
    ds_by_url = {d.url: d for d in datasets}
    for a in answers:
        fig = next((f for f in ("event_study.png", *a["figures"]) if f in a["figures"]), None)
        (OUT / a["page"]).write_text(
            page(
                f"{a['title']} · 분석 결과",
                ans.page_body(e, a, tb, ds_by_url),
                "results.html",
                depth=1,
                desc=ans.share_text(a),
                path=a["page"],
                image=f"cases/{a['case']}/{fig}" if fig else None,
            ),
            encoding="utf-8",
        )
    ans.write_csv(OUT, results)
    (OUT / "projects.html").write_text(
        page(
            "참여자 프로젝트 · 정책 효과 분석 플랫폼",
            proj.projects_body(e, projects, load_lineages(), topics),
            "projects.html",
        ),
        encoding="utf-8",
    )
    (OUT / "apps.html").write_text(
        page("서비스 · 정책 효과 분석 플랫폼", tracks.apps_body(e, apps, index), "apps.html"),
        encoding="utf-8",
    )
    shutil.copy(HERE / "ask.js", OUT / "ask.js")
    shutil.copy(HERE / "track.js", OUT / "track.js")
    shutil.copy(HERE / "board.js", OUT / "board.js")
    # 성과: data/cache/metrics.json(Actions) + 레포 파일 → impact.html · api/metrics.json
    import board
    import impact

    legal_dates = [
        json.loads(f.read_text(encoding="utf-8")).get("fetched", "")
        for f in (ROOT / "catalog" / "snapshots").glob("legal_*.source.json")
    ]
    sup = board.supply(topics, issues, datasets, lineages, answers, max(legal_dates, default=""))
    kpi = impact.compute(impact.load(), answers, projects, sup)
    (OUT / "api" / "metrics.json").write_text(
        json.dumps(kpi, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (OUT / "impact.html").write_text(
        page(
            "성과 · 정책 효과 분석 플랫폼",
            impact.body(e, kpi),
            "impact.html",
            desc="이 사이트가 목표대로 쓰이는지: 쓰임 · 외부 검증 · 결과의 질 · 참여",
            path="impact.html",
        ),
        encoding="utf-8",
    )
    (OUT / ".nojekyll").write_text("")
    print(f"_site/ 생성: 주제 {len(topics)} · 이슈 {len(issues)} · 데이터셋 {len(datasets)}")


if __name__ == "__main__":
    main()
