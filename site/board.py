"""이슈 보드 — 이슈 → 공공데이터 → 계보 → 분석 → 대시보드를 한 흐름으로.

- 홈: 흐름 띠(flow_strip)와 흐름 지도(flow_map: 주제 × 다섯 단계)
- 주제 페이지: 단계 레일(rail, 스크롤 위치를 따라 켜짐), 계보 그림(lineage_svg), 대시보드(event_chart)
- 답 페이지: 같은 이벤트 스터디 그림
그림은 모두 인라인 SVG 와 작은 JS(site/board.js)라 외부 라이브러리가 없다.
"""

from __future__ import annotations

import math

STAGES = [
    ("issue", "이슈", "지금 논쟁 중인 정책과 시행일"),
    ("data", "공공데이터", "받을 수 있는 공개 자료"),
    ("lineage", "계보", "데이터가 지표가 되는 길"),
    ("analysis", "분석", "받은 곳과 안 받은 곳 비교"),
    ("dashboard", "대시보드", "시점별 효과 그림"),
]
READY = {"즉시", "자동승인", "없음"}
KIND_COL = {"issue": 0, "policy": 0, "dataset": 1, "transform": 2, "metric": 3}
COL_TITLE = ["이슈 · 정책", "원천 데이터", "가공", "지표", "분석"]


# ─── 단계 집계 ───────────────────────────────────────────────────────────────
def topic_stages(t, issues, datasets, lineages, answers) -> dict[str, int]:
    """주제 하나의 단계별 개수. 0이면 그 단계가 비어 있다."""
    mine = [a for a in answers if a["topic"] == t.id]
    return {
        "issue": sum(i.topic == t.id for i in issues) + len(t.events),
        "data": sum(t.id in d.topics for d in datasets),
        "lineage": sum(lin.topic == t.id for lin in lineages),
        "analysis": len(mine),
        "dashboard": sum(bool(chart_result(a)) for a in mine),
    }


def totals(issues, datasets, lineages, answers) -> dict[str, int]:
    return {
        "issue": len(issues),
        "data": len(datasets),
        "lineage": len(lineages),
        "analysis": len(answers),
        "dashboard": sum(bool(chart_result(a)) for a in answers),
    }


def ready_count(datasets) -> int:
    return sum(d.approval in READY for d in datasets)


# ─── 홈: 흐름 띠 ─────────────────────────────────────────────────────────────
def flow_strip(e, tot: dict, links: dict, ready: int) -> str:
    """다섯 단계를 잇는 띠. 처음 열릴 때 한 번 왼쪽부터 차례로 그려진다(board.js · 동작 줄이기 설정 존중)."""
    notes = {
        "issue": "논쟁 중인 정책",
        "data": f"{ready}개는 오늘 바로 받기",
        "lineage": "이슈→지표 연결",
        "analysis": "판정까지 공개",
        "dashboard": "시점별 효과 그림",
    }
    items = "".join(
        f'<li style="--i:{i}"><a href="{links[k]}" data-track="flow-stage">'
        f'<span class="dot" aria-hidden="true"></span><span class="n" data-count="{tot[k]}">{tot[k]}</span>'
        f"<b>{lab}</b><span class='note'>{e(notes[k])}</span></a></li>"
        for i, (k, lab, _d) in enumerate(STAGES)
    )
    return f'<ol class="flow" aria-label="이슈에서 대시보드까지">{items}</ol>'


def flow_map(e, rows: list[tuple], up: str = "") -> str:
    """흐름 지도: 주제마다 다섯 단계가 얼마나 채워졌는지. rows = [(topic, stages, side_html)]"""
    head = "".join(f"<span>{lab}</span>" for _k, lab, _d in STAGES)
    out = []
    for t, st, side in rows:
        done = sum(1 for k, _l, _d in STAGES if st[k])
        cells = "".join(
            f'<span class="cell{" on" if st[k] else ""}" title="{lab} {st[k]}">'
            f"{st[k] if st[k] else ''}</span>"
            for k, lab, _d in STAGES
        )
        out.append(
            f'<a class="topic fm-row" data-topic="{t.id}" href="{up}topics/{t.id}.html">'
            f'<span class="fm-name"><b>{e(t.name)}</b><span class="q">{e(t.question)}</span></span>'
            f'<span class="fm-cells" aria-label="다섯 단계 중 {done}단계 채움">{cells}</span>'
            f'<span class="fm-side">{side}</span></a>'
        )
    return (
        f'<div class="fm" id="cards"><div class="fm-head" aria-hidden="true"><span></span>'
        f'<span class="fm-cells">{head}</span><span></span></div>{"".join(out)}</div>'
    )


