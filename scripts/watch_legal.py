"""최근 며칠 사이 주제와 관련된 법령·행정규칙이 바뀌었는지 확인한다 (변경 감지).

바뀐 것이 있으면 목록을 출력하고, --open-issue 를 주면 GitHub 이슈(라벨 law-change)를 엽니다.
같은 제목의 이슈가 이미 있으면 새로 열지 않습니다. 이슈는 구성원 누구나 확인하고 topics.yaml events·분석에 반영합니다.

    LAW_OC=... python scripts/watch_legal.py --days 7
    LAW_OC=... GITHUB_TOKEN=... GITHUB_REPOSITORY=org/repo python scripts/watch_legal.py --days 7 --open-issue
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.adapters.base import MissingAPIKey  # noqa: E402
from core.adapters.legal import ATTRIBUTION, LawClient, changes_between  # noqa: E402
from core.discovery import load_topics  # noqa: E402

SNAP = ROOT / "catalog" / "snapshots"


def known_law_names(topic) -> set[str]:
    """근거 법률과 그 시행령·시행규칙 이름. 스냅샷이 있으면 거기서, 없으면 규칙으로 만든다."""
    names = set()
    for law in topic.legal.laws:
        names |= {law, f"{law} 시행령", f"{law} 시행규칙"}
    snap = SNAP / f"legal_{topic.id}.csv"
    if snap.exists():
        df = pd.read_csv(snap, dtype=str).fillna("")
        names |= set(df.loc[df["group"] == "법령", "name"])
    return names


def to_markdown(results: list[tuple[str, pd.DataFrame]], start: date, end: date) -> str:
    lines = [f"{start} ~ {end} 사이 주제와 관련된 법령·행정규칙 변경입니다. {ATTRIBUTION}", ""]
    for name, df in results:
        lines.append(f"### {name}")
        lines.append("| 종류 | 이름 | 변경 | 공포·발령 | 시행 |")
        lines.append("|---|---|---|---|---|")
        for r in df.itertuples():
            lines.append(
                f"| {r.kind} | [{r.name}]({r.url}) | {r.change} | {r.announced} | {r.effective} |"
            )
        lines.append("")
    lines += [
        "**할 일 (구성원 누구나)**",
        "- 분석 중인 정책의 시작일·대상이 바뀌었는지 확인하고, 바뀌었으면 `catalog/topics.yaml`의 `events`에 출처와 함께 적어 PR을 올립니다.",
        "- 이미 계획(plan.yaml)을 커밋한 분석이라면 계획을 고치지 말고 리포트의 '한계'에 적습니다.",
    ]
    return "\n".join(lines)


def open_issue(title: str, body: str) -> str:
    import requests

    repo, token = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"]
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    api = f"https://api.github.com/repos/{repo}/issues"
    existing = requests.get(
        api, params={"labels": "law-change", "state": "all", "per_page": 100}, headers=h, timeout=20
    )
    existing.raise_for_status()
    if any(i["title"] == title for i in existing.json()):
        return "이미 있음"
    r = requests.post(
        api, json={"title": title, "body": body, "labels": ["law-change"]}, headers=h, timeout=20
    )
    r.raise_for_status()
    return r.json()["html_url"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--open-issue", action="store_true")
    a = ap.parse_args()
    try:
        c = LawClient()
    except MissingAPIKey as e:
        print(f"건너뜀: {e}")
        return 0
    end = date.today()
    start = end - timedelta(days=a.days)
    results = []
    for t in load_topics():
        if not t.legal or not (t.legal.laws or t.legal.admin_rules):
            continue
        df = changes_between(c, known_law_names(t), t.legal.admin_rules, start, end)
        if not df.empty:
            results.append((t.name, df))
    if not results:
        print(f"{start} ~ {end}: 바뀐 것 없음")
        return 0
    body = to_markdown(results, start, end)
    print(body)
    if a.open_issue:
        title = f"[법령 변경] {start} ~ {end} · " + ", ".join(n for n, _ in results)
        print("이슈:", open_issue(title[:120], body))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
