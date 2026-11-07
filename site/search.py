"""통합 검색 — "뉴스에서 본 그 정책, 진짜 효과였나?"를 한 번에 찾는다.

검색 대상 (api/search.json, 사이트 빌드 때 만들어짐)
  result   분석 결과(판정 포함)      → answers/<케이스>.html
  project  결과 전 참여자 프로젝트    → GitHub 폴더
  issue    지금 이슈인 정책           → issues.html#<id>
  topic    주제(이슈 보드)            → topics/<id>.html
  law      주제의 근거 법률           → topics/<id>.html#s-issue
  dataset  공공데이터                 → 원본 데이터 페이지
  lineage  데이터 계보                → lineage.html#<id>

검색은 브라우저 안에서만 한다(search.js). 서버가 없고 검색어를 저장하지 않는다.
이용 통계가 켜진 사이트에서만 다듬은 검색어(숫자·이메일·주소 제거, 30자)를 GoatCounter 이벤트 'q-…'로 센다.
결과가 없던 검색어는 'q0-…' — 다음에 분석할 주제의 후보가 된다 (성과 화면).
"""

from __future__ import annotations

import json

REPO = "https://github.com/CausalInferenceLab/policy-effect-analytics-agent"
TYPE_KO = {
    "result": "분석 결과",
    "project": "진행 중인 분석",
    "issue": "지금 이슈",
    "topic": "주제",
    "law": "근거 법률",
    "dataset": "공공데이터",
    "lineage": "데이터 계보",
}


def _j(*parts) -> str:
    return " ".join(str(p) for p in parts if p)


def index(topics, issues, datasets, answers, projects, lineages) -> list[dict]:
    """검색 항목 목록. kw 는 찾는 데만 쓰는 글(화면에 안 보임)."""
    from answers import DESCRIPTIVE_LABEL, VERDICT, card_line

    from core.discovery.links import dataset_users, is_auto

    tname = {t.id: t.name for t in topics}
    tkw = {t.id: list(t.keywords) for t in topics}
    out: list[dict] = []
    done = {a["case"] for a in answers}
    for a in answers:
        desc = a.get("execution_kind") == "descriptive_only"
        lab, cls = (DESCRIPTIVE_LABEL, "info") if desc else VERDICT.get(a["verdict"], ("-", "warn"))
        out.append(
            {
                "t": "result",
                "title": a["title"],
                "sub": card_line(a),
                "url": a["page"],
                "topic": a["topic"],
                "badge": lab,
                "cls": cls,
                "who": "멘토 예시" if a["mentor"] else f"@{a['owner']}",
                "kw": _j(a["question"], tname.get(a["topic"]), a["owner"], a["case"]),
            }
        )
    for p in projects:
        if p["case"] in done or p.get("mentor"):
            continue
        out.append(
            {
                "t": "project",
                "title": p["title"],
                "sub": p.get("question") or "아직 결과 전인 분석입니다.",
                "url": f"{REPO}/tree/main/cases/{p['case']}",
                "topic": p.get("topic"),
                "who": f"@{p['owner']}",
                "kw": _j(tname.get(p.get("topic")), p["owner"], p["case"]),
            }
        )
    for i in issues:
        out.append(
            {
                "t": "issue",
                "title": i.name,
                "sub": i.issue,
                "url": f"issues.html#{i.id}",
                "topic": i.topic,
                "badge": f"시행 {i.effective}",
                "kw": _j(i.treatment, " ".join(i.outcomes), tname.get(i.topic)),
            }
        )
    for t in topics:
        out.append(
            {
                "t": "topic",
                "title": t.name,
                "sub": getattr(t, "question", "") or "",
                "url": f"topics/{t.id}.html",
                "topic": t.id,
                "kw": _j(" ".join(t.keywords)),
            }
        )
        for law in (t.legal.laws if t.legal else []) + (t.legal.admin_rules if t.legal else []):
            out.append(
                {
                    "t": "law",
                    "title": law,
                    "sub": f"{t.name} 주제의 근거 법령·행정규칙 (법제처 자동 수집)",
                    "url": f"topics/{t.id}.html#s-issue",
                    "topic": t.id,
                    "kw": "",
                }
            )
    users = dataset_users(datasets)
    for d in datasets:
        n = len(users.get(d.id, []))
        out.append(
            {
                "t": "dataset",
                "title": d.name,
                "sub": _j(d.provider, f"{d.space} × {d.time}", f"분석 {n}개에 쓰임" if n else ""),
                "url": d.url,
                "topic": d.topics[0] if d.topics else None,
                "topics": d.topics,
                "badge": {"treatment": "처치", "outcome": "결과", "covariate": "통제"}.get(
                    d.roles[0], ""
                ),
                "kw": _j(" ".join(d.measures), " ".join(tname.get(x, "") for x in d.topics)),
            }
        )
    for lin in lineages:
        out.append(
            {
                "t": "lineage",
                "title": lin.title,
                "sub": ("plan.yaml 에서 그린 자동 계보" if is_auto(lin) else "직접 쓴 계보")
                + f" · 단계 {len(lin.steps)}개",
                "url": f"lineage.html#{lin.id}",
                "topic": lin.topic,
                "kw": _j(lin.question, " ".join(s.title for s in lin.steps)),
            }
        )
    return [{**x, "tk": " ".join(tkw.get(x.get("topic"), []))} for x in out]


