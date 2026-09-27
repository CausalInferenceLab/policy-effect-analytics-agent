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
import yaml

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from core.agent.guard import TRIGGER_KO  # noqa: E402
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
CSS = (HERE / "style.css").read_text(encoding="utf-8")

GATE_Q = {"when": "언제 시작했나", "who": "누가 받았나", "what": "무엇으로 재나"}
GATE_CLASS = {"pass": "go", "check": "warn", "key": "warn", "fail": "stop"}
VERDICT = {
    "identified": ("효과 근거 있음", "go"),
    "conditional": ("조건부", "warn"),
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
    ("index.html", "홈"),
    ("issues.html", "지금 이슈"),
    ("index.html#topics", "주제"),
    ("data.html", "데이터 지도"),
    ("architecture.html", "구조"),
    ("index.html#join", "참여하기"),
]
TERMS = [
    (
        "처치 · 대조",
        "정책을 받은 쪽이 처치, 받지 않은 쪽이 대조입니다. 대조는 '정책이 없었다면'을 대신 보여줍니다.",
    ),
    (
        "이중차분",
        "정책 지역의 전후 변화에서 대조 지역의 전후 변화를 뺍니다. 경기·계절처럼 둘 다 겪은 변화가 지워집니다.",
    ),
    (
        "평행 추세",
        "정책 전에 두 집단이 나란히 움직였어야 이중차분이 성립합니다. 가장 먼저 확인합니다.",
    ),
    (
        "사전 등록",
        "데이터를 보기 전에 무엇을 어떻게 볼지 plan.yaml에 적어 커밋합니다. 결과를 보고 말을 바꾸지 않기 위해서입니다.",
    ),
    (
        "무작위화 추론",
        "정책 지역이 몇 곳뿐일 때, 가짜 정책 지역을 수백 번 뽑아 비교해 우연인지 판단합니다.",
    ),
    ("판정", "효과 근거 있음 · 조건부 · 판단 불가 세 가지입니다. 판단 불가도 정직한 결과입니다."),
]

e = html.escape


