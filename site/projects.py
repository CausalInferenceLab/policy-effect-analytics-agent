"""참여자 프로젝트 — cases/·catalog/lineage/ 와 (있으면) 열린 PR·작업 제안을 한 화면에 모은다.

- 명단: catalog/projects.yaml (케이스 → 담당자·트랙·주제·작업 제안 이슈). 명단에 없는 케이스도 '주제 미지정'으로 보인다.
- 진행 단계: 폴더 안 파일로 판단한다 — plan.yaml → 계획 · fetch.py → 수집 · flow_log.json → 분석 · discussion.md → 해석.
- 열린 PR·작업 제안: scripts/refresh_activity.py 가 Actions 에서 받아 둔 data/cache/activity.json (없으면 생략).
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "cases"
REPO = "https://github.com/CausalInferenceLab/policy-effect-analytics-agent"
ACTIVITY = ROOT / "data" / "cache" / "activity.json"
MENTOR = "jsshin2022"
STAGES = ["계획", "수집", "분석", "해석"]
TRACK_KO = {"A": "데이터 온톨로지", "B": "가설과 분석", "C": "서비스 개발"}
VERDICT = {
    "identified": ("효과 근거 있음", "go"),
    "conditional": ("조건부", "warn"),
    "not_identified": ("판단 불가", "stop"),
}


def load_registry() -> dict[str, dict]:
    f = ROOT / "catalog" / "projects.yaml"
    if not f.exists():
        return {}
    return {p["case"]: p for p in yaml.safe_load(f.read_text(encoding="utf-8"))["projects"]}


def _template_discussion() -> str:
    f = CASES / "_template" / "discussion.md"
    return f.read_text(encoding="utf-8").strip() if f.exists() else ""


def _plan(case: Path) -> dict:
    for name in ("plan.yaml", "analysis-plan.yaml"):
        f = case / name
        if f.exists():
            try:
                return yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                return {}
    return {}


def stage_of(case: Path) -> list[bool]:
    tmpl = _template_discussion()
    disc = case / "discussion.md"
    return [
        (case / "plan.yaml").exists() or (case / "analysis-plan.yaml").exists(),
        (case / "fetch.py").exists(),
        (case / "flow_log.json").exists(),
        disc.exists() and disc.read_text(encoding="utf-8").strip() != tmpl,
    ]


def load_activity() -> dict:
    if not ACTIVITY.exists():
        return {}
    try:
        return json.loads(ACTIVITY.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def load_projects() -> list[dict]:
    """케이스 폴더마다 한 행. README 나 plan 이 있는 폴더만 (빈 폴더·_ 로 시작하는 폴더 제외)."""
    reg = load_registry()
    act = load_activity()
    prs_by_case: dict[str, list[dict]] = {}
    for pr in act.get("pulls", []):
        for c in pr.get("cases", []):
            prs_by_case.setdefault(c, []).append(pr)
    rows = []
    for case in sorted(p for p in CASES.iterdir() if p.is_dir() and not p.name.startswith("_")):
        if not ((case / "README.md").exists() or (case / "plan.yaml").exists()):
            continue
        meta = reg.get(case.name, {})
        plan = _plan(case)
        verdict = synthetic = None
        if (case / "flow_log.json").exists():
            try:
                verdict = json.loads((case / "flow_log.json").read_text(encoding="utf-8")).get(
                    "verdict"
                )
            except ValueError:
                verdict = None
        if plan.get("synthetic_data"):
            synthetic = True
        st = stage_of(case)
        rows.append(
            {
                "case": case.name,
                "title": plan.get("title") or case.name,
                "question": (plan.get("question") or "").strip(),
                "owner": meta.get("owner") or case.name.split("-")[0],
                "track": meta.get("track", "B"),
                "topic": meta.get("topic"),
                "issue": meta.get("issue"),
                "mentor": bool(meta.get("mentor")),
                "stages": st,
                "stage": max((i for i, ok in enumerate(st) if ok), default=-1),
                "verdict": verdict,
                "synthetic": bool(synthetic),
                "figures": sorted(f.name for f in (case / "figures").glob("*.png"))
                if (case / "figures").is_dir()
                else [],
                "has_report": (case / "report.md").exists(),
                "open_prs": prs_by_case.get(case.name, []),
            }
        )
    return rows


# ─── 그리기 ───────────────────────────────────────────────────────────────────
def stage_bar(e, stages: list[bool]) -> str:
    items = "".join(
        f'<li class="{"done" if ok else ""}"><span>{e(name)}</span></li>'
        for name, ok in zip(STAGES, stages, strict=True)
    )
    return f'<ol class="stages" aria-label="진행 단계">{items}</ol>'


def avatar(e, owner: str) -> str:
    return (
        f'<img class="avatar" src="https://github.com/{e(owner)}.png?size=64" alt="" loading="lazy" '
        f'width="32" height="32">'
    )


def project_card(e, p: dict, topics_by_id: dict, up: str = "") -> str:
    topic = topics_by_id.get(p["topic"])
    topic_html = (
        f'<a href="{up}topics/{e(topic.id)}.html">{e(topic.name)}</a>' if topic else "주제 미지정"
    )
    badges = []
    if p["verdict"]:
        lab, cls = VERDICT.get(p["verdict"], (p["verdict"], "warn"))
        badges.append(f'<span class="badge {cls}" title="파이프라인 자동 판정">{lab}</span>')
    if p["synthetic"]:
        badges.append('<span class="badge stop">시뮬레이션</span>')
    for pr in p["open_prs"]:
        badges.append(
            f'<a class="badge {"" if pr.get("draft") else "info"}" href="{e(pr["url"])}">'
            f"{'Draft ' if pr.get('draft') else '리뷰 중 '}PR #{pr['number']}</a>"
        )
    fig = ""
    if p["figures"]:
        f = "event_study.png" if "event_study.png" in p["figures"] else p["figures"][0]
        fig = (
            f'<img class="proj-fig" src="{up}cases/{e(p["case"])}/{e(f)}" alt="{e(p["title"])} 그림" '
            'loading="lazy">'
        )
    links = [f'<a href="{REPO}/tree/main/cases/{e(p["case"])}">폴더</a>']
    if p["stages"][2]:
        links.insert(0, f'<a href="{up}answers/{e(p["case"])}.html"><b>결과 보기</b></a>')
    if p["has_report"]:
        links.append(f'<a href="{REPO}/blob/main/cases/{e(p["case"])}/report.md">리포트</a>')
    if p["issue"]:
        links.append(f'<a href="{REPO}/issues/{int(p["issue"])}">작업 제안 #{int(p["issue"])}</a>')
    return (
        f'<article class="card proj" data-stage="{p["stage"]}" data-topic="{e(p["topic"] or "")}">'
        f'<div class="proj-head">{avatar(e, p["owner"])}<div><a class="who" href="https://github.com/{e(p["owner"])}">@{e(p["owner"])}</a>'
        f'<div class="muted small">트랙 {e(p["track"])} · {topic_html}</div></div></div>'
        f"<h3>{e(p['title'])}</h3>{stage_bar(e, p['stages'])}"
        + (f'<div class="tags">{"".join(badges)}</div>' if badges else "")
        + fig
        + f'<p class="small proj-links">{" · ".join(links)}</p></article>'
    )


def pr_list(e, act: dict) -> str:
    pulls, props = act.get("pulls", []), act.get("proposals", [])
    if not pulls and not props:
        return ""
    rows = "".join(
        f'<li>{avatar(e, pr["user"])}<div><a href="{e(pr["url"])}"><b>#{pr["number"]}</b> {e(pr["title"])}</a>'
        f'<div class="muted small">@{e(pr["user"])} · {"Draft" if pr.get("draft") else "리뷰 대기"} · {e(pr["updated"][:10])}</div></div></li>'
        for pr in pulls
    )
    prop_rows = "".join(
        f'<li>{avatar(e, it["user"])}<div><a href="{e(it["url"])}"><b>#{it["number"]}</b> {e(it["title"])}</a>'
        f'<div class="muted small">@{e(it["user"])} · 작업 제안</div></div></li>'
        for it in props
    )
    when = e(act.get("fetched_at", "")[:16].replace("T", " "))
    return f"""<section id="activity"><h2>지금 진행 중인 기여</h2>
