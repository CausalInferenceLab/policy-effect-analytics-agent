"""분석 결과 화면 — '그래서 이 정책, 효과 있었나?'에 답하는 사용자용 페이지.

참여자 화면(projects.html)이 '누가 어디까지'를 보여 준다면, 이 화면은 결과를 쓰려는 사람을 위한 것이다.
케이스마다 answers/<케이스>.html 한 장:
  1. 한 줄 답 — 판정을 쉬운 말로 + 작성자 해석(discussion.md 의 '결과를 한 문장으로')
  2. 이렇게 인용하세요 / 이렇게 쓰면 안 됩니다 — 판정에 맞춘 문구와 복사용 인용문
  3. 근거 — 지표별 효과(로그 지표는 %로), 그림, 판정 이유
  4. 쓴 공공데이터 — 출처·이용 조건·받는 곳
  5. 직접 돌려 보기 · 내 지역·정책에 적용하기
  6. 재현 기록 — 실행 시각, 코드·데이터 해시
판정이 '판단 불가'면 숫자를 앞세우지 않는다(인용되면 오해가 생기므로 진단용으로 흐리게 표시).
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "cases"
REPO = "https://github.com/CausalInferenceLab/policy-effect-analytics-agent"
SITE = "https://causalinferencelab.github.io/policy-effect-analytics-agent"

VERDICT = {
    "identified": ("효과 근거 있음", "go"),
    "conditional": ("크기를 판별하지 못함", "warn"),
    "not_identified": ("판단 불가", "stop"),
}
VERDICT_PLAIN = {
    "identified": "비교 대상보다 분명히 달라졌고, 다른 설명(같은 시기 사건·계절·미리 반응)도 걸러졌습니다.",
    "conditional": "추정은 했지만 범위가 0을 포함하거나 조건이 약해, 효과가 있었는지·얼마나인지 말할 수 없습니다.",
    "not_identified": "비교 자체가 성립하지 않아(정책 전부터 다르게 움직였거나 비교 단위가 너무 적음) 숫자를 효과로 읽으면 안 됩니다.",
}
PRIMARY = ' <span class="badge info">주 지표</span>'
LICENSE_KO = {
    "KOGL-1": "공공누리 1유형(출처표시)",
    "KOGL-2": "공공누리 2유형(출처표시·상업 금지)",
    "KOGL-3": "공공누리 3유형(출처표시·변경 금지)",
    "KOGL-4": "공공누리 4유형(출처표시·상업 금지·변경 금지)",
    "synthetic": "시뮬레이션(실데이터 아님)",
    "other": "기타 — 출처 페이지의 이용 조건 확인",
}


# ─── 읽기 ─────────────────────────────────────────────────────────────────────
def _plain(md: str) -> str:
    s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", md)
    s = s.replace("**", "").replace("`", "")
    return re.sub(r"\s+", " ", s).strip()


def _sections(md: str) -> list[tuple[str, str]]:
    """(제목, 본문) 목록. 첫 '## ' 앞의 본문은 제목 '' 로."""
    out, title, buf = [], "", []
    for line in md.splitlines():
        if line.startswith("## "):
            out.append((title, "\n".join(buf)))
            title, buf = line[3:].strip(), []
        elif line.startswith("# "):
            continue
        else:
            buf.append(line)
    out.append((title, "\n".join(buf)))
    return out


def _first_paragraph(body: str) -> str:
    paras, cur = [], []
    for line in body.splitlines():
        if not line.strip():
            if cur:
                paras.append(" ".join(cur))
                cur = []
            continue
        if line.lstrip().startswith((">", "|", "```", "!")):
            continue
        cur.append(line.strip())
    if cur:
        paras.append(" ".join(cur))
    return _plain(paras[0]) if paras else ""


def _bullets(body: str, n: int = 4) -> list[str]:
    items = [_plain(m) for m in re.findall(r"^\s*[-*] (.+)$", body, re.M)]
    return items[:n]


def read_discussion(case: Path) -> dict:
    f = case / "discussion.md"
    tmpl = CASES / "_template" / "discussion.md"
    if not f.exists():
        return {}
    md = f.read_text(encoding="utf-8")
    if tmpl.exists() and md.strip() == tmpl.read_text(encoding="utf-8").strip():
        return {}
    secs = _sections(md)
    tmpl_secs = dict(_sections(tmpl.read_text(encoding="utf-8"))) if tmpl.exists() else {}
    summary = next(
        (
            _first_paragraph(b)
            for t, b in secs
            if "한 문장" in t and b.strip() != (tmpl_secs.get(t) or "").strip()
        ),
        "",
    )
    has_one_line = bool(summary)
    if not summary:
        summary = next((_first_paragraph(b) for t, b in secs if t == "" and b.strip()), "")
    cautions = next((_bullets(b) for t, b in secs if re.search(r"조심|한계|제한", t)), [])
    changed = next((_first_paragraph(b) for t, b in secs if re.search(r"계획.*(바뀐|변경)", t)), "")
    return {
        "summary": summary[:600],
        "has_one_line": has_one_line,
        "cautions": cautions,
        "plan_changed": changed[:500],
    }


def _is_log(col: str, unit: str | None) -> bool:
    return col.startswith("log") or "log" in (unit or "").lower()


def effect_text(est, lo, hi, col: str, unit: str | None) -> tuple[str, str]:
    """(효과, 95% 범위)를 사람이 읽는 말로. 로그 지표는 %, 범위가 너무 넓으면 그렇다고 말한다."""
    if est is None or lo is None or hi is None:
        return "-", "-"
    if _is_log(col, unit):
        if hi - lo > 1.0:
            return f"{(math.exp(est) - 1) * 100:+.1f}%", "범위가 너무 넓어 크기를 말할 수 없음"

        def pct(v):
            return f"{(math.exp(v) - 1) * 100:+.1f}%"

        return pct(est), f"{pct(lo)} ~ {pct(hi)}"
    u = f" {unit}" if unit else ""
    return f"{est:+.3g}{u}", f"{lo:+.3g} ~ {hi:+.3g}{u}"


def bounds_text(lo, hi, col: str, unit: str | None) -> tuple[str, str] | None:
    """배제 진술용 (하한, 상한) 문자열. 범위가 너무 넓으면 None."""
    if lo is None or hi is None:
        return None
    if _is_log(col, unit):
        if hi - lo > 1.0:
            return None
        return f"{(math.exp(lo) - 1) * 100:+.1f}%", f"{(math.exp(hi) - 1) * 100:+.1f}%"
    u = f" {unit}" if unit else ""
    return f"{lo:+.3g}{u}", f"{hi:+.3g}{u}"


def load_answers() -> list[dict]:
    from projects import load_registry
    from quality import prereg

    reg = load_registry()
    try:
        from core.agent.guard import TRIGGER_KO
    except Exception:  # 사이트만 빌드할 때도 동작
        TRIGGER_KO = {}
    rows = []
    for case in sorted(CASES.glob("*/flow_log.json")):
        case = case.parent
        if case.name.startswith("_"):
            continue
        try:
            log = json.loads((case / "flow_log.json").read_text(encoding="utf-8"))
            plan = yaml.safe_load((case / "plan.yaml").read_text(encoding="utf-8")) or {}
        except (ValueError, OSError, yaml.YAMLError):
            continue
        meta = reg.get(case.name, {})
        outs = {o.get("col"): o for o in plan.get("outcomes", [])}
        primary = next((o.get("col") for o in plan.get("outcomes", []) if o.get("primary")), None)
        results = []
        for r in log.get("results", []):
            o = outs.get(r.get("outcome"), {})
            eff, rng = effect_text(
                r.get("estimate"),
                r.get("ci_low"),
                r.get("ci_high"),
                r.get("outcome", ""),
                o.get("unit"),
            )
            results.append(
                {
                    "col": r.get("outcome"),
                    "name": o.get("name", r.get("outcome")),
                    "effect": eff,
                    "range": rng,
                    "p": r.get("p_value"),
                    "verdict": r.get("verdict"),
                    "why": [TRIGGER_KO.get(t, t) for t in r.get("triggers") or []],
                    "n": r.get("n_obs"),
                    "clusters": r.get("n_clusters"),
                    "primary": r.get("outcome") == primary,
                    "bounds": bounds_text(
                        r.get("ci_low"), r.get("ci_high"), r.get("outcome", ""), o.get("unit")
                    ),
                }
            )
        results.sort(key=lambda x: not x["primary"])
        manifest = {}
        if (case / "run_manifest.json").exists():
            try:
                manifest = json.loads((case / "run_manifest.json").read_text(encoding="utf-8"))
            except ValueError:
                manifest = {}
        rows.append(
            {
                "case": case.name,
                "title": plan.get("title", case.name),
                "question": (plan.get("question") or log.get("question") or "").strip(),
                "owner": meta.get("owner") or case.name.split("-")[0],
                "topic": meta.get("topic"),
                "mentor": bool(meta.get("mentor")),
                "synthetic": bool(plan.get("synthetic_data")),
                "verdict": log.get("verdict"),
                "guard": (log.get("guard") or {}).get("narrative", ""),
                "results": results,
                "figures": sorted(f.name for f in (case / "figures").glob("*.png"))
                if (case / "figures").is_dir()
                else [],
                "sources": plan.get("data_sources", []),
                "manifest": manifest,
                "finished": (log.get("ended_at") or "")[:10],
                "page": f"answers/{case.name}.html",
                "reproduced_by": list(meta.get("reproduced_by") or []),
                "prereg": prereg(case),
                **read_discussion(case),
            }
        )
    order = {"identified": 0, "conditional": 1, "not_identified": 2}
    rows.sort(key=lambda a: (a["synthetic"], a["mentor"], order.get(a["verdict"], 3), a["title"]))
    return rows


# ─── 그리기 ───────────────────────────────────────────────────────────────────
def one_line(a: dict) -> str:
    return a.get("summary") or _plain(a.get("guard", "")) or VERDICT_PLAIN.get(a["verdict"], "")


def verdict_chip(e, v: str | None) -> str:
    lab, cls = VERDICT.get(v, (v or "-", "warn"))
    return f'<span class="badge {cls}">{e(lab)}</span>'


def card(e, a: dict, topics_by_id: dict, up: str = "") -> str:
    t = topics_by_id.get(a["topic"])
    line = one_line(a)
    line = line if len(line) <= 140 else line[:138] + "…"
    tags = [verdict_chip(e, a["verdict"])]
    if a["synthetic"]:
        tags.append('<span class="badge stop">시뮬레이션 데이터 결과</span>')
    if a["mentor"]:
        tags.append('<span class="badge">멘토 예시</span>')
    if a.get("reproduced_by"):
        tags.append('<span class="badge go">교차 재현됨</span>')
    if (a.get("prereg") or {}).get("level") == "go":
        tags.append('<span class="badge go">계획 먼저 커밋</span>')
    return (
        f'<a class="card answer" data-verdict="{e(a["verdict"] or "")}" href="{up}{e(a["page"])}">'
        f'<div class="tags">{"".join(tags)}</div><h3>{e(a["title"])}</h3>'
        f'<p class="muted">{e(line)}</p>'
        f'<p class="small muted" style="margin:auto 0 0">{e(t.name) if t else "주제 미지정"} · @{e(a["owner"])}'
        f"{' · ' + e(a['finished']) if a['finished'] else ''}</p></a>"
    )


def rule_out(a: dict) -> str:
    """판별하지 못한 결과에서도 말할 수 있는 것: 95% 범위 밖의 큰 효과는 자료와 맞지 않는다."""
    if a["verdict"] != "conditional":
        return ""
    r = next((r for r in a["results"] if r.get("bounds")), None)
    if not r:
        return ""
    lo, hi = r["bounds"]
    return (
        f"그래도 말할 수 있는 것(배제 범위) — {r['name']}: {hi}보다 큰 증가나 {lo}보다 큰 감소는 "
        "이 자료와 맞지 않습니다(설계 가정이 맞다는 전제)."
    )


def trust_block(e, a: dict) -> str:
    from quality import checks

    items = "".join(
        f'<li><span class="badge {lvl}">{e(head)}</span> <span class="muted small">{e(txt)}</span></li>'
        for lvl, head, txt in checks(a)
    )
    return f"""<section id="trust"><h2>이 결과를 얼마나 믿을 수 있나</h2>