# ─── 공통 ──────────────────────────────────────────────────────────────────────
def page(title: str, body: str, current: str, depth: int = 0) -> str:
    up = "../" * depth
    links = "".join(
        f'<a href="{up}{href}"{" aria-current=page" if href == current else ""}>{label}</a>'
        for href, label in NAV
    )
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>
<meta name="description" content="뉴스와 SNS에서 궁금해하는 정책이 정말 효과가 있었는지 공공데이터로 확인하는 오픈소스">
<style>{CSS}</style></head><body>
<nav class="nav"><div class="in"><b><a href="{up}index.html">정책 효과 분석 플랫폼</a></b>
<span class="links">{links}<a href="{REPO}">GitHub ↗</a></span></div></nav>
<div class="wrap">{body}
<footer>가짜연구소 인과추론팀 × 오픈업 오픈소스 AI 특화형 트랙3 · 이 사이트의 숫자와 판정은 레포의 <code>catalog/</code>·<code>cases/</code>에서
자동으로 만들어집니다(매주 월요일 갱신). 시뮬레이션 결과에는 따로 표시가 붙습니다. · <a href="{REPO}">소스 코드 (MIT)</a></footer>
</div></body></html>"""


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


def case_logs(t, policies) -> list[str]:
    by_id = {p.id: p for p in policies}
    return [
        by_id[i].sample_case
        for i in t.policies
        if by_id[i].sample_case and (ROOT / by_id[i].sample_case / "flow_log.json").exists()
    ]


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
def case_block(case_rel: str, depth: int) -> str:
    case = ROOT / case_rel
    log = json.loads((case / "flow_log.json").read_text(encoding="utf-8"))
    plan = yaml.safe_load((case / "plan.yaml").read_text(encoding="utf-8"))
    dest = OUT / "cases" / case.name
    dest.mkdir(parents=True, exist_ok=True)
    figs = []
    for f in sorted((case / "figures").glob("*.png")):
        shutil.copy(f, dest / f.name)
        figs.append(f'<img src="{"../" * depth}cases/{case.name}/{f.name}" alt="{e(f.stem)}">')
    label, cls = VERDICT.get(log.get("verdict"), ("-", "warn"))
    out = []
    if plan.get("synthetic_data"):
        out.append(
            '<div class="banner stop">시뮬레이션 데이터 결과입니다. 실제 정책 효과가 아닙니다. '
            "분석 과정을 보여주기 위한 예시이며, 데이터 키를 받으면 실제 데이터로 바꿉니다.</div>"
        )
    out.append(f"<p><b>질문</b> {e(plan['question'].strip())}</p>")
    out.append(f'<p>종합 판정 <span class="badge {cls}">{label}</span></p>')
    names = {o["col"]: o["name"] for o in plan["outcomes"]}
    rows = "".join(
        f"<tr><td>{e(names.get(r['outcome'], r['outcome']))}</td><td>{r['estimate']:+.3f}</td>"
        f"<td>{r['ci_low']:.3f} ~ {r['ci_high']:.3f}</td>"
        f'<td><span class="badge {VERDICT[r["verdict"]][1]}">{VERDICT[r["verdict"]][0]}</span></td>'
        f"<td class='muted'>{e(', '.join(TRIGGER_KO.get(x, x) for x in r.get('triggers') or []) or '-')}</td></tr>"
        for r in log["results"]
    )
    out.append(
        "<div class='tablewrap'><table><tr><th>결과 지표</th><th>추정 효과</th><th>95% 범위</th><th>판정</th><th>주의</th></tr>"
        f"{rows}</table></div>"
    )
    narr = (log.get("guard") or {}).get("narrative")
    if narr:
        out.append(f'<p class="card" style="margin-top:12px">{e(narr).replace("**", "")}</p>')
    if figs:
        out.append(f'<div class="figs" style="margin-top:12px">{"".join(figs)}</div>')
    out.append(
        f'<p class="muted">분석 계획·코드·리포트: <a href="{REPO}/tree/main/{case_rel}">{case_rel}</a></p>'
    )
    return "\n".join(out)


# ─── 홈 ──────────────────────────────────────────────────────────────────────
HOME_JS = """
const KW=__KW__;
const norm=s=>s.replace(/\\s+/g,'').toLowerCase();
const q=document.getElementById('q'),ans=document.getElementById('ans');
function match(){
  const t=norm(q.value);let best=null,bs=0,hits=[];
  for(const [id,ks] of Object.entries(KW)){const h=ks.filter(k=>t.includes(norm(k)));
    const s=h.reduce((a,k)=>a+Math.min(norm(k).length,6),0);if(s>bs){bs=s;best=id;hits=h;}}
  document.querySelectorAll('#cards .topic').forEach(c=>c.classList.toggle('hit',c.dataset.topic===best));
  if(!t){ans.textContent='입력한 글은 이 브라우저 안에서만 쓰이고, 어디에도 보내지 않습니다.';return;}
  if(!best){ans.textContent='맞는 주제를 찾지 못했습니다. 정책 이름이나 지역을 넣어 보세요.';return;}
  const c=document.querySelector(`#cards [data-topic="${best}"]`);
  ans.innerHTML=`→ <a href="${c.getAttribute('href')}"><b>${c.querySelector('h3').textContent}</b></a> 주제입니다. 이 주제의 정책을 모두 모아서 봅니다. (찾은 말: ${hits.join(', ')})`;
}
q.addEventListener('input',match);
document.querySelectorAll('.ex').forEach(b=>b.onclick=()=>{q.value=b.textContent;match();});
document.querySelectorAll('.f').forEach(b=>b.onclick=()=>{
  document.querySelectorAll('.f').forEach(x=>x.setAttribute('aria-pressed',x===b));const f=b.dataset.f;
  document.querySelectorAll('#cards .topic').forEach(c=>c.hidden=!(f==='all'||(f==='result'?c.dataset.result==='1':f==='issue'?c.dataset.issue==='1':c.dataset.ready===f)));});
document.querySelectorAll('.v').forEach(b=>b.onclick=()=>{
  document.querySelectorAll('.v').forEach(x=>x.setAttribute('aria-pressed',x===b));
  document.getElementById('cards').className=b.dataset.v==='list'?'list':'grid';});