# ─── 주제 페이지: 단계 레일 ──────────────────────────────────────────────────
def rail(e, st: dict) -> str:
    items = "".join(
        f'<li><a href="#s-{k}" data-spy="s-{k}"><span class="dot{" on" if st[k] else ""}" aria-hidden="true"></span>'
        f"<b>{lab}</b><span class='n'>{st[k] or '—'}</span></a></li>"
        for k, lab, _d in STAGES
    )
    return f'<nav class="rail" aria-label="이 주제의 흐름"><ol>{items}</ol></nav>'


def stage_head(e, k: str, extra: str = "") -> str:
    i = [s[0] for s in STAGES].index(k)
    _k, lab, desc = STAGES[i]
    return f'<div class="stage-head"><span class="stepno">{i + 1}</span><h2>{lab}</h2><span class="muted">{e(desc)}</span>{extra}</div>'


def access_summary(e, ds) -> str:
    ready = ready_count(ds)
    keyless = sum(d.approval == "없음" for d in ds)
    check = len(ds) - ready
    parts = [f"<b>{ready}</b>개는 오늘 바로 받을 수 있습니다"]
    if keyless:
        parts.append(f"그중 {keyless}개는 키도 필요 없습니다")
    if check:
        parts.append(f"{check}개는 이용 조건 확인이 필요합니다")
    return f"<p class='access'>{len(ds)}개 중 {', '.join(parts)}.</p>"


# ─── 계보 그림 ───────────────────────────────────────────────────────────────
def lineage_svg(e, lin, names: dict, verdicts: dict, up: str = "") -> str:
    """계보 하나를 다섯 열(이슈·정책 → 데이터 → 가공 → 지표 → 분석) 그래프로. 화살표는 inputs 를 따른다."""
    cols: list[list] = [[] for _ in range(5)]
    for s in lin.steps:
        cols[KIND_COL[s.kind]].append(s)
    cases = sorted({c for s in lin.steps for c in s.used_by})
    for c in cases:
        cols[4].append(c)
    cw, nh, gap, top = 196, 40, 12, 30
    w = cw * 5
    rows = max(len(c) for c in cols) or 1
    h = top + rows * (nh + gap) + 6
    pos: dict[str, tuple[float, float]] = {}
    nodes = []
    for ci, col in enumerate(cols):
        off = (rows - len(col)) * (nh + gap) / 2
        for ri, s in enumerate(col):
            x, y = ci * cw + 8, top + off + ri * (nh + gap)
            if ci == 4:
                key, label, cls, tip = f"case:{s}", s, "k-case", f"분석 {s}"
                v = verdicts.get(s)
                if v:
                    cls += f" v-{v}"
                href = f"{up}answers/{s}.html" if v else None
            else:
                key = s.id
                label = names.get(s.id) or s.title
                cls = f"k-{s.kind} s-{s.status}"
                tip = (
                    f"{label}"
                    + (f" — {s.note}" if s.note else "")
                    + (f" ({s.date})" if s.date else "")
                )
                href = None
            pos[key] = (x, y)
            short = label if len(label) <= 15 else label[:14] + "…"
            body = (
                f'<rect x="{x}" y="{y}" width="{cw - 26}" height="{nh}" rx="8"/>'
                f'<text x="{x + 10}" y="{y + nh / 2 + 4.5}">{e(short)}</text><title>{e(tip)}</title>'
            )
            node = f'<g class="node {cls}">{body}</g>'
            if href:
                node = f'<a href="{e(href)}">{node}</a>'
            nodes.append(node)
    edges = []
    for s in lin.steps:
        for i in s.inputs:
            if i in pos and s.id in pos:
                edges.append((pos[i], pos[s.id]))
        for c in s.used_by:
            if f"case:{c}" in pos and s.id in pos:
                edges.append((pos[s.id], pos[f"case:{c}"]))
    paths = []
    for (x1, y1), (x2, y2) in edges:
        a = (x1 + cw - 26, y1 + nh / 2)
        b = (x2, y2 + nh / 2)
        mx = (a[0] + b[0]) / 2
        paths.append(
            f'<path d="M{a[0]:.0f},{a[1]:.0f} C{mx:.0f},{a[1]:.0f} {mx:.0f},{b[1]:.0f} {b[0]:.0f},{b[1]:.0f}"/>'
        )
    heads = "".join(
        f'<text class="col" x="{i * cw + 8}" y="16">{t}</text>' for i, t in enumerate(COL_TITLE)
    )
    return (
        f'<div class="lin-wrap"><svg class="lin-svg" viewBox="0 0 {w} {h}" role="img" '
        f'aria-label="{e(lin.title)} 계보: 단계 {len(lin.steps)}개">{heads}'
        f'<g class="edges">{"".join(paths)}</g>{"".join(nodes)}</svg></div>'
    )


