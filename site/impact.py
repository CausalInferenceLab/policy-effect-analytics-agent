"""성과 화면(impact.html) — 이 사이트가 목표대로 쓰이고 있는지 숫자로 본다.

목표(docs/ops/roadmap.md)와 같은 순서로 네 묶음:
  1. 쓰임      사람들이 결과를 찾고, 가져가고, 질문하나 (방문 통계: GoatCounter, 선택)
  2. 외부 검증  처음 보는 사람이 혼자 찾아 바르게 인용하나 (사용자 과업 테스트 이슈)
  3. 결과의 질  사전 등록 · 교차 재현 · 한 문장 해석 (레포 파일과 git 기록)
  4. 참여      리뷰 · 참여자 · 머지 (GitHub)
숫자는 scripts/refresh_metrics.py 가 Actions 에서 받아 둔 data/cache/metrics.json 과 레포 파일에서 만든다.
측정하지 못한 칸은 0이 아니라 '측정 전'으로 둔다.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache" / "metrics.json"
REPO = "https://github.com/CausalInferenceLab/policy-effect-analytics-agent"

# 사이트 버튼에 붙인 이벤트 (track.js · data-track). 이름이 곧 GoatCounter 경로 'ev-<이름>'
EVENTS = {
    "cite-copy": "인용문 복사",
    "link-copy": "링크 복사",
    "csv-download": "CSV 내려받기",
    "ask": "대화창 질문",
    "propose": "질문을 제안으로 올리기",
    "search": "결과 검색",
    "reproduce": "재현 기록 열기",
    "flow-stage": "홈 흐름 띠의 단계 누름",
}
TAKE = ("cite-copy", "link-copy", "csv-download")


def load() -> dict:
    if not CACHE.exists():
        return {}
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def _week(d: str) -> str:
    x = date.fromisoformat(d)
    return (x - timedelta(days=x.weekday())).isoformat()


def weekly(days: list[str], weeks: int = 12, today: date | None = None) -> list[tuple[str, int]]:
    """날짜 목록 → 최근 n주(월요일 시작)별 개수. 빈 주도 0으로."""
    today = today or date.today()
    start = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks - 1)
    keys = [(start + timedelta(weeks=i)).isoformat() for i in range(weeks)]
    cnt = dict.fromkeys(keys, 0)
    for d in days:
        if d and d >= keys[0]:
            k = _week(d)
            if k in cnt:
                cnt[k] += 1
    return list(cnt.items())


def compute(
    metrics: dict, answers: list[dict], projects: list[dict], supply: dict | None = None
) -> dict:
    """화면과 api/metrics.json 이 함께 쓰는 지표. 측정 못 한 값은 None."""
    g = metrics.get("github") or {}
    use = metrics.get("usage")
    pulls = g.get("pulls", [])
    issues = g.get("issues", [])
    mentee_prs = [p for p in pulls if not p["mentor"] and not p["bot"] and not p["draft"]]
    merged_mentee = [p for p in mentee_prs if p["merged"]]
    tests = [i for i in issues if i["kind"] == "user_test"]
    real = [a for a in answers if not a["mentor"] and not a["synthetic"]]
    people = {p["owner"] for p in projects if not p["mentor"]} | {p["author"] for p in mentee_prs}

    def ev(name):
        return None if not use else use.get("events", {}).get(f"ev-{name}", 0)

    result_views = (
        None
        if not use
        else sum(v for k, v in use.get("pages", {}).items() if "/answers/" in k or "results" in k)
    )
    take = None if not use else sum(ev(k) or 0 for k in TAKE)
    board_views = (
        None if not use else sum(v for k, v in use.get("pages", {}).items() if "/topics/" in k)
    )
    weekly_take = None
    if use and use.get("days"):
        weekly_take = round((take or 0) * 7 / use["days"], 1)
    return {
        "north_star": {"name": "주간 가져간 답", "value": weekly_take},
        "supply": supply or {},
        "measured_at": metrics.get("fetched_at"),
        "usage_on": bool(use),
        "usage_days": (use or {}).get("days"),
        "use": {
            "pageviews": None if not use else use.get("pageviews"),
            "result_views": result_views,
            "board_views": board_views,
            "take": take,
            "events": {k: ev(k) for k in EVENTS},
            "site_questions": sum(i["kind"] == "site_question" for i in issues) if g else None,
        },
        "external": {
            "tests": len(tests) if g else None,
            "passed": sum(bool(i.get("passed")) for i in tests) if g else None,
        },
        "quality": {
            "results": len(real),
            "one_line": sum(bool(a.get("has_one_line")) for a in answers),
            "reproduced": sum(bool(a.get("reproduced_by")) for a in answers),
            "plan_first": sum((a.get("prereg") or {}).get("level") == "go" for a in answers),
            "all": len(answers),
            "reproduction_issues": sum(i["kind"] == "reproduction" for i in issues) if g else None,
        },
        "community": {
            "people": len(people),
            "mentee_prs": len(mentee_prs) if g else None,
            "mentee_merged": len(merged_mentee) if g else None,
            "mentee_reviewed": sum(p["reviews"] > 0 for p in merged_mentee) if g else None,
            "proposals": sum(i["kind"] == "proposal" for i in issues) if g else None,
            "stars": (g.get("repo") or {}).get("stars") if g else None,
            "forks": (g.get("repo") or {}).get("forks") if g else None,
        },
        "weekly": {
            "merged_prs": weekly([p["merged"] for p in pulls if p["merged"]]) if g else [],
            "questions": weekly(
                [i["created"] for i in issues if i["kind"] in ("site_question", "proposal")]
            )
            if g
            else [],
            "pageviews": _weekly_views(use) if use else [],
        },
    }


def _weekly_views(use: dict) -> list[tuple[str, int]]:
    out: dict[str, int] = {}
    for row in use.get("daily", []):
        k = _week(row["day"])
        out[k] = out.get(k, 0) + int(row.get("count") or 0)
    return sorted(out.items())


# ─── 그리기 ───────────────────────────────────────────────────────────────────
def _status(value, target) -> tuple[str, str]:
    if value is None:
        return "측정 전", "info"
    if target is None:
        return "기록", "plain"
    ok = value >= target
    return ("목표 도달", "go") if ok else ("목표 미달", "warn")


def _row(e, name: str, value, target, how: str, fmt=str, target_text: str | None = None) -> str:
    lab, cls = _status(value, target)
    v = "—" if value is None else fmt(value)
    t = target_text or ("—" if target is None else fmt(target))
    return (
        f"<tr><th scope='row'>{e(name)}</th><td class='num'>{e(v)}</td><td class='num muted'>{e(t)}</td>"
        f"<td><span class='badge {cls}'>{e(lab)}</span></td><td class='muted small'>{how}</td></tr>"
    )


def _ratio(a, b):
    return None if a is None or b is None else f"{a}/{b}"


def bars(e, series: list[tuple[str, int]], title: str, unit: str) -> str:
    """주별 막대 하나(단일 계열). 막대마다 hover 설명, 최댓값과 마지막 주에만 숫자."""
    if not series or not any(v for _, v in series):
        return f"<figure class='chart'><figcaption>{e(title)}</figcaption><p class='muted small'>아직 기록이 없습니다.</p></figure>"
    w, h, pad_b, pad_t = 560, 150, 22, 18
    n = len(series)
    slot = w / n
    bw = max(6, slot - 6)
    top = max(v for _, v in series)
    last = n - 1
    peak = max(range(n), key=lambda i: series[i][1])
    out = []
    for i, (wk, v) in enumerate(series):
        bh = 0 if top == 0 else (h - pad_b - pad_t) * v / top
        x = i * slot + (slot - bw) / 2
        y = h - pad_b - bh
        r = min(4, bh / 2, bw / 2)
        if bh > 0:
            out.append(
                f"<path class='bar' d='M{x:.1f},{h - pad_b} V{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
                f"H{x + bw - r:.1f} Q{x + bw:.1f},{y:.1f} {x + bw:.1f},{y + r:.1f} V{h - pad_b} Z'>"
                f"<title>{e(wk)} 주: {v}{e(unit)}</title></path>"
            )
        # 투명한 넓은 영역: 막대가 낮아도 hover 가 잡히게
        out.append(
            f"<rect class='hover-area' x='{i * slot:.1f}' y='{pad_t}' width='{slot:.1f}' height='{h - pad_b - pad_t}'>"
            f"<title>{e(wk)} 주: {v}{e(unit)}</title></rect>"
        )
        if v and i in (last, peak):
            out.append(
                f"<text class='val' x='{x + bw / 2:.1f}' y='{y - 5:.1f}' text-anchor='middle'>{v}</text>"
            )
        if i % 3 == 0 or i == last:
            out.append(
                f"<text class='tick' x='{x + bw / 2:.1f}' y='{h - 6}' text-anchor='middle'>{e(wk[5:].replace('-', '.'))}</text>"
            )
    axis = f"<line class='axis' x1='0' x2='{w}' y1='{h - pad_b}' y2='{h - pad_b}'/>"
    total = sum(v for _, v in series)
    return (
        f"<figure class='chart'><figcaption>{e(title)} <span class='muted small'>최근 {n}주 합계 {total}{e(unit)}</span></figcaption>"
        f"<svg viewBox='0 0 {w} {h}' role='img' aria-label='{e(title)}: 최근 {n}주 합계 {total}{e(unit)}'>{axis}{''.join(out)}</svg></figure>"
    )


def body(e, k: dict) -> str:
    u, x, q, c = k["use"], k["external"], k["quality"], k["community"]
    days = k.get("usage_days") or 30
    use_how = (
        f"최근 {days}일 · 쿠키 없는 방문 통계(GoatCounter)"
        if k["usage_on"]
        else "방문 통계가 아직 연결되지 않았습니다"
    )
    rows_use = "".join(
        [
            _row(e, "방문(페이지뷰)", u["pageviews"], None, use_how),
            _row(e, "이슈 보드 조회", u.get("board_views"), None, "주제(이슈 보드) 페이지"),
            _row(e, "분석 결과 화면 조회", u["result_views"], None, "결과 목록 + 결과 페이지"),
            _row(
                e,
                "결과를 가져간 횟수",
                u["take"],
                None,
                "인용문 복사 + 링크 복사 + CSV 내려받기",
            ),
            _row(
                e,
                "대화창 질문",
                u["events"]["ask"],
                None,
                "사이트 대화창에 보낸 질문 수",
            ),
            _row(
                e,
                "제안으로 올라온 질문",
                u["site_questions"],
                None,
                "GitHub 이슈 (라벨 from-site)",
            ),
        ]
    )
    rows_ext = "".join(
        [
            _row(
                e,
                "외부 사용자 과업 테스트",
                x["tests"],
                5,
                f"<a href='{REPO}/issues?q=label%3Auser-test'>사용자 테스트 기록</a> 이슈",
                target_text="5명",
            ),
            _row(
                e,
                "혼자 찾아 바르게 인용",
                x["passed"],
                4,
                "과업 1 '혼자 찾음' + 과업 2 '바르게 말함'",
                fmt=lambda v: _ratio(v, x["tests"]) if x["tests"] else "—",
                target_text="4/5",
            ),
        ]
    )
    rows_q = "".join(
        [
            _row(e, "참여자 분석 결과", q["results"], None, "시뮬레이션·멘토 예시 제외"),
            _row(
                e,
                "한 문장 해석이 있는 결과",
                q["one_line"],
                q["all"],
                "discussion.md '결과를 한 문장으로'",
                fmt=lambda v: f"{v}/{q['all']}",
                target_text=f"{q['all']}/{q['all']}",
            ),
            _row(
                e,
                "교차 재현된 결과",
                q["reproduced"],
                q["all"],
                "catalog/projects.yaml reproduced_by",
                fmt=lambda v: f"{v}/{q['all']}",
                target_text=f"{q['all']}/{q['all']}",
            ),
            _row(
                e,
                "계획 먼저 커밋된 결과",
                q["plan_first"],
                None,
                "plan.yaml 이 첫 결과보다 하루 이상 먼저 (새 분석부터 목표 전부)",
                fmt=lambda v: f"{v}/{q['all']}",
            ),
        ]
    )
    rows_c = "".join(
        [
            _row(e, "참여자", c["people"], None, "케이스 담당자 + PR 작성자 (멘토 제외)"),
            _row(
                e,
                "머지된 참여자 PR",
                c["mentee_merged"],
                None,
                "Draft 제외",
                fmt=lambda v: _ratio(v, c["mentee_prs"]) or "—",
            ),
            _row(
                e,
                "리뷰를 받고 머지된 참여자 PR",
                c["mentee_reviewed"],
                c["mentee_merged"],
                "작성자 아닌 사람의 리뷰 1건 이상",
                fmt=lambda v: _ratio(v, c["mentee_merged"]) or "—",
                target_text="전부",
            ),
            _row(e, "작업 제안", c["proposals"], None, "[작업] 이슈"),
            _row(
                e,
                "GitHub 스타 · 포크",
                c["stars"],
                None,
                f"포크 {c['forks'] if c['forks'] is not None else '—'}",
            ),
        ]
    )
    sp = k.get("supply") or {}
    rows_s = "".join(
        [
            _row(
                e,
                "다섯 단계를 모두 채운 이슈 보드",
                sp.get("complete"),
                sp.get("topics"),
                "이슈 · 공공데이터 · 계보 · 분석 · 대시보드가 모두 있는 주제",
                fmt=lambda v: f"{v}/{sp.get('topics')}",
                target_text="지금 이슈 주제 전부",
            ),
            _row(
                e,
                "주제당 채운 단계(평균)",
                sp.get("avg_stages"),
                None,
                "다섯 단계 중",
                fmt=lambda v: f"{v}/5",
            ),
            _row(
                e,
                "지금 이슈 중 대시보드까지 있는 것",
                sp.get("issues_with_dashboard"),
                sp.get("issues"),
                "지금 이슈의 주제에 시점별 효과 그림이 있는가",
                fmt=lambda v: f"{v}/{sp.get('issues')}",
                target_text="전부",
            ),
            _row(
                e,
                "오늘 바로 받을 수 있는 데이터",
                sp.get("ready"),
                None,
                "승인 없음 · 즉시 · 자동승인",
                fmt=lambda v: f"{v}/{sp.get('datasets')}",
            ),
            _row(
                e,
                "계보로 이어진 데이터",
                sp.get("in_lineage"),
                None,
                "계보 YAML 에서 쓰는 데이터셋 (나머지는 아직 어느 지표로도 이어지지 않음)",
                fmt=lambda v: f"{v}/{sp.get('datasets')}",
            ),
            _row(
                e,
                "법령 목록 경과일",
                sp.get("legal_age"),
                None,
                "마지막 법제처 수집 뒤 지난 날 (14일 넘으면 주제 페이지에 경고)",
                fmt=lambda v: f"{v}일",
            ),
        ]
    )
    ns = k.get("north_star") or {}
    ns_v = "측정 전" if ns.get("value") is None else f"{ns['value']}회"
    head = "<tr><th>지표</th><th class='num'>지금</th><th class='num'>목표</th><th>상태</th><th>어디서 셈</th></tr>"

    def table(rows):
        return f"<div class='tablewrap'><table class='score'>{head}{rows}</table></div>"

    wk = k["weekly"]
    charts = bars(e, wk["merged_prs"], "주별 머지된 PR", "건") + bars(
        e, wk["questions"], "주별 질문·작업 제안", "건"
    )
    if wk["pageviews"]:
        charts = bars(e, wk["pageviews"], "주별 방문", "회") + charts
    setup = (
        ""
        if k["usage_on"]
        else f"<p class='banner info'>방문·버튼 통계는 아직 꺼져 있습니다. 메인테이너가 <a href='{REPO}/blob/main/docs/ops/metrics.md'>측정 설정</a>을 마치면 이 표의 '측정 전' 칸이 채워집니다.</p>"
    )
    when = (k.get("measured_at") or "")[:16].replace("T", " ")
    return f"""