"""

HOME_STEPS = [
    ("찾기", "뉴스·SNS에서 사람들이 궁금해하는 <b>주제</b>를 찾습니다", "누구나"),
    ("모으기", "그 주제의 정책을 <b>전부</b> 모읍니다. 어느 지역이 언제 시작했는지", "수집 담당"),
    (
        "거르기",
        "세 가지를 확인합니다. 언제 시작했나 · 누가 받았나 · 무엇으로 재나",
        "문제 정의 담당",
    ),
    ("계획하기", "데이터를 보기 전에 분석 계획을 먼저 적어 둡니다", "문제 정의 담당"),
    ("비교하기", "정책을 받은 곳과 안 받은 곳의 변화를 비교합니다", "추정 담당"),
    ("말하기", "효과 근거 있음 · 조건부 · 판단 불가 중 하나로 정직하게 씁니다", "리포트 담당"),
]
HOME_EXAMPLES = [
    "토허제 확대하고 강남 집값 잡혔나요?",
    "소비쿠폰 받고 동네 가게 매출 늘었나?",
    "모두의 카드 나오고 지하철 더 타나?",
    "5030 속도 줄이고 사고 줄었나?",
]


def index_page(topics, policies, issues, datasets) -> str:
    kw = {
        t.id: list(
            dict.fromkeys(
                t.keywords
                + [k for pid in t.policies for p in policies if p.id == pid for k in p.keywords]
            )
        )
        for t in topics
    }
    issue_topics = {i.topic for i in issues}
    cards = []
    for t in topics:
        key, lab, cls = readiness(t)
        res = bool(case_logs(t, policies))
        n_ds = sum(t.id in d.topics for d in datasets)
        cards.append(
            f'<a class="card topic" data-topic="{t.id}" data-ready="{key}" data-result="{int(res)}" '
            f'data-issue="{int(t.id in issue_topics)}" href="topics/{t.id}.html"><div><h3>{e(t.name)}</h3>'
            f'<span class="badge {cls}">{lab}</span>'
            + (' <span class="badge info">분석 예시 있음</span>' if res else "")
            + f'</div><p class="muted">{e(t.question)}</p><div class="gates">{gate_badges(t)}</div>'
            f'<p class="muted small" style="margin:6px 0 0">데이터셋 {n_ds}개</p></a>'
        )
    issue_cards = "".join(
        f'<a class="card issue-card" href="issues.html#{i.id}"><span class="date">{e(i.effective)}</span>'
        f"<h3>{e(i.name)}</h3><p class='muted' style='margin:0'>{e(i.issue)}</p>"
        f'<div class="tags"><span class="badge {SUPPORT[i.design][1]}">{DESIGN_SHORT[i.design]}</span>'
        f'<span class="badge info">데이터 {len(i.datasets)}개</span></div></a>'
        for i in issues
    )
    n_api = sum(d.access == "open_api" for d in datasets)
    chips = "".join(f'<button class="chip ex" type="button">{e(x)}</button>' for x in HOME_EXAMPLES)
    flow = "".join(
        f'<div class="card"><span class="n">{i + 1:02d}</span><b>{a}</b><p>{b}</p><div class="who">{c}</div></div>'
        for i, (a, b, c) in enumerate(HOME_STEPS)
    )
    js = HOME_JS.replace("__KW__", json.dumps(kw, ensure_ascii=False))
    body = f"""
<div class="hero"><span class="eyebrow">공공데이터 · 인과추론 · 오픈소스</span>
<h1>그 정책, 정말 효과가 있었을까?</h1>
<p class="lede">뉴스와 SNS에서 사람들이 묻는 정책을 공공데이터로 확인합니다.
정책을 받은 곳과 안 받은 곳을 비교하고, 데이터로 판단할 수 없으면 <b>판단할 수 없다고</b> 말합니다.</p>
<div class="ask"><textarea id="q" aria-label="궁금한 정책 이야기" placeholder="궁금한 정책 이야기를 적어 보세요"></textarea>
<div class="chips" aria-label="예시">{chips}</div>
<p id="ans" class="muted">입력한 글은 이 브라우저 안에서만 쓰이고, 어디에도 보내지 않습니다.</p></div>
<div class="stats">
<a class="stat" href="#topics"><div class="v">{len(topics)}</div><div class="l">분석 주제</div></a>
<a class="stat" href="issues.html"><div class="v">{len(issues)}</div><div class="l">지금 이슈인 정책</div></a>
<a class="stat" href="data.html"><div class="v">{len(datasets)}</div><div class="l">정리한 데이터셋</div></a>
<a class="stat" href="data.html"><div class="v">{n_api}</div><div class="l">오픈API로 받을 수 있는 것</div></a>
</div></div>

<section id="how"><h2>이렇게 확인합니다</h2><p class="sub">여섯 단계는 조원 역할과 7주 일정에 그대로 대응합니다.</p>
<div class="flow">{flow}</div></section>

<section id="issues"><h2>지금 이슈인 정책</h2><p class="sub">요즘 논쟁 중인 정책을 어떻게 분석할 수 있는지, 어떤 데이터를 받을 수 있는지 정리했습니다.</p>
<div class="grid">{issue_cards}</div><div class="cta"><a class="btn ghost" href="issues.html">분석 가이드 전체 보기</a></div></section>

