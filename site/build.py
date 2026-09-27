"""정적 대시보드 빌더 → _site/ (GitHub Pages, 서버 없음)

    python site/build.py            # _site/index.html, _site/topics/<id>.html
    python -m http.server -d _site  # 로컬 미리보기

입력(모두 레포에 커밋된 파일): catalog/topics.yaml, catalog/policies.yaml,
catalog/snapshots/law_<topic>.csv(있으면), cases/<case>/flow_log.json·figures/*.png
"""

from __future__ import annotations

import html
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.agent.guard import TRIGGER_KO  # noqa: E402
from core.discovery.catalog import (  # noqa: E402
    GATE_KO,
    GATE_STATUS_KO,
    load_catalog,
    load_topics,
)

OUT = ROOT / "_site"
REPO = "https://github.com/CausalInferenceLab/policy-effect-analytics-agent"
VERDICT = {
    "identified": ("식별됨", "go"),
    "conditional": ("조건부", "warn"),
    "not_identified": ("식별 불가", "stop"),
}
GATE_CLASS = {"pass": "go", "check": "warn", "key": "warn", "fail": "stop"}
ACCESS_KO = {"api_key": "API 키(자동승인)", "file": "파일", "manual": "수동 수집"}
COLLECT_KO = {
    "law_ordinance": "법제처 조례 자동 수집",
    "notice": "고시문에서 이력 수집",
    "curated": "카탈로그 목록",
}

e = html.escape