# ─── 대시보드: 이벤트 스터디 그림 ────────────────────────────────────────────
def chart_result(a: dict) -> dict | None:
    """대시보드에 그릴 결과(주 지표 우선, 시점별 계수가 있는 것)."""
    for r in a.get("results", []):
        if r.get("coefs"):
            return r
    return None


def event_chart(e, a: dict, r: dict | None = None, compact: bool = False) -> str:
    """시점별 계수와 구간: 점 = 계수, 세로선 = 95% 구간, 0선, 정책 시작 점선. 마우스를 올리면 값."""
    r = r or chart_result(a)
    if not r:
        return ""
    from core.report.interpret import is_log as _is_log

    is_log = _is_log(r.get("col") or "", r.get("unit"))

    def tx(v):
        if v is None or not math.isfinite(v):
            return None
        return (math.exp(v) - 1) * 100 if is_log else v

    pts = []
    for c in r["coefs"]:
        k, b, lo, hi = (
            c.get("rel_time"),
            tx(c.get("coef")),
            tx(c.get("ci_low")),
            tx(c.get("ci_high")),
        )
        if k is None or b is None:
            continue
        pts.append((int(k), b, lo if lo is not None else b, hi if hi is not None else b))
    if len(pts) < 2:
        return ""
    pts.sort()
    ks = [p[0] for p in pts]
    vals = [v for p in pts for v in p[1:]] + [0.0]
    y0, y1 = min(vals), max(vals)
    pad = (y1 - y0) * 0.12 or 1
    y0, y1 = y0 - pad, y1 + pad
    w, h = (720, 240) if not compact else (420, 170)
    L, R, T, B = 48, 12, 14, 26
    kmin, kmax = min(ks), max(ks)

    def X(k):
        return L + (k - kmin + 0.5) / (kmax - kmin + 1) * (w - L - R)

    def Y(v):
        return T + (y1 - v) / (y1 - y0) * (h - T - B)

    unit = "%" if is_log else (" " + r["unit"] if r.get("unit") else "")
    fmt = (lambda v: f"{v:+.1f}%") if is_log else (lambda v: f"{v:+.3g}{unit}")
    start = X(-0.5)
    shade = f'<rect class="post" x="{start:.1f}" y="{T}" width="{w - R - start:.1f}" height="{h - T - B}"/>'
    grid = []
    for v in _ticks(y0, y1):
        grid.append(
            f'<line class="grid" x1="{L}" x2="{w - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>'
            f'<text class="tick" x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{fmt(v) if v else "0"}</text>'
        )
    xt = "".join(
        f'<text class="tick" x="{X(k):.1f}" y="{h - 8}" text-anchor="middle">{k}</text>'
        for k in ks
        if len(ks) <= 14 or k % 2 == 0
    )
    marks = []
    for k, b, lo, hi in pts:
        post = "post-pt" if k >= 0 else "pre-pt"
        tip = f"정책 기준 {k:+d}기: {fmt(b)} (구간 {fmt(lo)} ~ {fmt(hi)})"
        marks.append(
            f'<g class="pt {post}" data-tip="{e(tip)}" tabindex="0">'
            f'<rect class="hz" x="{X(k) - 12:.1f}" y="{T}" width="24" height="{h - T - B}"/>'
            f'<line class="ci" x1="{X(k):.1f}" x2="{X(k):.1f}" y1="{Y(lo):.1f}" y2="{Y(hi):.1f}"/>'
            f'<circle cx="{X(k):.1f}" cy="{Y(b):.1f}" r="4.5"/><title>{e(tip)}</title></g>'
        )
    few = any("처치 단위" in w for w in r.get("why", []))
    note = "구간별 세로선은 참고용입니다(처치 단위가 적어 실제 불확실성은 더 큼). " if few else ""
    cap = (
        f"<figcaption><b>{e(r['name'])}</b> <span class='muted small'>정책 시작 전후 시점별 차이"
        f"{'(%)' if is_log else ''}. {note}0선에 가까울수록 차이 없음.</span></figcaption>"
    )
    return (
        f'<figure class="es">{cap}<svg viewBox="0 0 {w} {h}" role="img" aria-label="{e(r["name"])} 시점별 효과">'
        f"{shade}{''.join(grid)}"
        f'<line class="zero" x1="{L}" x2="{w - R}" y1="{Y(0):.1f}" y2="{Y(0):.1f}"/>'
        f'<line class="start" x1="{start:.1f}" x2="{start:.1f}" y1="{T}" y2="{h - B}"/>'
        f'<text class="tick" x="{start + 4:.1f}" y="{T + 11}">정책 시작</text>'
        f"{''.join(marks)}{xt}</svg></figure>"
    )