<section id="topics"><h2>주제</h2><p class="sub">이슈 하나가 아니라 주제 단위로 봅니다. 배지는 세 가지 확인 사항의 상태입니다.</p>
<div class="chips" role="group" aria-label="필터">
<button class="chip f" data-f="all" aria-pressed="true">전체</button>
<button class="chip f" data-f="issue" aria-pressed="false">지금 이슈 있음</button>
<button class="chip f" data-f="result" aria-pressed="false">분석 예시 있음</button>
<button class="chip f" data-f="key" aria-pressed="false">데이터 키만 있으면 됨</button>
<button class="chip f" data-f="check" aria-pressed="false">확인할 것 있음</button>
<span style="flex:1"></span>
<button class="chip v" data-v="grid" aria-pressed="true">카드</button><button class="chip v" data-v="list" aria-pressed="false">목록</button></div>
<div class="grid" id="cards">{"".join(cards)}</div></section>

<section id="why"><h2>왜 주제 단위로 보나</h2><p class="sub">화제가 된 정책 하나만 골라 분석하면, 결과를 보고 사례를 고르는 것과 같아집니다.</p>
<div class="split">
<div class="card"><h3><span class="badge stop">피하는 방식</span> 화제가 된 정책만 분석</h3>
<ul><li>조용했지만 효과가 컸던 정책이 빠집니다</li><li>화제가 되면 신청이 늘어 효과가 부풀려집니다</li>
<li>시행 전부터 화제였다면 사람들이 미리 움직여 비교가 흔들립니다</li></ul></div>
<div class="card"><h3><span class="badge go">우리 방식</span> 화제는 출발점으로만</h3>
<ul><li>화제는 <b>어느 주제를 볼지</b>만 정합니다</li><li>그 주제의 정책을 <b>전부</b> 모아 비교합니다</li>
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