CSS = """
:root{--paper:#f6f7f9;--surface:#fff;--sunk:#eef0f3;--ink:#14171c;--ink2:#434954;--muted:#6b7280;--hair:#dde0e5;
--accent:#1b5e9b;--accent-soft:#e3eef8;--go:#1e6a4d;--go-bg:#e0f1e8;--warn:#8a5900;--warn-bg:#fbeed3;--stop:#9c2b33;--stop-bg:#f8e2e4;
--sans:"Pretendard","Apple SD Gothic Neo","Malgun Gothic",system-ui,sans-serif;--mono:ui-monospace,SFMono-Regular,Menlo,monospace}
@media (prefers-color-scheme:dark){:root{--paper:#111317;--surface:#1a1d23;--sunk:#22262d;--ink:#eceef2;--ink2:#c2c7d0;--muted:#8e95a2;
--hair:#2d323a;--accent:#79b2e8;--accent-soft:#1a2b3c;--go:#7fd3ab;--go-bg:#15302a;--warn:#e8b45c;--warn-bg:#33291a;--stop:#ee8f96;--stop-bg:#371e21}}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.7 var(--sans);word-break:keep-all}
a{color:var(--accent)}code{font-family:var(--mono);font-size:.9em;background:var(--sunk);padding:1px 5px;border-radius:4px}
.nav{position:sticky;top:0;z-index:5;background:color-mix(in srgb,var(--paper) 88%,transparent);backdrop-filter:blur(8px);border-bottom:1px solid var(--hair)}
.nav .in{max-width:1080px;margin:0 auto;padding:10px 16px;display:flex;gap:16px;align-items:center;justify-content:space-between;flex-wrap:wrap}
.nav b a{color:var(--ink);text-decoration:none}.nav .links{display:flex;gap:14px;flex-wrap:wrap;font-size:14px}.nav .links a{color:var(--ink2);text-decoration:none}
.nav .links a:hover{color:var(--accent)}.wrap{max-width:1080px;margin:0 auto;padding:0 16px 80px}
.hero{padding:64px 0 28px}.eyebrow{font-size:13px;font-weight:700;letter-spacing:.06em;color:var(--accent)}
h1{font-size:clamp(30px,5vw,48px);line-height:1.18;margin:10px 0 14px;letter-spacing:-.02em}
h2{font-size:clamp(22px,3vw,28px);margin:0 0 6px;letter-spacing:-.01em}h3{font-size:17px;margin:0 0 6px}
.lede{color:var(--ink2);font-size:18px;max-width:62ch;margin:0}.sub{color:var(--ink2);max-width:66ch;margin:0 0 20px}
section{padding:56px 0 8px;scroll-margin-top:56px}.muted{color:var(--muted);font-size:14px}
.cta{display:flex;gap:10px;flex-wrap:wrap;margin:22px 0 0}.btn{display:inline-block;padding:10px 18px;border-radius:999px;font-weight:600;text-decoration:none;font-size:15px}
.btn.primary{background:var(--accent);color:#fff}.btn.ghost{border:1px solid var(--hair);color:var(--ink);background:var(--surface)}
.card{background:var(--surface);border:1px solid var(--hair);border-radius:14px;padding:20px}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(280px,1fr))}.grid3{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}
.icon{width:36px;height:36px;border-radius:10px;background:var(--accent-soft);color:var(--accent);display:grid;place-items:center;font-weight:800;margin-bottom:10px}
.badge{display:inline-block;font-size:12.5px;font-weight:600;padding:2px 9px;border-radius:999px;white-space:nowrap}
.go{color:var(--go);background:var(--go-bg)}.warn{color:var(--warn);background:var(--warn-bg)}.stop{color:var(--stop);background:var(--stop-bg)}.info{color:var(--accent);background:var(--accent-soft)}
.gates{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0 4px}
.ask{margin-top:26px}.ask textarea{width:100%;min-height:76px;font:inherit;font-size:17px;padding:14px 16px;border-radius:14px;border:1px solid var(--hair);background:var(--surface);color:var(--ink)}
.ask textarea:focus{outline:2px solid var(--accent);border-color:transparent}.chips{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}
.chip{border:1px solid var(--hair);background:var(--surface);color:var(--ink2);border-radius:999px;padding:4px 12px;font:inherit;font-size:13.5px;cursor:pointer}
.chip[aria-pressed=true]{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.hit{outline:2px solid var(--accent);outline-offset:2px}.topic{text-decoration:none;color:inherit;display:block}.topic:hover{border-color:var(--accent)}
.list .topic{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,2fr) auto;gap:14px;align-items:center}
.list{display:flex;flex-direction:column;gap:8px}.list .topic p{margin:0}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--hair);vertical-align:top}th{color:var(--muted);font-weight:600}
.tablewrap{overflow-x:auto;background:var(--surface);border:1px solid var(--hair);border-radius:12px}
.banner{border-radius:12px;padding:12px 16px;margin:14px 0;font-weight:600}
.figs{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}.figs img{width:100%;background:#fff;border-radius:10px;border:1px solid var(--hair)}
svg text{fill:var(--ink2);font:12.5px var(--sans)}svg .strong{fill:var(--ink);font-weight:700}ul,ol{padding-left:20px}
.flow{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));counter-reset:s}
.flow .card{padding:14px;position:relative}.flow .n{font:700 12px var(--mono);color:var(--accent)}.flow b{display:block;margin:2px 0 4px}.flow p{margin:0;font-size:14px;color:var(--ink2)}
.flow .who{margin-top:8px;font-size:12.5px;color:var(--muted)}.split{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}
.vs .card h3{display:flex;gap:8px;align-items:center}.stat{font-size:28px;font-weight:800;letter-spacing:-.02em}
footer{margin-top:64px;color:var(--muted);font-size:13px;border-top:1px solid var(--hair);padding-top:16px}
@media (max-width:640px){.list .topic{grid-template-columns:minmax(0,1fr)}.hero{padding-top:40px}}
"""


