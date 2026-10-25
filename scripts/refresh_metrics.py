"""성과 지표를 모아 data/cache/metrics.json 에 저장 → 사이트 '성과' 화면(impact.html)과 api/metrics.json 이 읽는다.

공개 정보만 모은다. 사람 이름·연락처는 저장하지 않고 GitHub ID 수만 센다.
- GitHub (GITHUB_TOKEN · GITHUB_REPOSITORY, Actions 에서는 자동):
  PR(작성·머지·리뷰), 이슈(사이트 질문 from-site · 작업 제안 [작업] · 교차 재현 reproduction · 사용자 테스트 user-test),
  사용자 테스트 기록의 과업별 응답, 스타·포크
- GoatCounter (선택: 변수 GOATCOUNTER_CODE + 시크릿 GOATCOUNTER_TOKEN):
  최근 기간 방문 수, 페이지별 조회, 버튼 이벤트(인용 복사·CSV 내려받기·질문 등)
어느 쪽이든 실패하면 경고만 남기고 넘어간다(사이트는 그 부분을 '아직 측정 안 됨'으로 그린다).
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "cache" / "metrics.json"
API = "https://api.github.com"
MENTOR = "jsshin2022"
BOTS = ("[bot]",)
TASK_RE = re.compile(r"### 과업 (\d)[^\n]*\n+([^\n#]+)")


def _get(path: str, token: str, **params):
    r = requests.get(
        f"{API}{path}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        params=params,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def _all(path: str, token: str, **params) -> list:
    out, page = [], 1
    while True:
        rows = _get(path, token, per_page=100, page=page, **params)
        out += rows
        if len(rows) < 100 or page >= 20:
            return out
        page += 1


def parse_user_test(body: str) -> dict[str, str]:
    """사용자 과업 테스트 이슈 본문 → {'1': '혼자 찾음', ...}"""
    return {k: v.strip() for k, v in TASK_RE.findall(body or "")}


def user_test_pass(answers: dict[str, str]) -> bool:
    """관문: 과업 1(혼자 찾음)과 과업 2(바르게 말함)를 힌트 없이 성공."""
    return answers.get("1") == "혼자 찾음" and answers.get("2") == "바르게 말함"


def github(token: str, repo: str) -> dict:
    meta = _get(f"/repos/{repo}", token)
    pulls = _all(f"/repos/{repo}/pulls", token, state="all")
    prs = []
    for p in pulls:
        author = p["user"]["login"]
        reviews = []
        if p.get("merged_at") or p["state"] == "open":
            reviews = [
                rv
                for rv in _get(f"/repos/{repo}/pulls/{p['number']}/reviews", token, per_page=100)
                if rv["user"] and rv["user"]["login"] != author
            ]
        prs.append(
            {
                "number": p["number"],
                "author": author,
                "mentor": author == MENTOR,
                "bot": author.endswith(BOTS),
                "created": p["created_at"][:10],
                "merged": (p.get("merged_at") or "")[:10] or None,
                "state": p["state"],
                "draft": bool(p.get("draft")),
                "reviews": len(reviews),
                "reviewers": sorted({rv["user"]["login"] for rv in reviews}),
            }
        )
    issues = [
        i for i in _all(f"/repos/{repo}/issues", token, state="all") if "pull_request" not in i
    ]

    def kind(i) -> str | None:
        labels = {lb["name"] for lb in i.get("labels", [])}
        title = i.get("title", "")
        if "user-test" in labels or title.startswith("[사용자 테스트]"):
            return "user_test"
        if "reproduction" in labels or title.startswith("[재현]"):
            return "reproduction"
        if "from-site" in labels or title.startswith("[사이트 질문]"):
            return "site_question"
        if title.startswith("[작업]"):
            return "proposal"
        return None

    rows = []
    for i in issues:
        k = kind(i)
        if not k:
            continue
        row = {
            "number": i["number"],
            "kind": k,
            "created": i["created_at"][:10],
            "state": i["state"],
        }
        if k == "user_test":
            ans = parse_user_test(i.get("body") or "")
            row |= {"answers": ans, "passed": user_test_pass(ans)}
        rows.append(row)
    return {
        "repo": {
            "stars": meta.get("stargazers_count", 0),
            "forks": meta.get("forks_count", 0),
            "watchers": meta.get("subscribers_count", 0),
        },
        "pulls": prs,
        "issues": rows,
    }


def goatcounter(code: str, token: str, days: int = 30) -> dict:
    base = f"https://{code}.goatcounter.com/api/v0"
    end = date.today()
    start = end - timedelta(days=days)
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    q = {"start": start.isoformat(), "end": end.isoformat()}
    total = requests.get(f"{base}/stats/total", headers=h, params=q, timeout=30)
    total.raise_for_status()
    hits = requests.get(f"{base}/stats/hits", headers=h, params=q | {"limit": 100}, timeout=30)
    hits.raise_for_status()
    t = total.json()
    pages, events = {}, {}
    for row in hits.json().get("hits", []):
        (events if row.get("event") else pages)[row.get("path", "")] = row.get("count", 0)
    daily = [
        {"day": s.get("day"), "count": s.get("daily", 0)}
        for s in t.get("stats", [])
        if isinstance(s, dict) and s.get("day")
    ]
    return {
        "days": days,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "pageviews": t.get("total", 0),
        "events_total": t.get("total_events", 0),
        "daily": daily,
        "pages": pages,
        "events": events,
    }


def main() -> int:
    out: dict = {"fetched_at": datetime.now(UTC).isoformat(timespec="seconds")}
    token, repo = os.getenv("GITHUB_TOKEN"), os.getenv("GITHUB_REPOSITORY")
    if token and repo:
        try:
            out["github"] = github(token, repo)
        except requests.RequestException as ex:
            print(f"::warning::GitHub 지표를 받지 못했습니다: {ex}", file=sys.stderr)
    else:
        print("GITHUB_TOKEN/GITHUB_REPOSITORY 없음 — GitHub 지표를 건너뜁니다")
    code, gtoken = os.getenv("GOATCOUNTER_CODE"), os.getenv("GOATCOUNTER_TOKEN")
    if code and gtoken:
        try:
            out["usage"] = goatcounter(code, gtoken)
        except (requests.RequestException, ValueError) as ex:
            print(f"::warning::방문 통계를 받지 못했습니다: {ex}", file=sys.stderr)
    if len(out) == 1:
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    g = out.get("github", {})
    print(
        f"PR {len(g.get('pulls', []))}개 · 이슈 {len(g.get('issues', []))}개"
        + (f" · 방문 {out['usage']['pageviews']}" if "usage" in out else "")
        + f" → {OUT.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
