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
:root{--paper:#f4f5f7;--surface:#fff;--ink:#16181d;--ink2:#454b57;--muted:#6f7683;--hair:#d9dce2;
--accent:#1d5b8f;--go:#1f6b4f;--go-bg:#e2f1ea;--warn:#8a5a00;--warn-bg:#fbefd7;--stop:#9b2c33;--stop-bg:#f8e3e4;
--sans:"Pretendard","Apple SD Gothic Neo","Malgun Gothic",system-ui,sans-serif}
@media (prefers-color-scheme:dark){:root{--paper:#121418;--surface:#1b1e24;--ink:#eceef2;--ink2:#c3c8d1;--muted:#8d94a1;
--hair:#2e333c;--accent:#7cb4e6;--go:#79d1a8;--go-bg:#16302a;--warn:#e7b35a;--warn-bg:#33291a;--stop:#ec8e95;--stop-bg:#361e21}}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.7 var(--sans);word-break:keep-all}
a{color:var(--accent)}.wrap{max-width:1040px;margin:0 auto;padding:40px 16px 80px}
header.top{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap;border-bottom:2px solid var(--ink);padding-bottom:14px}
header.top a{font-size:14px}h1{font-size:clamp(28px,4.4vw,40px);line-height:1.2;margin:22px 0 8px}
h2{font-size:21px;margin:44px 0 12px}h3{font-size:17px;margin:0 0 6px}.lede{color:var(--ink2);max-width:66ch;margin:0}
.muted{color:var(--muted);font-size:14px}.card{background:var(--surface);border:1px solid var(--hair);border-radius:10px;padding:18px}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(290px,1fr))}
.steps{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));margin-top:16px}
.step{background:var(--surface);border:1px solid var(--hair);border-radius:10px;padding:12px 14px;font-size:14px}
.step b{display:block;font-size:15px}.step .n{color:var(--accent);font-weight:700;font-size:13px}
.badge{display:inline-block;font-size:12.5px;font-weight:600;padding:2px 9px;border-radius:999px;white-space:nowrap}
.go{color:var(--go);background:var(--go-bg)}.warn{color:var(--warn);background:var(--warn-bg)}.stop{color:var(--stop);background:var(--stop-bg)}
.gates{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0 4px}
textarea{width:100%;min-height:74px;font:inherit;padding:12px;border-radius:10px;border:1px solid var(--hair);background:var(--surface);color:var(--ink)}
.hit{outline:2px solid var(--accent)}table{width:100%;border-collapse:collapse;font-size:14px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--hair);vertical-align:top}th{color:var(--muted);font-weight:600}
.tablewrap{overflow-x:auto;background:var(--surface);border:1px solid var(--hair);border-radius:10px}
.banner{border-radius:10px;padding:12px 16px;margin:14px 0;font-weight:600}
.kpi{display:flex;gap:28px;flex-wrap:wrap;margin:8px 0}.kpi div{min-width:120px}.kpi .v{font-size:26px;font-weight:700}
.figs{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}.figs img{width:100%;background:#fff;border-radius:8px;border:1px solid var(--hair)}
svg text{fill:var(--ink2);font:12px var(--sans)}ul{padding-left:20px}footer{margin-top:60px;color:var(--muted);font-size:13px;border-top:1px solid var(--hair);padding-top:14px}
"""


def page(title: str, body: str, depth: int = 0) -> str:
    up = "../" * depth
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)}</title>
<style>{CSS}</style></head><body><div class="wrap">
<header class="top"><a href="{up}index.html"><b>정책 효과 분석 플랫폼</b></a>
<span><a href="{REPO}">GitHub</a> · <span class="muted">가짜연구소 인과추론팀 × OpenUp</span></span></header>
{body}
<footer>모든 수치와 판정은 레포의 <code>catalog/</code>·<code>cases/</code>에서 GitHub Actions가 자동 생성합니다.
시뮬레이션 데이터로 만든 결과에는 별도 표시가 붙습니다. · <a href="{REPO}">{REPO}</a></footer>
</div></body></html>"""


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
        f"<h1>{e(t.name)}</h1><p class='lede'>{e(t.question)}</p>",
        f'<div class="gates">{gate_badges(t)}</div>',
        "<h2>1. 이 주제의 정책 전체</h2>",
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


def index_page(topics, policies) -> str:
    cards = []
    for t in topics:
        cards.append(
            f'<a class="card" data-topic="{t.id}" href="topics/{t.id}.html" style="text-decoration:none;color:inherit">'
            f"<h3>{e(t.name)}</h3><p class='muted' style='margin:0'>{e(t.question)}</p>"
            f'<div class="gates">{gate_badges(t)}</div></a>'
        )
    kw = {
        t.id: list(
            dict.fromkeys(
                t.keywords
                + [k for pid in t.policies for p in policies if p.id == pid for k in p.keywords]
            )
        )
        for t in topics
    }
    steps = [
        ("소셜 신호", "뉴스 제목·SNS 글"),
        ("주제", "신호는 주제까지만 정함"),
        ("정책 전체 수집", "법제처 조례·고시로 지역×시점"),
        ("세 관문", "언제 · 누가 · 무엇을"),
        ("사전 등록", "계획을 먼저 커밋"),
        ("효과 추정", "판정: 식별됨·조건부·식별 불가"),
    ]
    body = f"""
<h1>소셜 반응에서 정책 효과까지</h1>
<p class="lede">사람들이 이야기하는 정책이 실제로 효과가 있었는지, 공공데이터로 확인합니다.
화제가 된 정책 하나만 골라 분석하지 않고, <b>그 주제의 정책을 전부 모아</b> 비교합니다.
화제성으로 사례를 고르면 결과를 보고 사례를 고르는 셈이 되기 때문입니다.</p>
<div class="steps">{"".join(f'<div class="step"><span class="n">{i + 1}</span><b>{a}</b>{b}</div>' for i, (a, b) in enumerate(steps))}</div>
<h2>지금 어떤 이야기가 궁금하세요?</h2>
<textarea id="q" placeholder="예: 토허제 확대하고 강남 집값 잡혔나요? / 지역화폐 쓰면 동네 가게 매출이 오르나요?"></textarea>
<p id="ans" class="muted">글을 입력하면 해당하는 주제를 찾아 표시합니다. (브라우저 안에서만 동작, 서버로 보내지 않음)</p>
<h2>주제</h2><div class="grid" id="cards">{"".join(cards)}</div>
<script>
const KW={json.dumps(kw, ensure_ascii=False)};
const norm=s=>s.replace(/\\s+/g,'').toLowerCase();
document.getElementById('q').addEventListener('input',ev=>{{
  const t=norm(ev.target.value);let best=null,bs=0,hits=[];
  for(const [id,ks] of Object.entries(KW)){{const h=ks.filter(k=>t.includes(norm(k)));
    const s=h.reduce((a,k)=>a+Math.min(norm(k).length,6),0);if(s>bs){{bs=s;best=id;hits=h;}}}}
  document.querySelectorAll('#cards .card').forEach(c=>c.classList.toggle('hit',c.dataset.topic===best));
  const a=document.getElementById('ans');
  if(!t){{a.textContent='글을 입력하면 해당하는 주제를 찾아 표시합니다.';return;}}
  if(!best){{a.textContent='맞는 주제를 찾지 못했습니다. 정책명이나 지역·시점을 넣어 보세요.';return;}}
  const c=document.querySelector(`#cards [data-topic="${{best}}"]`);
  a.innerHTML=`→ <a href="${{c.getAttribute('href')}}">${{c.querySelector('h3').textContent}}</a> (일치: ${{hits.join(', ')}})`;
}});
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
    (OUT / ".nojekyll").write_text("")
    print(f"_site/ 생성: 주제 {len(topics)}개")


if __name__ == "__main__":
    main()