def page(title: str, body: str, depth: int = 0) -> str:
    up = "../" * depth
    home = f"{up}index.html"
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>
<meta name="description" content="소셜 반응에서 출발해 공공데이터로 정책 효과를 확인하는 오픈소스 플랫폼">
<style>{CSS}</style></head><body>
<nav class="nav"><div class="in"><b><a href="{home}">정책 효과 분석 플랫폼</a></b>
<span class="links"><a href="{home}#why">왜</a><a href="{home}#flow">흐름</a><a href="{home}#topics">주제</a>
<a href="{up}architecture.html">아키텍처</a><a href="{home}#trust">신뢰</a><a href="{home}#join">참여하기</a><a href="{REPO}">GitHub ↗</a></span></div></nav>
<div class="wrap">{body}
<footer>가짜연구소 인과추론팀 × 오픈업 오픈소스 AI 특화형 트랙3 · 모든 수치와 판정은 레포의 <code>catalog/</code>·<code>cases/</code>에서
GitHub Actions가 자동 생성합니다(매주 월요일 갱신). 시뮬레이션 데이터로 만든 결과에는 별도 표시가 붙습니다.
· <a href="{REPO}">소스 코드 (MIT)</a></footer></div></body></html>"""


def gate_badges(t) -> str:
    return "".join(
        f'<span class="badge {GATE_CLASS[g.status]}" title="{e(g.note)}">'
        f"{GATE_KO[k]} · {GATE_STATUS_KO[g.status]}</span>"
        for k, g in t.gates.items()
    )


def timeline_svg(events) -> str:
    """축 위에 점, 아래에 연도 눈금. 설명은 HTML 목록으로 (긴 한국어 라벨이 겹치지 않게)."""
    if not events:
        return ""
    d = pd.to_datetime([ev.date for ev in events])
    lo = pd.Timestamp(year=d.min().year, month=1, day=1)
    hi = pd.Timestamp(year=d.max().year + 1, month=1, day=1)
    w, x0, x1 = 900, 20, 880

    def x(t):
        return x0 + (x1 - x0) * ((t - lo) / (hi - lo))

    ticks = "".join(
        f'<line x1="{x(pd.Timestamp(year=y, month=1, day=1)):.0f}" y1="26" '
        f'x2="{x(pd.Timestamp(year=y, month=1, day=1)):.0f}" y2="32" stroke="var(--muted)"/>'
        f'<text x="{x(pd.Timestamp(year=y, month=1, day=1)):.0f}" y="48" text-anchor="middle">{y}</text>'
        for y in range(lo.year, hi.year + 1)
    )
    dots = "".join(
        f'<circle cx="{x(t):.0f}" cy="26" r="7" fill="var(--accent)"/>'
        f'<text x="{x(t):.0f}" y="14" text-anchor="middle">{i + 1}</text>'
        for i, t in enumerate(d)
    )
    items = "".join(
        f"<li><b>{ev.date:%Y.%m.%d}</b> {e(ev.what)}"
        + (f' <a href="{e(ev.source)}">출처</a>' if ev.source else "")
        + "</li>"
        for ev in events
    )
    return (
        f'<svg viewBox="0 0 {w} 56" width="100%" role="img" aria-label="정책 시점">'
        f'<line x1="{x0}" y1="26" x2="{x1}" y2="26" stroke="var(--ink2)"/>{ticks}{dots}</svg>'
        f"<ol>{items}</ol>"
    )


def bars_svg(counts: pd.Series, label: str) -> str:
    if counts.empty:
        return ""
    w, h, pad = 900, 220, 30
    bw = (w - 2 * pad) / len(counts)
    mx = counts.max()
    bars = []
    for i, (k, v) in enumerate(counts.items()):
        bh = (h - 60) * v / mx
        xx = pad + i * bw
        bars.append(
            f'<rect x="{xx + 3:.0f}" y="{h - 30 - bh:.0f}" width="{bw - 6:.0f}" height="{bh:.0f}" rx="3" fill="var(--accent)"/>'
            f'<text x="{xx + bw / 2:.0f}" y="{h - 12}" text-anchor="middle">{k}</text>'
            f'<text x="{xx + bw / 2:.0f}" y="{h - 36 - bh:.0f}" text-anchor="middle">{v}</text>'
        )
    return f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="{e(label)}">{"".join(bars)}</svg>'


def case_block(case_rel: str, depth: int) -> str:
    case = ROOT / case_rel
    log_p = case / "flow_log.json"
    if not log_p.exists():
        return '<p class="muted">아직 실행 결과가 없습니다.</p>'
    log = json.loads(log_p.read_text(encoding="utf-8"))
    import yaml

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
            '<div class="banner stop">시뮬레이션 데이터 결과입니다. 실제 정책 효과가 아닙니다 '
            "(API 키 발급 후 실데이터로 교체).</div>"
        )
    out.append(f"<p><b>질문</b> {e(plan['question'].strip())}</p>")
    out.append(f'<p>종합 판정 <span class="badge {cls}">{label}</span></p>')
    names = {o["col"]: o["name"] for o in plan["outcomes"]}
    rows = []
    for r in log["results"]:
        lab, c = VERDICT[r["verdict"]]
        why = ", ".join(TRIGGER_KO.get(x, x) for x in r.get("triggers") or []) or "-"
        rows.append(
            f"<tr><td>{e(names.get(r['outcome'], r['outcome']))}</td><td>{r['estimate']:+.3f}</td>"
            f"<td>[{r['ci_low']:.3f}, {r['ci_high']:.3f}]</td><td>{r['p_value']:.3f}</td>"
            f'<td><span class="badge {c}">{lab}</span></td><td class="muted">{e(why)}</td></tr>'
        )
    out.append(
        '<div class="tablewrap"><table><tr><th>결과 지표</th><th>추정치</th><th>95% 신뢰구간</th>'
        f"<th>p</th><th>판정</th><th>경고</th></tr>{''.join(rows)}</table></div>"
    )
    narr = (log.get("guard") or {}).get("narrative")
    if narr:
        out.append(f'<p class="card" style="margin-top:12px">{e(narr).replace("**", "")}</p>')
    if figs:
        out.append(f'<div class="figs" style="margin-top:12px">{"".join(figs)}</div>')
    out.append(
        f'<p class="muted">분석계획·코드·리포트: <a href="{REPO}/tree/main/{case_rel}">{case_rel}</a></p>'
    )
    return "\n".join(out)


def topic_page(t, policies) -> str:
    by_id = {p.id: p for p in policies}
    ps = [by_id[i] for i in t.policies]
    body = [
        f"<div class='hero' style='padding-bottom:0'><span class='eyebrow'>주제</span>"
        f"<h1>{e(t.name)}</h1><p class='lede'>{e(t.question)}</p></div>",
        f'<div class="gates">{gate_badges(t)}</div>',
        "<section style='padding-top:32px'><h2>1. 이 주제의 정책 전체</h2>",
        f"<p class='muted'>수집 방법: {COLLECT_KO[t.collect.method]} — {e(t.collect.note)}</p>",
        timeline_svg(t.events),
    ]
    snap = ROOT / "catalog" / "snapshots" / f"law_{t.id}.csv"
    if t.collect.method == "law_ordinance":
        if snap.exists():
            df = pd.read_csv(snap)
            cnt = df.dropna(subset=["year"]).astype({"year": int}).groupby("year").size()
            body += [
                f"<h3>조례 시행연도 분포 (법제처, {len(df)}건)</h3>",
                bars_svg(cnt, "조례 시행연도"),
                "<p class='muted'>현행 조례의 시행일자 기준입니다. 처음 제정된 날은 연혁 조회로 확인합니다.</p>",
            ]
        else:
            body.append(
                "<p class='card'>법제처 API로 조례를 자동 수집할 주제입니다. 레포 시크릿 <code>LAW_OC</code>를 "
                "등록하면 GitHub Actions가 다음 배포 때 지자체별 조례 목록과 시행일을 채웁니다.</p>"
            )
    body.append("<h2>2. 세 가지 관문</h2><div class='grid'>")
    for k, g in t.gates.items():
        body.append(
            f'<div class="card"><h3>{GATE_KO[k]}</h3><span class="badge {GATE_CLASS[g.status]}">'
            f"{GATE_STATUS_KO[g.status]}</span><p>{e(g.note)}</p></div>"
        )
    body.append("</div>")
    if ps:
        body.append("<h2>3. 분석 가능한 정책과 추천 데이터</h2>")
        for p in ps:
            ds = "".join(
                f"<tr><td><a href='{e(d.url)}'>{e(d.name)}</a></td><td>{e(d.provider)}</td>"
                f"<td>{e(d.granularity)}</td><td>{ACCESS_KO[d.access]}</td><td>{e(d.license)}</td></tr>"
                for d in p.datasets
            )
            sup = "go" if p.support == "지원" else "warn"
            body.append(
                f'<div class="card" style="margin-bottom:12px"><h3>{e(p.name)}</h3>'
                f"<p class='muted'>{e(p.summary)}</p>"
                f'<p>설계 {p.design_ko} <span class="badge {sup}">{e(p.support)}</span></p>'
                f"<div class='tablewrap'><table><tr><th>데이터셋</th><th>제공</th><th>단위</th><th>접근</th>"
                f"<th>라이선스</th></tr>{ds}</table></div>"
                + (
                    "<details style='margin-top:8px'><summary>식별상 함정</summary><ul>"
                    + "".join(f"<li>{e(x)}</li>" for x in p.pitfalls)
                    + "</ul></details>"
                    if p.pitfalls
                    else ""
                )
                + "</div>"
            )
    cases = [p.sample_case for p in ps if p.sample_case]
    if cases:
        body.append("<h2>4. 효과 분석 결과</h2>")
        body += [case_block(c, depth=1) for c in cases]
    if t.pitfalls:
        body.append(
            "<h2>주의할 점</h2><ul>" + "".join(f"<li>{e(x)}</li>" for x in t.pitfalls) + "</ul>"
        )
    body.append(
        "<h2>소셜 신호는 여기에만 씁니다</h2><ul><li>이 주제를 고르는 데</li>"
        "<li>시행 전 1년 검색량·기사 수로 <b>미리 반응했는지</b> 점검하는 데</li>"
        "<li>'정책이 알려지긴 했나'를 묻는다면 관심도 자체를 결과 지표로</li></ul>"
    )
    return page(t.name, "\n".join(body), depth=1)


def readiness(t) -> tuple[str, str, str]:
    """주제 전체 준비 상태 (필터용 키, 라벨, 색)."""
    st = {g.status for g in t.gates.values()}
    if "fail" in st:
        return "fail", "관문 탈락", "stop"
    if "check" in st:
        return "check", "확인 필요", "warn"
    if "key" in st:
        return "key", "데이터 키 대기", "warn"
    return "ready", "분석 가능", "go"


def has_result(t, policies) -> bool:
    by_id = {p.id: p for p in policies}
    return any(
        by_id[i].sample_case and (ROOT / by_id[i].sample_case / "flow_log.json").exists()
        for i in t.policies
    )


FLOW_STEPS = [
    ("소셜 신호", "뉴스 제목·SNS 글에서 사람들이 궁금해하는 것을 읽습니다", "누구나"),
    (
        "주제 고르기",
        "신호는 <b>주제까지만</b> 정합니다. 화제가 된 정책 하나를 고르지 않습니다",
        "플랫폼 자동",
    ),
    ("정책 전부 모으기", "법제처 조례·부처 고시로 '어느 지역이 언제부터'를 모읍니다", "수집 담당"),
    ("세 관문", "언제 시작했나 · 누가 받았나 · 무엇으로 재나", "문제 정의 담당"),
    ("계획 먼저", "데이터를 보기 전에 분석계획을 커밋합니다(사전 등록)", "문제 정의 담당"),
    (
        "효과 추정·판정",
        "식별됨 · 조건부 · 식별 불가 — 과장 표현은 자동으로 막습니다",
        "추정·리포트 담당",
    ),
]


def index_page(topics, policies) -> str:
    kw = {
        t.id: list(
            dict.fromkeys(
                t.keywords
                + [k for pid in t.policies for p in policies if p.id == pid for k in p.keywords]
            )
        )
        for t in topics
    }
    cards = []
    for t in topics:
        key, lab, cls = readiness(t)
        res = has_result(t, policies)
        cards.append(
            f'<a class="card topic" data-topic="{t.id}" data-ready="{key}" data-result="{int(res)}" '
            f'href="topics/{t.id}.html"><div><h3>{e(t.name)}</h3>'
            f'<span class="badge {cls}">{lab}</span>'
            + (' <span class="badge info">분석 결과 있음</span>' if res else "")
            + f'</div><p class="muted">{e(t.question)}</p><div class="gates">{gate_badges(t)}</div></a>'
        )
    n_ready = sum(1 for t in topics if has_result(t, policies))
    flow = "".join(
        f'<div class="card"><span class="n">{i + 1:02d}</span><b>{a}</b><p>{b}</p><div class="who">{c}</div></div>'
        for i, (a, b, c) in enumerate(FLOW_STEPS)
    )
    examples = [
        "토허제 확대하고 강남 집값 잡혔나요?",
        "지역화폐 쓰면 동네 가게 매출이 오르나요?",
        "5030 속도 줄이고 사고 줄었나?",
        "계절관리제 하면 미세먼지 줄어요?",
    ]
    chips = "".join(f'<button class="chip ex" type="button">{e(x)}</button>' for x in examples)
    body = f"""