def write(out_dir, items: list[dict]) -> None:
    (out_dir / "api").mkdir(exist_ok=True)
    (out_dir / "api" / "search.json").write_text(
        json.dumps(items, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )


EXAMPLES = [
    "토지거래허가구역",
    "기후동행카드",
    "출산지원금",
    "지역화폐",
    "녹색교통",
    "대형마트 의무휴업",
]


def body(e, n_items: int, n_results: int) -> str:
    chips = "".join(
        f'<a class="chip" href="search.html?q={e(x)}" data-q="{e(x)}">{e(x)}</a>' for x in EXAMPLES
    )
    filters = "".join(
        f'<button type="button" class="chip sf" data-t="{k}" aria-pressed="false">{e(v)}</button>'
        for k, v in TYPE_KO.items()
    )
    return f"""
<div class="hero" style="padding-bottom:0"><h1 class="h1-sm">그 정책, 진짜 효과였나?</h1>
<p class="lede">뉴스에서 본 정책 이름·지역·키워드를 넣어 보세요. 이미 확인한 분석 결과와 판정, 쓸 수 있는 공공데이터, 데이터가 이어지는 길(계보)을 한 번에 찾아 드려요.</p>
<form id="sform" class="sbox" role="search" action="search.html">
<label class="sr-only" for="sq">검색어</label>
<input id="sq" name="q" type="search" autocomplete="off" placeholder="예: 토허제 풍선효과, 기후동행카드, 출산지원금" autofocus>
<button class="btn primary" type="submit">찾기</button></form>
<div class="chips" aria-label="예시 검색어">{chips}</div></div>

<section style="padding-top:20px">
<div class="chips" role="group" aria-label="종류로 거르기"><button type="button" class="chip sf" data-t="" aria-pressed="true">전체</button>{filters}</div>
<div id="verdict" class="card s-verdict" hidden></div>
<div id="sres" aria-live="polite"></div>
<div id="snone" class="card" hidden>
<h3 style="margin-top:0">아직 이 질문에 답한 분석이 없어요</h3>
<p>그게 바로 다음 분석 거리예요. 무엇이 궁금한지 남겨 주면 참여자가 데이터부터 찾아봅니다.</p>
<div class="cta"><a id="snone-propose" class="btn primary" data-track="search-propose" href="{REPO}/issues/new?template=case-proposal.yml">이 정책 분석 요청하기</a>
<a id="snone-ask" class="btn ghost" href="index.html#ask">대화창에서 계획 초안 만들기</a>
<a class="btn ghost" href="data.html">데이터 지도 보기</a></div></div>
<p class="muted small" id="sstat">분석 결과 {n_results}개 · 검색 항목 {n_items}개를 이 브라우저 안에서 찾습니다.</p>
<p class="muted small">검색어는 서버에 저장하지 않습니다. 이용 통계가 켜진 경우에만 숫자·이메일·주소를 지운 짧은 검색어(30자)의 <b>횟수</b>를 쿠키 없이 셉니다(GoatCounter, 브라우저의 '추적 안 함'을 따름).
많이 찾았는데 결과가 없던 검색어는 <a href="impact.html#search">성과</a>에 공개되고 다음 분석 주제의 후보가 됩니다.</p>
</section>
<script src="search.js" defer></script>"""