<p class="sub">열린 PR과 작업 제안입니다. 합쳐지면 아래 프로젝트 카드에 반영됩니다. (기준 {when} UTC)</p>
<div class="split"><div class="card"><h3>열린 PR {len(pulls)}개</h3><ul class="plain act">{rows or "<li class='muted'>없음</li>"}</ul></div>
<div class="card"><h3>작업 제안 {len(props)}개</h3><ul class="plain act">{prop_rows or "<li class='muted'>없음</li>"}</ul></div></div></section>"""


def lineage_list(e, lineages, topics_by_id) -> str:
    if not lineages:
        return ""
    items = []
    for lin in lineages:
        n_missing = sum(s.status == "missing" for s in lin.steps)
        n_planned = sum(s.status == "planned" for s in lin.steps)
        t = topics_by_id.get(lin.topic)
        extra = []
        if n_planned:
            extra.append(f'<span class="badge info">계획 {n_planned}</span>')
        if n_missing:
            extra.append(f'<span class="badge warn">빈칸 {n_missing}</span>')
        items.append(
            f'<article class="card proj"><div class="proj-head">{avatar(e, lin.owner)}<div>'
            f'<a class="who" href="https://github.com/{e(lin.owner)}">@{e(lin.owner)}</a>'
            f'<div class="muted small">트랙 A · {e(t.name) if t else e(lin.topic)}'
            + (" · 멘토 예시" if lin.owner == MENTOR else "")
            + "</div></div></div>"
            f"<h3>{e(lin.title)}</h3><p class='muted small'>단계 {len(lin.steps)}개</p>"
            + (f'<div class="tags">{"".join(extra)}</div>' if extra else "")
            + f'<p class="small proj-links"><a href="lineage.html#{e(lin.id)}">계보 보기</a> · '
            f'<a href="{REPO}/blob/main/catalog/lineage/{e(lin.id)}.yaml">YAML</a></p></article>'
        )
    return "".join(items)


def projects_body(e, projects, lineages, topics) -> str:
    tb = {t.id: t for t in topics}
    act = load_activity()
    mentee = [p for p in projects if not p["mentor"]]
    mentor = [p for p in projects if p["mentor"]]
    mentee.sort(key=lambda p: (-p["stage"], p["title"]))
    people = {p["owner"] for p in mentee} | {lin.owner for lin in lineages if lin.owner != MENTOR}
    people |= {pr["user"] for pr in act.get("pulls", [])} | {
        it["user"] for it in act.get("proposals", [])
    }
    people.discard(MENTOR)
    n_res = sum(p["stages"][2] for p in mentee)
    cards = "".join(project_card(e, p, tb) for p in mentee)
    mentor_cards = "".join(project_card(e, p, tb) for p in mentor)
    lin_cards = lineage_list(e, lineages, tb)
    return f"""