<div class="hero"><span class="eyebrow">OPEN SOURCE · 공공데이터 · 인과추론</span>
<h1>사람들이 묻는 정책,<br>정말 효과가 있었을까?</h1>
<p class="lede">소셜 반응에서 출발해, 그 주제의 정책을 전부 모으고, 공공데이터로 효과를 추정합니다.
결론을 낼 수 없으면 <b>"식별 불가"라고 말하는 것</b>까지가 이 플랫폼의 일입니다.</p>
<div class="ask"><textarea id="q" aria-label="궁금한 정책 이야기" placeholder="궁금한 정책 이야기를 적어 보세요"></textarea>
<div class="chips" aria-label="예시">{chips}</div>
<p id="ans" class="muted">입력한 글은 이 브라우저 안에서만 쓰입니다. 서버로 보내지 않습니다.</p></div>
<div class="cta"><a class="btn primary" href="#topics">주제 둘러보기</a><a class="btn ghost" href="architecture.html">어떻게 동작하나</a></div>
</div>

<section id="why"><h2>왜 이렇게 만드나</h2><p class="sub">화제가 된 정책만 골라 분석하면 결과를 보고 사례를 고르는 셈이 됩니다.</p>
<div class="split vs">
<div class="card"><h3><span class="badge stop">A</span> 화제성으로 사례를 고르면</h3>
<ul><li>조용했지만 효과가 컸던 정책이 빠집니다</li><li>화제가 되면 신청이 늘어 효과가 부풀려집니다</li>
<li>시행 전부터 화제였다면 사람들이 미리 움직여 비교가 깨집니다</li></ul></div>
<div class="card"><h3><span class="badge go">B</span> 화제성은 출발점으로만 쓰면</h3>
<ul><li>신호는 <b>어느 주제를 볼지</b>만 정합니다</li><li>그 주제의 정책을 <b>전부</b> 모아 비교합니다</li>
<li>신호는 나중에 '미리 반응했나' 점검용으로 다시 씁니다</li></ul></div></div></section>