def _ticks(lo: float, hi: float, n: int = 4) -> list[float]:
    span = hi - lo
    if span <= 0:
        return [0.0]
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=raw)
    start = math.ceil(lo / step) * step
    out, v = [], start
    while v <= hi + 1e-12:
        out.append(round(v, 10))
        v += step
    if 0 not in out and lo < 0 < hi:
        out.append(0.0)
    return sorted(out)


def kpis(e, mine: list[dict], n_data: int, ready: int) -> str:
    vc = {"identified": 0, "conditional": 0, "not_identified": 0}
    for a in mine:
        vc[a["verdict"]] = vc.get(a["verdict"], 0) + 1
    tiles = [
        (len(mine), "분석", ""),
        (vc["identified"], "효과 근거 있음", "k-go"),
        (vc["conditional"], "크기를 판별하지 못함", "k-warn"),
        (vc["not_identified"], "판단 불가", "k-stop"),
        (f"{ready}/{n_data}", "오늘 받을 수 있는 데이터", ""),
    ]
    return (
        '<div class="kpis">'
        + "".join(
            f'<div class="kpi {c}"><span class="v">{v}</span><span class="l">{e(lab)}</span></div>'
            for v, lab, c in tiles
        )
        + "</div>"
    )


def supply(topics, issues, datasets, lineages, answers, legal_fetched: str = "") -> dict:
    """성과 화면의 '흐름 완성도와 데이터 접근성'."""
    from datetime import date

    st = {t.id: topic_stages(t, issues, datasets, lineages, answers) for t in topics}
    filled = {k: sum(1 for x in v.values() if x) for k, v in st.items()}
    used = {s.ref for lin in lineages for s in lin.steps if s.kind == "dataset" and s.ref}
    issue_topics = {i.topic for i in issues}
    age = None
    if legal_fetched:
        try:
            age = (date.today() - date.fromisoformat(legal_fetched)).days
        except ValueError:
            age = None
    return {
        "topics": len(topics),
        "complete": sum(v == 5 for v in filled.values()),
        "avg_stages": round(sum(filled.values()) / max(len(filled), 1), 1),
        "issues": len(issue_topics),
        "issues_with_dashboard": sum(1 for t in issue_topics if st.get(t, {}).get("dashboard")),
        "datasets": len(datasets),
        "ready": ready_count(datasets),
        "in_lineage": sum(d.id in used for d in datasets),
        "legal_age": age,
        "by_topic": st,
    }
