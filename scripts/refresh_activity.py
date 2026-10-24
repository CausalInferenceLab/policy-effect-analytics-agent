"""열린 PR·작업 제안을 받아 data/cache/activity.json 에 저장 → 사이트 '프로젝트' 화면이 읽는다.

GITHUB_TOKEN 과 GITHUB_REPOSITORY 가 있을 때만 돈다(Actions 에서는 자동). 없거나 실패하면 아무것도 쓰지 않고
사이트는 이 부분을 빼고 만든다. 공개 정보(제목·작성자·Draft 여부·바꾼 폴더)만 저장한다.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "cache" / "activity.json"
API = "https://api.github.com"


def _get(path: str, token: str, **params):
    r = requests.get(
        f"{API}{path}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        params=params,
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def touched_cases(files: list[str]) -> list[str]:
    out = []
    for f in files:
        parts = f.split("/")
        if parts[0] == "cases" and len(parts) > 2 and not parts[1].startswith("_"):
            out.append(parts[1])
    return sorted(set(out))


def main() -> int:
    token, repo = os.getenv("GITHUB_TOKEN"), os.getenv("GITHUB_REPOSITORY")
    if not token or not repo:
        print("GITHUB_TOKEN/GITHUB_REPOSITORY 없음 — 활동 목록을 건너뜁니다")
        return 0
    try:
        pulls = []
        for pr in _get(f"/repos/{repo}/pulls", token, state="open", per_page=50):
            files = [
                f["filename"]
                for f in _get(f"/repos/{repo}/pulls/{pr['number']}/files", token, per_page=100)
            ]
            pulls.append(
                {
                    "number": pr["number"],
                    "title": pr["title"],
                    "user": pr["user"]["login"],
                    "draft": pr.get("draft", False),
                    "url": pr["html_url"],
                    "updated": pr["updated_at"],
                    "cases": touched_cases(files),
                }
            )
        proposals = [
            {
                "number": it["number"],
                "title": it["title"],
                "user": it["user"]["login"],
                "url": it["html_url"],
            }
            for it in _get(f"/repos/{repo}/issues", token, state="open", per_page=50)
            if "pull_request" not in it and it["title"].startswith("[작업]")
        ]
    except requests.RequestException as ex:
        print(f"::warning::활동 목록을 받지 못했습니다: {ex}", file=sys.stderr)
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "pulls": pulls,
                "proposals": proposals,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"열린 PR {len(pulls)}개 · 작업 제안 {len(proposals)}개 → {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