<section id="flow"><h2>여섯 단계 흐름</h2><p class="sub">각 단계는 조원 역할과 7주 일정에 그대로 대응합니다.</p>
<div class="flow">{flow}</div></section>

<section id="topics"><h2>주제</h2><p class="sub">주제마다 세 관문(언제·누가·무엇을)의 통과 여부를 보여줍니다.</p>
<div class="chips" role="group" aria-label="필터">
<button class="chip f" data-f="all" aria-pressed="true">전체 {len(topics)}</button>
<button class="chip f" data-f="result" aria-pressed="false">분석 결과 있음 {n_ready}</button>
<button class="chip f" data-f="key" aria-pressed="false">데이터 키 대기</button>
<button class="chip f" data-f="check" aria-pressed="false">확인 필요</button>
<span style="flex:1"></span>
<button class="chip v" data-v="grid" aria-pressed="true">카드</button><button class="chip v" data-v="list" aria-pressed="false">목록</button></div>
<div class="grid" id="cards">{"".join(cards)}</div></section>

<section id="trust"><h2>무엇을 믿을 수 있나</h2><p class="sub">결과보다 과정을 먼저 공개합니다.</p>
<div class="grid3">
<div class="card"><div class="icon">1</div><h3>계획을 먼저 커밋</h3><p class="muted">분석계획(plan.yaml)이 git에 커밋되지 않으면 추정 단계가 실행되지 않습니다.</p></div>
<div class="card"><div class="icon">2</div><h3>방법은 규칙이 정함</h3><p class="muted">LLM은 주제·서술을 돕고, 추정 방법은 데이터 모양을 보고 규칙이 고릅니다. 수치는 검증된 라이브러리가 계산합니다.</p></div>
<div class="card"><div class="icon">3</div><h3>작은 표본에 맞는 추론</h3><p class="muted">처치 지역이 10곳 미만이면 무작위화 추론으로 바꿉니다. 시뮬레이션에서 95% 신뢰구간 포함률 95%를 확인했습니다.</p></div>
<div class="card"><div class="icon">4</div><h3>과장 표현 차단</h3><p class="muted">판정이 '식별됨'이 아니면 "입증", "때문에" 같은 표현을 리포트에서 막습니다.</p></div>
<div class="card"><div class="icon">5</div><h3>출처·라이선스 표시</h3><p class="muted">모든 데이터셋에 제공 기관, 공공누리 유형, 수집 시점을 붙입니다.</p></div>
<div class="card"><div class="icon">6</div><h3>한계도 공개</h3><p class="muted">시뮬레이션 결과, 키 대기, 확인 필요 상태를 숨기지 않고 배지로 표시합니다.</p></div>
</div></section>