<p class="sub">판정과 별개로, 기록으로 확인되는 것만 적었습니다. 노란 항목은 결과가 틀렸다는 뜻이 아니라 아직 확인되지 않았다는 뜻입니다.</p>
<ul class="plain trust">{items}</ul>
<p class="small muted">교차 재현을 하셨나요? <a href="{REPO}/issues/new?template=reproduction.yml&amp;title=%5B재현%5D%20{e(a["case"])}">재현 기록 남기기</a></p></section>"""


def _usage(e, a: dict) -> str:
    v = a["verdict"]
    p = next(iter(a["results"]), None)
    eff = ""
    if p:
        rng = p["range"] if p["range"].startswith("범위") else f"95% 범위 {p['range']}"
        eff = f"{p['name']} {p['effect']}, {rng}"
    if v == "identified":
        do = [
            f'"{a["title"]}" — 비교 대상 대비 {eff}. 이 자료와 설계 기준입니다.',
            "같은 지역·기간·지표에 한정해서 말하기",
        ]
        dont = [
            "'정책 때문에 반드시' 같은 단정",
            "다른 지역·시기·지표로 일반화",
        ]
    elif v == "conditional":
        do = [
            '"이 자료로는 효과가 있었는지·얼마나인지 판별하지 못했다."',
            f"범위를 함께 쓰기: {eff}" if p else "추정 범위를 함께 쓰기",
        ]
        ro = rule_out(a)
        if ro:
            do.append(ro)
        dont = ["'효과가 없다' — 판별하지 못한 것과 없는 것은 다릅니다", "추정치 하나만 떼어 인용"]
    else:
        reasons = (
            ", ".join(dict.fromkeys(w for r in a["results"] for w in r["why"])) or "조건 미충족"
        )
        do = [f'"이 설계로는 효과를 판단할 수 없다. 이유: {reasons}."']
        dont = ["표의 숫자·p값 인용 — 진단용입니다", "'효과가 있다' 또는 '없다'"]
    cite = (
        f"{a['title']} — 판정: {VERDICT.get(v, (v,))[0]}. 출처: 정책 효과 분석 플랫폼"
        f"(가짜연구소 인과추론팀 오픈소스), {a['finished'] or '날짜 미상'} 실행, {SITE}/{a['page']} · 공식 평가 아님"
    )
    lis = lambda xs: "".join(f"<li>{e(x)}</li>" for x in xs)  # noqa: E731
    return f"""<section id="use"><h2>이 결과를 쓰려면</h2>