<div class="hero" style="padding-bottom:0"><span class="eyebrow">참여자 프로젝트</span>
<h1>누가, 어떤 정책을, 어디까지</h1>
<p class="lede">참여자가 각자 고른 정책을 <b>계획 → 수집 → 분석 → 해석</b> 순서로 진행합니다.
이 화면은 레포의 <code>cases/</code>와 <code>catalog/lineage/</code>에서 자동으로 만들어집니다.</p>
<div class="stats">
<div class="stat"><div class="v">{len(people)}</div><div class="l">참여자</div></div>
<a class="stat" href="#cases"><div class="v">{len(mentee)}</div><div class="l">분석 프로젝트</div></a>
<a class="stat" href="#cases"><div class="v">{n_res}</div><div class="l">분석 결과가 나온 프로젝트</div></a>
<a class="stat" href="#lineages"><div class="v">{len(lineages)}</div><div class="l">데이터 계보</div></a>
</div></div>
{pr_list(e, act)}
<section id="cases"><h2>분석 프로젝트 (트랙 B)</h2>
<p class="sub">막대는 진행 단계입니다. 판정은 파이프라인의 자동 판정이고, 해석은 각 프로젝트의 discussion.md가 우선합니다.</p>
<div class="chips" role="group" aria-label="단계 필터">
<button class="chip pf" data-s="-9" aria-pressed="true">전체</button>
<button class="chip pf" data-s="2" aria-pressed="false">분석 결과 있음</button>
<button class="chip pf" data-s="0" aria-pressed="false">계획·수집 중</button></div>
<div class="grid proj-grid" id="proj-cards">{cards or "<p class='card'>아직 없습니다.</p>"}</div></section>
<section id="lineages"><h2>데이터 계보 (트랙 A)</h2>
<p class="sub">이슈 → 정책 → 데이터 → 가공 → 지표의 길입니다. 빈칸은 아직 없는 데이터, 채울 곳입니다.</p>
<div class="grid proj-grid">{lin_cards or "<p class='card'>아직 없습니다.</p>"}</div></section>
<section id="mentor"><h2>멘토 예시</h2><p class="sub">흐름을 보여 주는 예시입니다. 복사해서 시작해도 됩니다.</p>
<div class="grid proj-grid">{mentor_cards}</div></section>
<section><div class="cta"><a class="btn primary" href="{REPO}/issues/new?template=case-proposal.yml">작업 제안 올리기</a>
<a class="btn ghost" href="{REPO}/blob/main/docs/ops/mentee-guide.md">참여 가이드</a></div></section>
<script>{FILTER_JS}</script>"""


FILTER_JS = """
document.querySelectorAll('.pf').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('.pf').forEach(x=>x.setAttribute('aria-pressed',x===b));
  const s=+b.dataset.s;
  document.querySelectorAll('#proj-cards .proj').forEach(c=>{
    const st=+c.dataset.stage;
    c.hidden = s===-9 ? false : (s===2 ? st<2 : st>=2);
  });
}));
"""


def strip(e, projects, topics, limit: int = 6) -> str:
    """홈 화면용: 결과가 나온 순서로 참여자 프로젝트 몇 개."""
    tb = {t.id: t for t in topics}
    mentee = sorted(
        (p for p in projects if not p["mentor"]), key=lambda p: (-p["stage"], p["title"])
    )
    if not mentee:
        return ""
    cards = "".join(project_card(e, p, tb) for p in mentee[:limit])
    return f"""<section id="projects"><h2>참여자 프로젝트</h2>
<p class="sub">참여자가 직접 고른 정책을 분석하고 있습니다. 진행 단계와 자동 판정이 레포에서 바로 반영됩니다.</p>
<div class="grid proj-grid">{cards}</div>
<div class="cta"><a class="btn ghost" href="projects.html">프로젝트 {len(mentee)}개 전체 보기</a></div></section>"""


def by_topic(projects, topic_id: str) -> list[dict]:
    return [p for p in projects if p["topic"] == topic_id]