<section id="join"><h2>참여하기</h2><p class="sub">조별로 주제 하나를 맡아 <code>cases/</code>에 케이스를 추가합니다.</p>
<div class="grid3">
<div class="card"><div class="icon">①</div><h3>주제 고르기</h3><p class="muted">위 주제 중 하나를 고르거나 <code>catalog/topics.yaml</code>에 새 주제를 제안합니다.</p></div>
<div class="card"><div class="icon">②</div><h3>계획 PR</h3><p class="muted"><code>cases/_template</code>을 복사해 plan.yaml을 쓰고 PR로 사전 등록합니다.</p></div>
<div class="card"><div class="icon">③</div><h3>실행·공개</h3><p class="muted"><code>make flow</code>로 돌리면 이 사이트에 결과가 자동으로 올라옵니다.</p></div>
</div><div class="cta"><a class="btn primary" href="{REPO}/blob/main/docs/ops/group-guide.md">조별 운영 가이드</a>
<a class="btn ghost" href="{REPO}/blob/main/docs/ops/github-onboarding.md">GitHub 처음이라면</a></div></section>

<script>
const KW={json.dumps(kw, ensure_ascii=False)};
const norm=s=>s.replace(/\s+/g,'').toLowerCase();
const q=document.getElementById('q'),ans=document.getElementById('ans');
function match(){{
  const t=norm(q.value);let best=null,bs=0,hits=[];
  for(const [id,ks] of Object.entries(KW)){{const h=ks.filter(k=>t.includes(norm(k)));
    const s=h.reduce((a,k)=>a+Math.min(norm(k).length,6),0);if(s>bs){{bs=s;best=id;hits=h;}}}}
  document.querySelectorAll('#cards .topic').forEach(c=>c.classList.toggle('hit',c.dataset.topic===best));
  if(!t){{ans.textContent='입력한 글은 이 브라우저 안에서만 쓰입니다. 서버로 보내지 않습니다.';return;}}
  if(!best){{ans.textContent='맞는 주제를 찾지 못했습니다. 정책명이나 지역을 넣어 보세요.';return;}}
  const c=document.querySelector(`#cards [data-topic="${{best}}"]`);
  ans.innerHTML=`→ 주제 <a href="${{c.getAttribute('href')}}"><b>${{c.querySelector('h3').textContent}}</b></a> · 일치한 말: ${{hits.join(', ')}} · 이 주제의 정책 전체를 봅니다`;
}}
q.addEventListener('input',match);
document.querySelectorAll('.ex').forEach(b=>b.onclick=()=>{{q.value=b.textContent;match();}});
document.querySelectorAll('.f').forEach(b=>b.onclick=()=>{{
  document.querySelectorAll('.f').forEach(x=>x.setAttribute('aria-pressed',x===b));const f=b.dataset.f;
  document.querySelectorAll('#cards .topic').forEach(c=>c.hidden=!(f==='all'||(f==='result'?c.dataset.result==='1':c.dataset.ready===f)));}});
document.querySelectorAll('.v').forEach(b=>b.onclick=()=>{{
  document.querySelectorAll('.v').forEach(x=>x.setAttribute('aria-pressed',x===b));
  document.getElementById('cards').className=b.dataset.v==='list'?'list':'grid';}});
</script>"""
    return page("정책 효과 분석 플랫폼", body)


def main() -> None:
    topics, policies = load_topics(), load_catalog()
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "topics").mkdir(parents=True)
    (OUT / "index.html").write_text(index_page(topics, policies), encoding="utf-8")
    for t in topics:
        (OUT / "topics" / f"{t.id}.html").write_text(topic_page(t, policies), encoding="utf-8")
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import architecture

    (OUT / "architecture.html").write_text(
        page("아키텍처 · 정책 효과 분석 플랫폼", architecture.body(e)), encoding="utf-8"
    )
    (OUT / ".nojekyll").write_text("")
    print(f"_site/ 생성: 주제 {len(topics)}개")


if __name__ == "__main__":
    main()