<section id="join"><h2>참여하기</h2><p class="sub">조마다 주제 하나를 맡아 <code>cases/</code> 폴더에 분석을 추가합니다.</p>
<div class="grid3">
<div class="card"><div class="icon">①</div><h3>주제 고르기</h3><p class="muted">위 주제나 <a href="issues.html">지금 이슈</a>에서 고릅니다. 새 주제는 GitHub 이슈로 제안합니다.</p></div>
<div class="card"><div class="icon">②</div><h3>계획 올리기</h3><p class="muted"><code>cases/_template</code>을 복사해 plan.yaml을 쓰고 PR로 올립니다.</p></div>
<div class="card"><div class="icon">③</div><h3>실행하고 공개</h3><p class="muted"><code>make flow</code>로 돌리고 PR이 합쳐지면 이 사이트에 자동으로 올라옵니다.</p></div>
</div><div class="cta"><a class="btn primary" href="{REPO}/blob/main/docs/ops/group-guide.md">조별 운영 가이드</a>
<a class="btn ghost" href="{REPO}/blob/main/docs/ops/github-onboarding.md">GitHub가 처음이라면</a></div></section>
<script>{js}</script>"""
    return page("정책 효과 분석 플랫폼", body, "index.html")


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
            f'<div class="issue" id="{i.id}"><span class="eyebrow">{e(t.name)}</span><h2>{e(i.name)}</h2>'
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
<div class="hero" style="padding-bottom:0"><span class="eyebrow">지금 이슈</span>
<h1>논쟁 중인 정책, 이렇게 분석합니다</h1>
<p class="lede">2025~2026년에 논쟁이 된 정책 {len(issues)}개를 골라, 누구와 누구를 비교할지, 어떤 방법을 쓸지,
어떤 데이터를 받을 수 있는지 정리했습니다. 시작일은 모두 정부 공식 자료에서 확인했습니다.</p></div>
<div class="banner info" style="margin-top:20px">분석은 이슈 하나가 아니라 그 이슈가 속한 <b>주제 전체</b>로 합니다.
이 목록은 조가 어디서부터 볼지 정하는 출발점입니다.</div>
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
<div class="hero" style="padding-bottom:0"><span class="eyebrow">데이터 지도</span>
<h1>효과를 재려면 어떤 데이터가 필요할까</h1>
<p class="lede">정책 효과를 재려면 세 종류의 데이터가 필요합니다. <b>누가 언제 정책을 받았는지</b>, <b>무엇이 달라졌는지</b>,
<b>결과에 영향을 준 다른 요인</b>입니다. 주제별로 받을 수 있는 공공데이터 {len(datasets)}개를 이 기준으로 정리했습니다.</p></div>

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
def topic_page(t, policies, issues, datasets) -> str:
    by_id = {p.id: p for p in policies}
    ps = [by_id[i] for i in t.policies]
    _, lab, cls = readiness(t)
    my_issues = [i for i in issues if i.topic == t.id]
    my_ds = [d for d in datasets if t.id in d.topics]
    body = [
        f"<div class='hero' style='padding-bottom:0'><span class='eyebrow'>주제</span>"
        f"<h1>{e(t.name)}</h1><p class='lede'>{e(t.question)}</p>"
        f'<div class="gates"><span class="badge {cls}">{lab}</span></div></div>',
        "<section style='padding-top:32px'><h2>1. 이 주제의 정책</h2>",
        f"<p class='muted'>모으는 방법: {COLLECT_KO[t.collect.method]} — {e(t.collect.note)}</p>",
        timeline_svg(t.events),
    ]
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
    if my_issues:
        items = "".join(
            f'<li><a href="../issues.html#{i.id}">{e(i.name)}</a> <span class="muted">({e(i.effective)})</span></li>'
            for i in my_issues
        )
        body.append(f"<h3 style='margin-top:18px'>지금 이슈</h3><ul>{items}</ul>")
    body.append("</section><section><h2>2. 세 가지 확인</h2><div class='grid3'>")
    for k, g in t.gates.items():
        body.append(
            f'<div class="card"><h3>{GATE_Q[k]}</h3><span class="badge {GATE_CLASS[g.status]}">'
            f"{GATE_STATUS_KO[g.status]}</span><p>{e(g.note)}</p></div>"
        )
    body.append("</div></section>")
    if my_ds:
        order = ["treatment", "outcome", "covariate"]
        body.append(
            f"<section><h2>3. 받을 수 있는 데이터 ({len(my_ds)}개)</h2>"
            "<p class='sub'>역할별 전체 목록은 <a href='../data.html'>데이터 지도</a>에 있습니다.</p>"
            + dataset_table(sorted(my_ds, key=lambda d: order.index(d.roles[0])))
            + "</section>"
        )
    if ps:
        body.append("<section><h2>4. 분석 설계</h2>")
        for p in ps:
            sup, scls = SUPPORT[p.design]
            pits = (
                "<details><summary>조심할 점</summary><ul>"
                + "".join(f"<li>{e(x)}</li>" for x in p.pitfalls)
                + "</ul></details>"
                if p.pitfalls
                else ""
            )
            body.append(
                f'<div class="card" style="margin-bottom:12px"><h3>{e(p.name)}</h3>'
                f"<p class='muted'>{e(p.summary)}</p>"
                f"<p><b>{DESIGN_SHORT[p.design]}</b> — {DESIGN_PLAIN[p.design]} "
                f'<span class="badge {scls}">{sup}</span></p>{pits}</div>'
            )
        body.append("</section>")
    cases = case_logs(t, policies)
    if cases:
        body.append("<section><h2>5. 분석 예시</h2>")
        body += [case_block(c, depth=1) for c in cases]
        body.append("</section>")
    if t.pitfalls:
        items = "".join(f"<li>{e(x)}</li>" for x in t.pitfalls)
        body.append(f"<section><h2>주의할 점</h2><ul>{items}</ul></section>")
    return page(f"{t.name} · 정책 효과 분석 플랫폼", "\n".join(body), "index.html#topics", depth=1)


# ─── 빌드 ────────────────────────────────────────────────────────────────────
def main() -> None:
    import architecture

    topics, policies = load_topics(), load_catalog()
    issues, datasets = load_issues(), load_datasets()
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "topics").mkdir(parents=True)
    pages = {
        "index.html": index_page(topics, policies, issues, datasets),
        "issues.html": issues_page(issues, datasets, topics),
        "data.html": data_page(datasets, topics, issues),
        "architecture.html": page(
            "구조 · 정책 효과 분석 플랫폼", architecture.body(e), "architecture.html"
        ),
    }
    for name, text in pages.items():
        (OUT / name).write_text(text, encoding="utf-8")
    for t in topics:
        (OUT / "topics" / f"{t.id}.html").write_text(
            topic_page(t, policies, issues, datasets), encoding="utf-8"
        )
    (OUT / ".nojekyll").write_text("")
    print(f"_site/ 생성: 주제 {len(topics)} · 이슈 {len(issues)} · 데이터셋 {len(datasets)}")


if __name__ == "__main__":
    main()