<div class="split"><div class="card"><h3><span class="badge go">이렇게 쓰세요</span></h3><ul>{lis(do)}</ul></div>
<div class="card"><h3><span class="badge stop">이렇게 쓰면 안 됩니다</span></h3><ul>{lis(dont)}</ul></div></div>
<div class="card cite"><div class="row-between"><b>인용문</b><button class="btn ghost small-btn" type="button" data-copy="cite-text">복사</button></div>
<p id="cite-text" class="small" style="margin:8px 0 0">{e(cite)}</p></div></section>"""


def page_body(e, a: dict, topics_by_id: dict, datasets_by_url: dict) -> str:
    t = topics_by_id.get(a["topic"])
    lab, cls = VERDICT.get(a["verdict"], ("-", "warn"))
    hide_numbers = a["verdict"] == "not_identified"
    banner = (
        '<div class="banner stop">시뮬레이션 데이터 결과입니다. 실제 정책 효과가 아니라 분석 과정을 보여 주는 예시입니다.</div>'
        if a["synthetic"]
        else ""
    )
    author = (
        f"<p><b>작성자 해석</b> {e(a['summary'])}</p>"
        if a.get("summary")
        else f'<p class="muted small">작성자 해석은 <a href="{REPO}/blob/main/cases/{e(a["case"])}/discussion.md">discussion.md</a>를 보세요.</p>'
    )
    rows = "".join(
        f"<tr{' class=dim' if hide_numbers else ''}><td>{e(r['name'])}{PRIMARY if r['primary'] else ''}</td>"
        f"<td>{e(r['effect'])}</td><td>{e(r['range'])}</td><td>{verdict_chip(e, r['verdict'])}</td>"
        f"<td class='muted small'>{e(', '.join(r['why']) or '-')}</td></tr>"
        for r in a["results"]
    )
    dim_note = (
        "<p class='small muted'>판단 불가 결과의 숫자는 <b>진단용</b>입니다. 인용하지 마세요.</p>"
        if hide_numbers
        else "<p class='small muted'>로그 지표는 %로 바꿔 보여 줍니다(대조 대비 변화). 95% 범위가 0을 포함하면 '변화 없음'과 구별되지 않습니다.</p>"
    )
    figs = "".join(
        f'<img src="../cases/{e(a["case"])}/{e(f)}" alt="{e(a["title"])} — {e(f)}" loading="lazy">'
        for f in a["figures"][:4]
    )
    cautions = (
        "<ul>" + "".join(f"<li>{e(c)}</li>" for c in a["cautions"]) + "</ul>"
        if a.get("cautions")
        else ""
    )
    changed = (
        f'<div class="banner warn"><b>계획에서 바뀐 것(작성자 기록)</b> {e(a["plan_changed"])}</div>'
        if a.get("plan_changed")
        else ""
    )
    src_rows = []
    for s in a["sources"]:
        url = s.get("url")
        name = f'<a href="{e(url)}">{e(s.get("name", ""))}</a>' if url else e(s.get("name", ""))
        mark = " <span class='badge info'>데이터 지도</span>" if url in datasets_by_url else ""
        src_rows.append(
            f"<tr><td>{name}{mark}<div class='muted small'>{e(s.get('provider', ''))}</div></td>"
            f"<td>{e(LICENSE_KO.get(s.get('license'), s.get('license', '')))}</td></tr>"
        )
    head = "<tr><th>데이터</th><th>이용 조건</th></tr>"
    src_html = f"<div class='tablewrap'><table>{head}{''.join(src_rows[:6])}</table></div>"
    if len(src_rows) > 6:
        src_html += (
            f"<details><summary>나머지 {len(src_rows) - 6}개 출처 보기</summary>"
            f"<div class='tablewrap'><table>{head}{''.join(src_rows[6:])}</table></div></details>"
        )
    m = a.get("manifest") or {}
    sha = (m.get("git_sha") or "")[:7]
    repro = (
        f"<p class='small muted'>실행 {e(a['finished'] or '-')} · 코드 "
        + (f"<a href='{REPO}/commit/{e(m.get('git_sha', ''))}'>{e(sha)}</a>" if sha else "-")
        + f" · 데이터 해시 {e((m.get('data_sha256') or '-')[:12])}"
        + (" · 실행 당시 작업 폴더에 커밋 안 된 변경 있음" if m.get("git_dirty") else "")
        + "</p>"
    )
    return f"""
