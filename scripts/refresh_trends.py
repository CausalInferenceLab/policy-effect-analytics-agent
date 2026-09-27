"""'요즘 궁금해하는 주제' 순위의 재료를 모은다 → catalog/snapshots/trends.json

두 가지 신호를 쓰고, 없는 신호는 비워 둔다(지어내지 않는다).
  1. 사이트 질문 수 — 사이트 대화창에서 올린 GitHub 이슈(라벨 from-site) 중 최근 30일, 주제별 개수.
     GITHUB_TOKEN, GITHUB_REPOSITORY 가 있을 때만 (Actions 에서는 자동으로 있음).
  2. 검색 관심도 — 네이버 데이터랩 검색어 트렌드, 최근 4주 평균(가장 높은 주제 = 100).
     NAVER_CLIENT_ID, NAVER_CLIENT_SECRET 시크릿이 있을 때만.
     새 키는 NCP 'NAVER API HUB'(Search Trend)에서 발급합니다(2026.7.30부터 개발자센터 신규 신청 중단).
     개발자센터에서 전에 받은 키도 2027.6.30까지 쓸 수 있어, 두 주소를 차례로 시도합니다.
     네이버 결과값은 네이버 소유이므로 사이트에는 값이 아니라 '순위'만 보여 줍니다.
둘 다 없으면 사이트는 '최근 시행·발표 순'으로 보여 주고 그렇게 표시한다.

    python scripts/refresh_trends.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.discovery import load_topics  # noqa: E402

OUT = ROOT / "catalog" / "snapshots" / "trends.json"
DAYS = 30
# (주소, 헤더 이름 두 개) — API HUB 먼저, 실패하면 개발자센터
NAVER_ENDPOINTS = [
    (
        "https://naverapihub.apigw.ntruss.com/search-trend/v1/search",
        "X-NCP-APIGW-API-KEY-ID",
        "X-NCP-APIGW-API-KEY",
    ),
    ("https://openapi.naver.com/v1/datalab/search", "X-Naver-Client-Id", "X-Naver-Client-Secret"),
]


# ─── 1. 사이트 질문 ─────────────────────────────────────────────────────────
TOPIC_FIELD = re.compile(r"###\s*관련 주제\s*\n+(.+)")
ID_IN_PARENS = re.compile(r"\(([a-z0-9-]+)\)\s*$")


def topic_of(body: str, topic_ids: set[str]) -> str | None:
    """이슈 본문의 '관련 주제' 칸에서 주제 id를 꺼낸다. 없거나 모르는 값이면 None(=새 주제)."""
    m = TOPIC_FIELD.search(body or "")
    if not m:
        return None
    val = m.group(1).strip()
    idm = ID_IN_PARENS.search(val)
    if idm and idm.group(1) in topic_ids:
        return idm.group(1)
    return val if val in topic_ids else None


def count_site_questions(issues: list[dict], topic_ids: set[str]) -> tuple[Counter, int]:
    counts: Counter = Counter()
    new = 0
    for it in issues:
        if "pull_request" in it:
            continue
        tid = topic_of(it.get("body") or "", topic_ids)
        if tid:
            counts[tid] += 1
        else:
            new += 1
    return counts, new


def fetch_site_issues() -> list[dict] | None:
    token, repo = os.getenv("GITHUB_TOKEN"), os.getenv("GITHUB_REPOSITORY")
    if not (token and repo):
        return None
    since = (datetime.now(UTC) - timedelta(days=DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out, page = [], 1
    while page <= 5:
        r = requests.get(
            f"https://api.github.com/repos/{repo}/issues",
            params={
                "labels": "from-site",
                "state": "all",
                "since": since,
                "per_page": 100,
                "page": page,
            },
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            timeout=20,
        )
        r.raise_for_status()
        batch = r.json()
        out += [i for i in batch if i.get("created_at", "") >= since]
        if len(batch) < 100:
            break
        page += 1
    return out


# ─── 2. 네이버 데이터랩 ──────────────────────────────────────────────────────
def naver_groups(topics) -> list[dict]:
    """주제마다 검색어 묶음 하나(최대 5개 단어)."""
    return [{"groupName": t.id, "keywords": t.keywords[:5]} for t in topics]


def combine_batches(batches: list[dict[str, float]], anchor: str) -> dict[str, float]:
    """요청마다 기준(100)이 달라지므로, 모든 요청에 넣은 anchor 주제 값으로 눈금을 맞춘 뒤 최대=100으로 다시 맞춘다."""
    ref = batches[0].get(anchor, 0.0)
    merged: dict[str, float] = {}
    for b in batches:
        a = b.get(anchor, 0.0)
        scale = (ref / a) if a else 0.0
        for k, v in b.items():
            merged.setdefault(k, v * scale)
    top = max(merged.values(), default=0.0)
    return {k: round(100 * v / top, 1) if top else 0.0 for k, v in merged.items()}


def naver_post(body: dict, cid: str, sec: str):
    last = None
    for url, h_id, h_sec in NAVER_ENDPOINTS:
        r = requests.post(url, json=body, headers={h_id: cid, h_sec: sec}, timeout=20)
        if r.ok:
            return r
        last = r
    last.raise_for_status()
    return last


def fetch_naver(topics) -> dict[str, float] | None:
    cid, sec = os.getenv("NAVER_CLIENT_ID"), os.getenv("NAVER_CLIENT_SECRET")
    if not (cid and sec):
        return None
    end = date.today()
    start = end - timedelta(weeks=4)
    groups = naver_groups(topics)
    anchor, rest = groups[0], groups[1:]
    batches: list[dict[str, float]] = []
    chunks = [rest[i : i + 4] for i in range(0, len(rest), 4)] or [[]]
    for chunk in chunks:
        body = {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "timeUnit": "week",
            "keywordGroups": [anchor, *chunk],
        }
        r = naver_post(body, cid, sec)
        batches.append(
            {
                res["title"]: (
                    sum(d["ratio"] for d in res["data"]) / len(res["data"]) if res["data"] else 0.0
                )
                for res in r.json()["results"]
            }
        )
    return combine_batches(batches, anchor["groupName"])


def main() -> int:
    topics = load_topics()
    ids = {t.id for t in topics}
    data: dict = {
        "updated": date.today().isoformat(),
        "window_days": DAYS,
        "sources": [],
        "topics": {},
    }

    try:
        issues = fetch_site_issues()
    except requests.RequestException as e:
        print(f"사이트 질문 수집 실패(건너뜀): {e}")
        issues = None
    if issues is not None:
        counts, new = count_site_questions(issues, ids)
        data["sources"].append("site_questions")
        data["new_topic_questions"] = new
        for t in ids:
            data["topics"].setdefault(t, {})["questions"] = counts.get(t, 0)
        print(f"사이트 질문 {len(issues)}건 (새 주제 {new}건)")

    try:
        search = fetch_naver(topics)
    except (requests.RequestException, KeyError, ValueError) as e:
        print(f"네이버 데이터랩 실패(건너뜀): {e}")
        search = None
    if search is not None:
        data["sources"].append("naver_datalab")
        for t, v in search.items():
            data["topics"].setdefault(t, {})["search"] = v
        print("네이버 데이터랩 검색 관심도 반영")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"→ {OUT.relative_to(ROOT)} (신호: {', '.join(data['sources']) or '없음'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
