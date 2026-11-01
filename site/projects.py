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
    "conditional": ("크기를 판별하지 못함", "warn"),
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
    # 단계는 앞에서부터 이어진다: 분석(공통 make flow 또는 자체 report.md)이 없으면 해석도 아직이다
    analysed = (case / "flow_log.json").exists() or (case / "report.md").exists()
    return [
        (case / "plan.yaml").exists() or (case / "analysis-plan.yaml").exists(),
        (case / "fetch.py").exists(),
        analysed,
        analysed and disc.exists() and disc.read_text(encoding="utf-8").strip() != tmpl,
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
    from answers import normalize_descriptive

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
        descriptive, result_error = None, None
        if (case / "flow_log.json").exists():
            try:
                log = json.loads((case / "flow_log.json").read_text(encoding="utf-8"))
                descriptive = normalize_descriptive(log)
                verdict = log.get("verdict")
            except ValueError as exc:
                verdict = None
                result_error = str(exc)
                print(f"건너뜀: {case.name}: {exc}")
        if plan.get("synthetic_data"):
            synthetic = True
        st = stage_of(case)
        if result_error:
            st[2] = False
        rows.append(
            {
                **(
                    {"execution_kind": "descriptive_only", "causal_estimation": "not_run"}
                    if descriptive
                    else {}
                ),
                **({"result_error": result_error} if result_error else {}),
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
                "has_flow": (case / "flow_log.json").exists(),
                "open_prs": prs_by_case.get(case.name, []),
                "registered": case.name in reg,
            }
        )
    return rows


def attach_next_steps(projects: list[dict], answers: list[dict]) -> None:
    """프로젝트마다 '다음 할 일'을 붙인다 (결과 정보가 있어야 해서 load_answers 뒤에 부른다)."""
    from quality import next_steps

    by_case = {a["case"]: a for a in answers}
    for p in projects:
        p["next"] = [] if p["mentor"] else next_steps(p, by_case.get(p["case"]), p["registered"])


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
    if p.get("execution_kind") == "descriptive_only":
        badges.append('<span class="badge info">관측 통계 · 정책 효과 미추정</span>')
    elif p["verdict"]:
        lab, cls = VERDICT.get(p["verdict"], (p["verdict"], "warn"))
        badges.append(f'<span class="badge {cls}" title="파이프라인 자동 판정">{lab}</span>')
    if p["synthetic"]:
        badges.append('<span class="badge stop">시뮬레이션</span>')
    for pr in p["open_prs"]:
        badges.append(
            f'<a class="badge {"" if pr.get("draft") else "info"}" href="{e(pr["url"])}">'
            f"{'Draft ' if pr.get('draft') else '리뷰 중 '}PR #{pr['number']}</a>"
        )
    todo = ""
    if p.get("next"):
        # 아직 결과가 없는 프로젝트는 할 일을 펼쳐 둔다 (참여자가 바로 보도록)
        opened = " open" if not p.get("has_flow") else ""
        todo = (
            f'<details class="todo"{opened}><summary>다음 할 일 '
            f"{len(p['next'])}</summary><ul>"
            + "".join(f"<li>{e(x)}</li>" for x in p["next"])
            + "</ul></details>"
        )
    fig = ""
    if p["figures"]:
        f = next((x for x in THUMB_PREF if x in p["figures"]), p["figures"][0])
        fig = (
            f'<img class="proj-fig" src="{up}cases/{e(p["case"])}/{e(f)}" alt="{e(p["title"])} 그림" '
            'loading="lazy">'
        )
    links = [f'<a href="{REPO}/tree/main/cases/{e(p["case"])}">폴더</a>']
    if p.get("result_error"):
        badges.append(f'<span class="badge stop">{e(p["result_error"])}</span>')
    if p.get("has_flow") and not p.get("result_error"):
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
        + todo
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
    n_res = sum(bool(p.get("has_flow")) for p in mentee)
    cards = "".join(project_card(e, p, tb) for p in mentee)
    mentor_cards = "".join(project_card(e, p, tb) for p in mentor)
    lin_cards = lineage_list(e, lineages, tb)
    verdict_help = (
        "관측 통계는 정책 효과 미추정으로 표시합니다. 효과 추정 사례의 판정은 파이프라인 자동 판정입니다."
        if any(p.get("execution_kind") == "descriptive_only" for p in projects)
        else "판정은 파이프라인의 자동 판정이고, 해석은 각 프로젝트의 discussion.md가 우선합니다."
    )
    return f"""
<div class="hero" style="padding-bottom:0"><h1>참여</h1>
<p class="lede">참여자가 각자 고른 정책을 <b>계획 → 수집 → 분석 → 해석</b> 순서로 진행합니다.
이 화면은 레포의 <code>cases/</code>와 <code>catalog/lineage/</code>에서 자동으로 만들어집니다.
처음이라면 아래 <a href="#join">세 가지 참여 방식</a>과 <a href="{REPO}/blob/main/docs/ops/mentee-guide.md">참여 가이드</a>부터 보세요.</p>
<div class="stats">
<div class="stat"><div class="v">{len(people)}</div><div class="l">참여자</div></div>
<a class="stat" href="#cases"><div class="v">{len(mentee)}</div><div class="l">분석 프로젝트</div></a>
<a class="stat" href="#cases"><div class="v">{n_res}</div><div class="l">분석 결과가 나온 프로젝트</div></a>
<a class="stat" href="#lineages"><div class="v">{len(lineages)}</div><div class="l">데이터 계보</div></a>
</div></div>
{JOIN.format(REPO=REPO)}
{PATH.format(REPO=REPO)}
{pr_list(e, act)}
<section id="cases"><h2>분석 프로젝트 (트랙 B)</h2>
<p class="sub">막대는 진행 단계입니다. {verdict_help}
<b>다음 할 일</b>은 폴더·git 기록에서 자동으로 뽑습니다(한 문장 해석, 교차 재현, 계획 먼저 커밋 등).</p>
<div class="toolbar"><input id="proj-q" type="search" class="search" placeholder="내 GitHub ID나 정책 이름으로 찾기" aria-label="프로젝트 찾기">
<div class="chips" role="group" aria-label="단계 필터">
<button class="chip pf" data-s="-9" aria-pressed="true">전체 {len(mentee)}</button>
<button class="chip pf" data-s="2" aria-pressed="false">분석까지 감</button>
<button class="chip pf" data-s="0" aria-pressed="false">계획·수집 중</button></div></div>
<div class="grid proj-grid" id="proj-cards">{cards or "<p class='card'>아직 없습니다.</p>"}</div></section>
<section id="lineages"><h2>데이터 계보 (트랙 A)</h2>
<p class="sub">이슈 → 정책 → 데이터 → 가공 → 지표의 길입니다. 빈칸은 아직 없는 데이터, 채울 곳입니다.</p>
<div class="grid proj-grid">{lin_cards or "<p class='card'>아직 없습니다.</p>"}</div></section>
<section id="mentor"><h2>멘토 예시</h2><p class="sub">흐름을 보여 주는 예시입니다. 복사해서 시작해도 됩니다.</p>
<div class="grid proj-grid">{mentor_cards}</div></section>
<section><div class="cta"><a class="btn primary" href="{REPO}/issues/new?template=case-proposal.yml">작업 제안 올리기</a>
<a class="btn ghost" href="{REPO}/blob/main/docs/ops/mentee-guide.md">참여 가이드</a></div></section>
<script>{FILTER_JS}</script>"""


PATH = """<section id="path"><h2>내 분석이 사이트에 올라가기까지</h2>
<p class="sub">PR 하나에 한 단계씩. 각 단계가 합쳐질 때마다 아래 내 카드의 막대가 한 칸씩 채워지고, 마지막에는 분석 결과·이슈 보드·README에 자동으로 나와요.</p>
<ol class="path">
<li><b>작업 제안</b><span><a href="{REPO}/issues/new?template=case-proposal.yml">작업 제안 이슈</a>에 트랙·주제를 적어요</span></li>
<li><b>계획</b><span><code>cp -r cases/_template cases/&lt;내ID&gt;-&lt;주제&gt;</code> 후 <code>plan.yaml</code>만 담아 먼저 PR, <code>catalog/projects.yaml</code>에 한 줄</span></li>
<li><b>수집</b><span><code>fetch.py</code>로 <code>data/panel.csv</code> 만들기 (원자료는 커밋하지 않아요)</span></li>
<li><b>분석</b><span><code>make flow CASE=cases/&lt;내ID&gt;-&lt;주제&gt;</code> → 판정·그림·리포트가 생겨요</span></li>
<li><b>해석</b><span><code>discussion.md</code>에 '결과를 한 문장으로'와 한계, <code>make readme</code></span></li>
<li><b>재현받기</b><span>다른 참여자가 돌려 보고 <a href="{REPO}/issues/new?template=reproduction.yml">재현 기록</a>을 남기면 '교차 재현됨' 배지</span></li>
</ol>
<p class="small muted">막히면 <a href="{REPO}/blob/main/docs/ops/mentee-guide.md">참여 가이드</a> · <a href="{REPO}/blob/main/docs/ops/github-onboarding.md">GitHub가 처음이라면</a>. 내 카드만 보려면 주소 끝에 <code>?me=내GitHubID</code>를 붙이세요.</p></section>
"""

JOIN = """<section id="join"><h2>세 가지 참여 방식</h2><p class="sub">커리어 방향과 해 보고 싶은 시도에 따라 하나를 고릅니다. 세 트랙은 이어져 있습니다:
A가 이슈와 데이터를 이으면, B가 그 데이터로 효과를 추정하고, C가 그 결과로 서비스를 만듭니다.</p>
<div class="grid3">
<div class="card"><div class="icon">A</div><h3>데이터 온톨로지</h3><p><b>데이터 온톨로지를 만들고 싶다</b></p>
<p class="muted">공공 이슈와 연결되는 데이터를 찾고 이슈 → 정책 → 원천 데이터 → 가공 → 지표로 이어지는 계보(Lineage)를 만듭니다.</p>
<p class="small">내 작업: <code>catalog/lineage/&lt;내ID&gt;-&lt;주제&gt;.yaml</code>, <code>catalog/datasets.yaml</code></p>
<p class="small"><a href="lineage.html">데이터 계보 보기</a> · <a href="{REPO}/blob/main/docs/tracks/ontology.md">트랙 A 가이드</a></p></div>
<div class="card"><div class="icon">B</div><h3>가설과 분석</h3><p><b>가설 설정과 분석을 익히고 싶다</b></p>
<p class="muted">실제 사례로 가설 → 계획 → 수집 → 추정 → 반증 → 해석의 한 바퀴(Cycle)를 돌며 효과를 추정합니다.</p>
<p class="small">내 작업: <code>cases/&lt;내ID&gt;-&lt;주제&gt;/</code></p>
<p class="small"><a href="architecture.html#how">여섯 단계 보기</a> · <a href="{REPO}/blob/main/docs/tracks/analysis.md">트랙 B 가이드</a></p></div>
<div class="card"><div class="icon">C</div><h3>서비스 개발</h3><p><b>서비스를 개발하고 싶다</b></p>
<p class="muted">분석 Cycle에서 나온 데이터(공개 API)로 웹·앱 서비스를 만듭니다. 합쳐지면 이 사이트에서 바로 열립니다.</p>
<p class="small">내 작업: <code>apps/&lt;내ID&gt;-&lt;서비스&gt;/</code></p>
<p class="small"><a href="apps.html">서비스와 API 보기</a> · <a href="{REPO}/blob/main/docs/tracks/service.md">트랙 C 가이드</a></p></div>
</div><div class="cta"><a class="btn primary" href="{REPO}/blob/main/docs/ops/mentee-guide.md">참여 가이드</a>
<a class="btn ghost" href="{REPO}/issues/new?template=case-proposal.yml">작업 제안 올리기</a>
<a class="btn ghost" href="{REPO}/blob/main/docs/ops/github-onboarding.md">GitHub가 처음이라면</a>
<a class="btn ghost" href="{REPO}/issues?q=label%3Afrom-site">올라온 질문 보기</a></div></section>"""

FILTER_JS = """
(()=>{let s=-9;const q=document.getElementById('proj-q');
const apply=()=>{const t=(q.value||'').trim().toLowerCase();
  document.querySelectorAll('#proj-cards .proj').forEach(c=>{const st=+c.dataset.stage;
    const okS = s===-9 ? true : (s===2 ? st>=2 : st<2);
    c.hidden = !okS || (!!t && !c.textContent.toLowerCase().includes(t));});};
document.querySelectorAll('.pf').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('.pf').forEach(x=>x.setAttribute('aria-pressed',x===b));s=+b.dataset.s;apply();}));
q.addEventListener('input',apply);
const me=new URLSearchParams(location.search).get('me');if(me){q.value=me;apply();}})();
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


# ─── 홈: 시민 데이터 과학자들이 만든 것 ───────────────────────────────────────
STAGE_KO = ["계획", "수집", "분석", "해석"]
THUMB_PREF = ("raw_trends.png", "event_study.png")


def people(projects, lineages=(), activity: dict | None = None) -> list[str]:
    """함께 만든 사람(GitHub ID). 케이스 담당자 + 계보 작성자 + 열린 PR 작성자. 멘토는 맨 뒤."""
    act = activity if activity is not None else load_activity()
    names = {p["owner"] for p in projects}
    names |= {lin.owner for lin in lineages}
    names |= {pr["user"] for pr in act.get("pulls", []) if not pr["user"].endswith("[bot]")}
    return sorted(names - {MENTOR}, key=str.lower) + ([MENTOR] if MENTOR in names else [])


def showcase(e, projects, answers, topics, crew: list[str], limit: int = 6) -> str:
    """홈 하이라이트: 그림이 있는 참여자 프로젝트 카드 + 함께 만든 사람들."""
    tb = {t.id: t for t in topics}
    ans = {a["case"]: a for a in answers}
    mentee = [p for p in projects if not p["mentor"]]
    mentee.sort(key=lambda p: (p["case"] not in ans, not p["figures"], -p["stage"], p["title"]))
    cards = []
    for p in mentee[:limit]:
        t = tb.get(p["topic"])
        a = ans.get(p["case"])
        fig = next(
            (f for f in THUMB_PREF if f in p["figures"]), p["figures"][0] if p["figures"] else None
        )
        thumb = (
            f'<img src="cases/{e(p["case"])}/{e(fig)}" alt="" loading="lazy">'
            if fig
            else f'<span class="ph" aria-hidden="true">{e((t.name if t else p["title"])[:2])}</span>'
        )
        if a:
            from answers import DESCRIPTIVE_LABEL, VERDICT

            lab, cls = (
                (DESCRIPTIVE_LABEL, "info")
                if a.get("execution_kind") == "descriptive_only"
                else VERDICT.get(a["verdict"], ("-", "warn"))
            )
            state = f'<span class="badge {cls}">{e(lab)}</span>'
            href = f"answers/{p['case']}.html"
        else:
            st = STAGE_KO[p["stage"]] if p["stage"] >= 0 else "준비"
            state = f'<span class="badge plain">{e(st)} 단계 진행 중</span>'
            href = f"{REPO}/tree/main/cases/{p['case']}"
        cards.append(
            f'<a class="show" href="{e(href)}"><span class="thumb">{thumb}</span>'
            f'<span class="show-body"><span class="who">{avatar(e, p["owner"])}@{e(p["owner"])}</span>'
            f"<b>{e(p['title'])}</b>"
            f'<span class="show-meta">{state}<span class="muted small">{e(t.name) if t else "주제 미지정"}</span></span></span></a>'
        )
    faces = "".join(
        f'<a href="https://github.com/{e(n)}" title="@{e(n)}{" (멘토)" if n == MENTOR else ""}">'
        f'<img src="https://github.com/{e(n)}.png?size=80" alt="@{e(n)}" loading="lazy" width="40" height="40"></a>'
        for n in crew
    )
    return f"""<section id="showcase"><div class="sec-head"><h2>시민 데이터 과학자들이 만든 것</h2>
<a class="more" href="projects.html">프로젝트 {len(mentee)}개 모두</a></div>
<p class="sub">현업 개발자·분석가들이 각자 궁금했던 정책을 골라 공공데이터로 직접 비교했어요. 그림을 누르면 결과와 인용문, 따라 하는 법이 나와요.</p>
<div class="shows">{"".join(cards)}</div>
<div class="crew"><div class="faces">{faces}</div><p class="muted small">함께 만든 사람 {len(crew)}명. 여러분 자리도 비워 뒀어요 → <a href="projects.html#join">참여하기</a></p></div></section>"""


def personas(e, n_answers: int, n_data: int) -> str:
    """처음 온 사람을 위한 세 갈래 안내."""
    items = [
        (
            "궁금한 시민",
            "뉴스에서 본 그 정책, 효과 있었는지 쉬운 말로 알고 싶어요",
            "#ask",
            "대화창에 물어보기",
        ),
        (
            "기자 · 공무원 · 연구자",
            f"공공데이터로 확인된 답을 인용하고 싶어요. 판정과 인용문이 붙은 결과 {n_answers}개",
            "results.html",
            "분석 결과 보기",
        ),
        (
            "분석가 · 개발자",
            f"직접 돌려 보고 기여하고 싶어요. 정리된 공공데이터 {n_data}개와 재현 코드",
            "projects.html#join",
            "참여 방법 보기",
        ),
    ]
    cards = "".join(
        f'<a class="persona" href="{href}"><span class="tag">{e(who)}</span><b>{e(need)}</b><span class="go-link">{e(cta)}</span></a>'
        for who, need, href, cta in items
    )
    return f"""<section id="start"><h2>처음 오셨나요? 이렇게 시작하세요</h2>
<div class="personas">{cards}</div>
<p class="promise"><b>이 사이트의 약속.</b> 결과는 공식 평가가 아니라 공개 데이터로 다시 확인할 수 있는 비교예요. 데이터가 모르면 '판단 불가'라고 말하고, 숫자가 어떻게 나왔는지 코드까지 전부 공개해요.</p></section>"""
