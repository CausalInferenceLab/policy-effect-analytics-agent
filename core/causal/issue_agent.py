"""작업 제안 이슈 → 가설·데이터 점검 댓글 → (사람이 승인하면) plan.yaml 초안 PR.

.github/workflows/plan-agent.yml 이 부른다. 이슈 본문은 믿지 않는 입력이라 셸에 넣지 않고 환경변수로만 받는다.

    ISSUE_NUMBER, ISSUE_TITLE, ISSUE_BODY 환경변수
    python -m core.causal.issue_agent comment   → 댓글 본문(markdown)을 표준출력으로
    python -m core.causal.issue_agent write     → cases/<케이스>/plan.yaml 을 쓰고 케이스 이름을 출력

사람의 관문: 메인테이너가 이슈에 'plan-approved' 라벨을 붙여야 PR 을 만든다. PR 을 머지하는 것이 사전 등록이다.
"""

from __future__ import annotations

import os
import re
import sys

from core.discovery.catalog import ROOT

from .draft import draft, write

MARK = "<!-- plan-agent -->"
SECTION = re.compile(r"^###\s+(.+?)\s*$", re.M)
OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")


def parse_form(body: str) -> dict[str, str]:
    """GitHub 이슈 폼 본문(### 라벨 \\n\\n 값) → {라벨: 값}."""
    out: dict[str, str] = {}
    parts = SECTION.split(body or "")
    for label, value in zip(parts[1::2], parts[2::2], strict=False):
        v = value.strip()
        out[label.strip()] = "" if v in ("_No response_", "미정") else v
    return out


def _field(form: dict, prefix: str) -> str:
    return next((v for k, v in form.items() if k.startswith(prefix)), "")


def case_name(form: dict, topic_id: str | None) -> str | None:
    owner = _field(form, "담당자").lstrip("@").strip()
    if not OWNER.match(owner):
        return None
    slug = topic_id or "topic"
    name = re.sub(r"[^a-z0-9-]+", "-", f"{owner}-{slug}".lower()).strip("-")
    return name[:60]


def plan_for_issue(title: str, body: str) -> dict:
    form = parse_form(body)
    question = _field(form, "하려는 것") or re.sub(r"^\[작업\]\s*", "", title or "")
    question = " ".join(question.split())[:300]
    topic_hint = _field(form, "주제")
    r = draft(question, "gildong-topic", hint=topic_hint)
    topic = r.get("topic") if r.get("matched") else None
    case = case_name(form, topic)
    if r.get("matched") and case:
        r = draft(question, case, hint=topic_hint)
    return {"question": question, "case": case, "topic": topic, **r}


def comment(title: str, body: str) -> str:
    r = plan_for_issue(title, body)
    if not r.get("question"):
        return f"{MARK}\n질문 칸이 비어 있어 가설·데이터 점검을 하지 못했어요. '하려는 것'에 한두 문장을 적어 주세요."
    if not r.get("matched"):
        return (
            f"{MARK}\n### 가설·데이터 점검 (자동)\n이 질문과 맞는 주제를 카탈로그에서 찾지 못했어요. "
            "새 주제라면 `catalog/topics.yaml` 에 주제를 먼저 제안해 주세요. 정책 이름·지역을 넣으면 다시 확인합니다."
        )
    f = r["feasibility"]
    mark = {"ok": "✅", "warn": "⚠️", "miss": "❌"}
    rows = "\n".join(f"| {mark[c['status']]} | {c['label']} | {c['detail']} |" for c in f["checks"])
    case = r["case"] or "<담당자ID>-<주제>"
    return f"""{MARK}
### 가설·데이터 점검 (자동) — **{f["label"]}**

**가설** {f["hypothesis"]["sentence"]}

| | 점검 | 근거 |
|---|---|---|
{rows}

주제 `{r["topic"]}` · 지금 이슈 `{r.get("issue") or "없음"}` · 인과 그래프(PyWhy 방식): 정책 → 결과, 공통 원인 → 정책·결과

<details><summary>plan.yaml 초안 (TODO {r["todo"]}곳) — <code>cases/{case}/plan.yaml</code></summary>

```yaml
{r["plan_yaml"]}```
</details>

메인테이너가 이 이슈에 `plan-approved` 라벨을 붙이면 이 초안으로 PR 을 엽니다. 데이터를 보기 전에 TODO 를 채워 PR 을 머지하는 것이 사전 등록입니다.
숫자·날짜·데이터는 전부 카탈로그에서 왔고 LLM 은 쓰지 않았어요. (`python -m core.causal.draft`)"""


def write_plan(title: str, body: str) -> str:
    r = plan_for_issue(title, body)
    if not (r.get("matched") and r.get("case")):
        raise SystemExit("주제나 담당자 ID 를 확인할 수 없어 초안을 쓰지 않았어요")
    write(r["case"], r["plan_yaml"])
    return r["case"]


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    title, body = os.environ.get("ISSUE_TITLE", ""), os.environ.get("ISSUE_BODY", "")
    if argv[:1] == ["comment"]:
        print(comment(title, body))
    elif argv[:1] == ["write"]:
        print(write_plan(title, body))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    os.chdir(ROOT)
    raise SystemExit(main())