<div class="hero" style="padding-bottom:0"><h1 class="h1-sm">성과</h1>
<p class="lede">이 사이트가 목표대로 쓰이는지 매일 다시 셉니다. 목표는 <a href="{REPO}/blob/main/docs/ops/roadmap.md">점검과 다음 계획</a>에서 정했고,
못 센 칸은 0이 아니라 '측정 전'으로 둡니다.{f" 마지막 집계 {e(when)} UTC." if when else ""}</p></div>
{setup}
<section id="north" style="padding-top:28px"><div class="now"><h2>북극성 지표: 주간 가져간 답 <span class="ns">{e(ns_v)}</span></h2>
<p class="muted" style="margin:0">일주일 동안 사람들이 결과의 인용문·링크·CSV를 가져간 횟수입니다. 이 사이트의 목적은 공공데이터로 확인한 답이 <b>판정을 넘지 않는 형태로</b> 밖에서 쓰이는 것이라, 방문 수가 아니라 이것을 중심에 둡니다.
나머지 표는 이 숫자를 움직이는 입력(도달 → 이해 → 가져감 → 참여)과 공급(이슈 보드가 얼마나 채워졌나), 지켜야 할 선(신뢰)입니다. 정의: <a href="{REPO}/blob/main/docs/ops/metrics.md">metrics.md</a></p></div></section>
<section id="supply"><h2>흐름 완성도와 데이터 접근성</h2><p class="sub">이슈에서 대시보드까지 이어진 정도. 사용자가 볼 것이 있어야 쓰임도 생깁니다.</p>{table(rows_s)}</section>
<section id="use"><h2>쓰임</h2><p class="sub">사람들이 결과를 찾고, 가져가고, 질문하는지.</p>{table(rows_use)}</section>
<section id="external"><h2>외부 검증</h2><p class="sub">레포를 모르는 사람이 혼자 결과를 찾아 판정을 넘지 않게 인용하는지. 1단계 관문입니다.
진행 방법: <a href="{REPO}/blob/main/docs/ops/user-test.md">사용자 과업 테스트</a></p>{table(rows_ext)}</section>
<section id="quality"><h2>결과의 질</h2><p class="sub">판정과 별개로, 기록으로 확인되는 신뢰 조건입니다.</p>{table(rows_q)}</section>
<section id="community"><h2>참여</h2><p class="sub">오픈소스로 살아 있는지 — 리뷰와 참여가 이어지는지.</p>{table(rows_c)}</section>
<section id="trend"><h2>흐름</h2><div class="charts">{charts}</div>
<p class="small muted">같은 숫자를 <a href="api/metrics.json">api/metrics.json</a>으로 받을 수 있습니다.</p></section>"""
