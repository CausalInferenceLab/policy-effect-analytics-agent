"""결과를 얼마나 믿을 수 있나 — 기록으로 확인할 수 있는 것만 보여 준다.

1. 사전 등록 기록: git 기록에서 plan.yaml 이 처음 커밋된 때와 flow_log.json(첫 결과)이 처음 커밋된 때를 비교한다.
   git 기록은 '로컬에서 데이터를 먼저 봤는지'까지는 증명하지 못한다. 그래서 판정이 아니라 기록을 그대로 보여 준다.
   - 계획이 결과보다 하루 이상 먼저, 결과 뒤 계획 수정 없음 → '계획 먼저 커밋'
   - 결과가 나온 뒤(또는 같은 커밋에서) 계획을 고쳤음 → '결과 뒤 계획 수정 n회'
   - 계획과 결과가 하루 안에 커밋됨 → '같은 날 커밋 — 사전 등록 기록 약함'
   얕은 clone(Actions 기본)이면 기록이 없으므로 None (화면에서 빠진다).
2. 교차 재현: catalog/projects.yaml 의 reproduced_by (다른 참여자가 make flow 로 같은 판정을 얻었음).
3. 작성자 해석: discussion.md 에 '결과를 한 문장으로'가 있는가.
4. 다음 할 일: 위 항목과 진행 단계로 참여자에게 보여 줄 할 일 목록.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str) -> str | None:
    try:
        r = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


@cache
def _history_ok() -> bool:
    out = _git("rev-parse", "--is-shallow-repository")
    return out is not None and out.strip() == "false"


def _commits(path: Path, added_only: bool = False) -> list[tuple[str, datetime]]:
    rel = path.relative_to(ROOT).as_posix()
    args = ["log", "--format=%H %aI"]
    if added_only:
        args.append("--diff-filter=A")
    out = _git(*args, "--", rel) or ""
    rows = []
    for line in out.splitlines():
        sha, _, when = line.partition(" ")
        try:
            rows.append((sha, datetime.fromisoformat(when)))
        except ValueError:
            continue
    return rows


def prereg(case: Path) -> dict | None:
    """사전 등록 기록. 기록을 확인할 수 없으면 None."""
    if not _history_ok() or not (case / "plan.yaml").exists():
        return None
    plan_added = _commits(case / "plan.yaml", added_only=True)
    result_added = _commits(case / "flow_log.json", added_only=True)
    if not plan_added or not result_added:
        return None
    p_sha, p0 = plan_added[-1]
    r_sha, r0 = result_added[-1]
    after = [s for s, t in _commits(case / "plan.yaml") if t >= r0 and s != p_sha]
    gap_days = (r0 - p0).total_seconds() / 86400
    base = {
        "plan_at": p0.date().isoformat(),
        "result_at": r0.date().isoformat(),
        "plan_commit": p_sha[:7],
        "result_commit": r_sha[:7],
        "changed_after": len(after),
    }
    if after:
        return base | {
            "level": "warn",
            "label": f"결과 뒤 계획 수정 {len(after)}회",
            "text": "첫 결과가 커밋된 뒤(또는 같은 커밋에서) plan.yaml 이 바뀌었습니다. "
            "바뀐 이유는 작성자의 '계획에서 바뀐 것'을 보세요.",
        }
    if gap_days >= 1:
        return base | {
            "level": "go",
            "label": "계획 먼저 커밋",
            "text": f"plan.yaml 이 첫 결과보다 {int(gap_days)}일 먼저 커밋됐고, 그 뒤 바뀌지 않았습니다.",
        }
    return base | {
        "level": "warn",
        "label": "같은 날 커밋 — 사전 등록 기록 약함",
        "text": "plan.yaml 과 첫 결과가 하루 안에 커밋돼, 데이터를 보기 전에 계획을 정했는지 기록으로 구분되지 않습니다. "
        "결과가 틀렸다는 뜻은 아닙니다.",
    }


def checks(a: dict) -> list[tuple[str, str, str]]:
    """(상태 go|warn|info, 항목, 설명) — 답 페이지의 '이 결과를 얼마나 믿을 수 있나'."""
    out = []
    pr = a.get("prereg")
    if pr:
        out.append((pr["level"], f"사전 등록 · {pr['label']}", pr["text"]))
    else:
        out.append(
            ("info", "사전 등록 · 기록 확인 안 됨", "이 빌드에서는 git 기록을 읽지 못했습니다.")
        )
    rep = a.get("reproduced_by") or []
    if rep:
        who = ", ".join(f"@{x}" for x in rep)
        out.append(
            ("go", "교차 재현 · 확인됨", f"{who} 이(가) 같은 명령으로 같은 판정을 얻었습니다.")
        )
    else:
        out.append(
            ("warn", "교차 재현 · 아직 없음", "작성자 외에 다시 돌려 본 사람이 아직 없습니다.")
        )
    if a.get("has_one_line"):
        out.append(
            ("go", "작성자 해석 · 있음", "discussion.md 에 '결과를 한 문장으로'가 있습니다.")
        )
    else:
        out.append(("warn", "작성자 해석 · 한 문장 없음", "위 한 줄 답은 자동 판정 문장입니다."))
    m = a.get("manifest") or {}
    if m.get("git_dirty"):
        out.append(
            (
                "warn",
                "실행 상태 · 커밋 안 된 변경",
                "실행 당시 작업 폴더에 커밋 안 된 변경이 있었습니다.",
            )
        )
    return out


def next_steps(p: dict, a: dict | None, registered: bool) -> list[str]:
    """참여자 카드에 보일 다음 할 일 (앞에서부터 중요)."""
    st = p["stages"]
    todo = []
    if not registered:
        todo.append("catalog/projects.yaml 에 한 줄 추가")
    if not st[0]:
        todo.append("plan.yaml 작성 → 계획만 담은 PR 먼저")
    elif not st[1]:
        todo.append("fetch.py 로 data/panel.csv 만들기")
    elif not st[2]:
        todo.append("make flow 실행 → 결과 PR")
    elif not st[3]:
        todo.append("discussion.md 에 해석·한계 쓰기")
    if a is not None:
        if st[3] and not a.get("has_one_line"):
            todo.append("discussion.md 에 '## 결과를 한 문장으로' 추가")
        if not a.get("reproduced_by"):
            todo.append("다른 참여자에게 교차 재현 요청")
        pr = a.get("prereg")
        if pr and pr["level"] == "warn":
            todo.append("다음 분석은 계획 PR을 먼저 올리기")
    return todo