<div class="hero" style="padding-bottom:0"><span class="eyebrow">분석 결과 · {e(t.name) if t else "주제 미지정"}</span>
<h1 class="h1-sm">{e(a["title"])}</h1>
<p class="lede">{e(a["question"])}</p></div>
{banner}
<section style="padding-top:24px"><div class="card answer-box {cls}">
<div class="answer-verdict"><span class="badge {cls} big">{e(lab)}</span></div>
<p style="margin:10px 0 6px"><b>{e(VERDICT_PLAIN.get(a["verdict"], ""))}</b></p>
{author}
<p class="muted small">자동 요약: {e(_plain(a["guard"]))}</p></div></section>
{_usage(e, a)}
<section id="evidence"><h2>근거</h2>{changed}
<div class="tablewrap"><table><tr><th>결과 지표</th><th>추정 효과</th><th>95% 범위</th><th>판정</th><th>주의</th></tr>{rows}</table></div>
{dim_note}<div class="figs">{figs}</div>
{("<h3>작성자가 적은 한계</h3>" + cautions) if cautions else ""}</section>
{trust_block(e, a)}
<section id="data"><h2>쓴 공공데이터</h2>
{src_html}
<p class="small muted">원자료는 레포에 올리지 않습니다. 아래 명령이 공개 창구에서 직접 받아 같은 결과를 만듭니다. 각 데이터의 단위·받는 법·키 필요 여부는 <a href="../data.html">데이터 지도</a>에 있습니다.</p></section>
<section id="run"><h2>직접 돌려 보기</h2>
<pre class="code"><code>git clone {REPO}.git
cd policy-effect-analytics-agent
pip install -e ".[dev,analysis]"
make flow CASE=cases/{e(a["case"])}</code></pre>
{repro}
<h3>내 지역·정책에 적용하기</h3>
<ol><li>이 폴더를 복사합니다: <code>cp -r cases/{e(a["case"])} cases/&lt;내ID&gt;-&lt;주제&gt;</code></li>
<li><code>plan.yaml</code>의 처치(정책·시작일·대상)와 대조를 바꾸고, <b>데이터를 보기 전에</b> 커밋합니다.</li>
<li><a href="{REPO}/issues/new?template=case-proposal.yml">작업 제안</a>으로 올리면 리뷰 후 이 화면에 같은 형식으로 나옵니다.</li></ol>
<p class="small"><a href="{REPO}/blob/main/cases/{e(a["case"])}/report.md">전체 리포트</a> ·
<a href="{REPO}/tree/main/cases/{e(a["case"])}">분석 폴더</a> · <a href="../results.html">다른 결과</a></p></section>
<script>document.querySelectorAll('[data-copy]').forEach(b=>b.addEventListener('click',()=>{{const t=document.getElementById(b.dataset.copy).textContent;(navigator.clipboard?navigator.clipboard.writeText(t):Promise.reject()).then(()=>{{b.textContent='복사됨'}}).catch(()=>{{b.textContent='직접 선택해 복사하세요'}})}}))</script>"""


def index_body(e, answers: list[dict], topics) -> str:
    tb = {t.id: t for t in topics}
    real = [a for a in answers if not a["synthetic"] and not a["mentor"]]
    examples = [a for a in answers if a["synthetic"] or a["mentor"]]
    legend = "".join(
        f'<div class="card"><h3>{verdict_chip(e, k)}</h3><p class="muted" style="margin:0">{e(VERDICT_PLAIN[k])}</p></div>'
        for k in ("identified", "conditional", "not_identified")
    )
    no_result = [t for t in topics if not any(a["topic"] == t.id for a in answers)]
    gap = ", ".join(f'<a href="topics/{e(t.id)}.html">{e(t.name)}</a>' for t in no_result)
    return f"""
<div class="hero" style="padding-bottom:0"><span class="eyebrow">분석 결과</span>
<h1>그 정책, 효과 있었나 — 지금까지 나온 답</h1>
<p class="lede">공공데이터로 정책을 받은 곳과 안 받은 곳을 비교한 결과입니다. 결과마다 <b>쉬운 말 답, 인용해도 되는 문장, 쓴 데이터, 직접 재현하는 법</b>을 붙였습니다.</p></div>
<section style="padding-top:24px"><h2>판정은 세 가지입니다</h2><div class="grid3">{legend}</div>
<p class="small muted">'판단 불가'도 결과입니다. 왜 판단할 수 없는지가 다음 분석의 출발점이 됩니다.</p></section>
<section id="answers"><h2>참여자 분석 {len(real)}개</h2>
<div class="chips" role="group" aria-label="판정 필터">
<button class="chip af" data-v="" aria-pressed="true">전체</button>
<button class="chip af" data-v="identified" aria-pressed="false">효과 근거 있음</button>
<button class="chip af" data-v="conditional" aria-pressed="false">크기를 판별하지 못함</button>
<button class="chip af" data-v="not_identified" aria-pressed="false">판단 불가</button></div>
<div class="grid proj-grid" id="answer-cards">{"".join(card(e, a, tb) for a in real) or "<p class='card'>아직 없습니다.</p>"}</div></section>
<section><h2>예시</h2><p class="sub">흐름을 보여 주는 멘토 예시입니다.</p>
<div class="grid proj-grid">{"".join(card(e, a, tb) for a in examples)}</div></section>
<section id="reuse"><h2>우리 지역·정책에 같은 분석을 하려면</h2>
<ol><li>위에서 비슷한 결과 하나를 엽니다 — 같은 데이터·설계를 쓰는 것이 가장 빠릅니다.</li>
<li>그 화면 아래 <b>내 지역·정책에 적용하기</b>대로 폴더를 복사하고 <code>plan.yaml</code>의 처치·대조만 바꿉니다.</li>
<li><b>데이터를 보기 전에</b> 계획만 담은 PR을 먼저 올립니다. 결과는 이 화면에 같은 형식으로 나옵니다.</li></ol>
<p class="small muted">코드를 다루지 않는다면 <a href="index.html#ask">질문하기</a>로 남겨 주세요. 참여자가 검토해 분석으로 잇습니다.</p></section>
<section><h2>아직 결과가 없는 주제</h2><p class="sub">{gap or "없음"}</p>
<div class="cta"><a class="btn primary" href="index.html#ask">질문하기</a>
<a class="btn ghost" href="{REPO}/issues/new?template=case-proposal.yml">분석 제안하기</a></div></section>
<script>document.querySelectorAll('.af').forEach(b=>b.addEventListener('click',()=>{{document.querySelectorAll('.af').forEach(x=>x.setAttribute('aria-pressed',x===b));const v=b.dataset.v;document.querySelectorAll('#answer-cards .answer').forEach(c=>{{c.hidden=!!v&&c.dataset.verdict!==v}})}}))</script>"""


def strip(e, answers: list[dict], topics, limit: int = 4) -> str:
    tb = {t.id: t for t in topics}
    real = [a for a in answers if not a["synthetic"] and not a["mentor"]][:limit]
    if not real:
        return ""
    return f"""<section id="answers"><h2>이미 나온 답</h2>
<p class="sub">참여자가 공공데이터로 확인한 결과입니다. 판정과 함께 인용해도 되는 문장, 직접 재현하는 법을 붙였습니다.</p>
<div class="grid proj-grid">{"".join(card(e, a, tb) for a in real)}</div>
<div class="cta"><a class="btn ghost" href="results.html">분석 결과 전체 보기</a></div></section>"""


def catalog(answers: list[dict]) -> list[dict]:
    """대화창(ask.js)용: 주제별로 이미 나온 결과."""
    return [
        {
            "topic": a["topic"],
            "title": a["title"],
            "page": a["page"],
            "verdict": VERDICT.get(a["verdict"], (a["verdict"],))[0],
            "line": one_line(a)[:160],
            "example": a["synthetic"] or a["mentor"],
        }
        for a in answers
    ]
