"""질문 한 줄 → 가설·데이터 점검 → plan.yaml 초안 (사람이 승인하는 에이전트의 첫 단계).

    python -m core.causal.draft "서울 토허제 확대 뒤 옆 동네 집값이 올랐나"            # 화면에만
    python -m core.causal.draft "…" --case gildong-ltp-spillover --write            # cases/<케이스>/plan.yaml

하는 일
  1. 질문을 주제·지금 이슈에 맞춘다 (core.discovery.match — 키워드 점수, 지어내지 않음)
  2. 그 주제의 가설·데이터 점검(feasibility)을 붙인다 — 처치 시점 근거, 결과·통제 데이터, 단위
  3. 스키마(core.schema.plan)를 통과하는 plan.yaml 초안을 만든다. 사람이 확인해야 할 칸은 'TODO' 주석.
     시행일은 지금 이슈(issues.yaml)의 공식 시행일만 쓰고, 없으면 TODO 로 남긴다.
  4. --write 는 새 폴더에만 쓴다(있으면 멈춤). 데이터는 받지 않는다 — fetch.py 는 사람이 쓴다.

LLM 은 쓰지 않는다. 숫자·날짜·데이터 id 는 전부 카탈로그에서 온다.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

from core.discovery.catalog import ROOT, load_catalog, load_topics
from core.discovery.match import match_topic
from core.discovery.ontology import load_datasets, load_issues

from .feasibility import topic_feasibility

DESIGN_METHOD = {
    "did_simultaneous": "event_study",
    "did_staggered": "event_study",
    "scm": "did",
    "its": "its",
}


def _q(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def draft(question: str, case_id: str = "gildong-topic", hint: str = "") -> dict:
    """hint: 주제 id·이슈 id 처럼 매칭에만 쓰고 plan 에는 넣지 않는 글."""
    question = " ".join(str(question).split())[:300]  # 한 줄로 — YAML 블록·주석을 깨지 않게
    topics = load_topics()
    ids = {t.id: t for t in topics}
    hint_ids = [x for x in re.split(r"[\s/,]+", hint or "") if x]
    hinted = next((ids[x] for x in hint_ids if x in ids), None)
    m = match_topic(question + " " + (hint or ""), topics, load_catalog())
    if hinted:
        from core.discovery.match import TopicMatch

        m = [TopicMatch(hinted, 99.0, ["hint"])] + [x for x in m if x.topic.id != hinted.id]
    if not m:
        return {
            "matched": False,
            "message": "주제를 찾지 못했어요. 정책 이름·지역을 넣어 다시 물어보세요.",
        }
    topic = m[0].topic
    datasets, issues = load_datasets(), load_issues()
    feas = topic_feasibility(topic, datasets, issues)
    my_issues = [i for i in issues if i.topic == topic.id]
    qn = re.sub(r"\s+", "", question)
    issue = next((i for i in my_issues if i.id in hint_ids), None) or max(
        my_issues,
        key=lambda i: sum(w in qn for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", i.name)),
        default=None,
    )
    ds = [d for d in datasets if topic.id in d.topics]
    outs = sorted(
        [d for d in ds if "outcome" in d.roles],
        key=lambda d: (
            d.id not in (issue.datasets if issue else []),
            d.approval not in {"즉시", "자동승인", "없음"},
        ),
    )
    covs = [d for d in ds if "covariate" in d.roles][:2]
    when = issue.effective if issue else None
    monthly = any(("월" in d.time) for d in outs[:1])
    t_col, freq = ("month", "month") if monthly else ("year", "year")
    treat_time = (when[:7] if monthly else int(when[:4])) if when else None
    expected = "unknown"
    lines = [
        "# 질문에서 만든 plan.yaml 초안 (python -m core.causal.draft) — 데이터를 보기 전에 TODO 를 채우고 PR 로 사전 등록하세요.",
        f"# 원래 질문: {question}",
        f"# 가설·데이터 점검: {feas['label']} — "
        + " · ".join(f"{c['label']} {c['status']}" for c in feas["checks"]),
        f"case_id: {case_id}",
        f"title: {_q((issue.name if issue else topic.name) + ' 효과 분석')}",
        "question: >",
        f"  {question.strip()}",
        "synthetic_data: false",
        "",
        "unit: {name: 시군구, id_col: region_id}   # TODO: 결과 데이터의 공간 단위에 맞추기",
        f"time: {{col: {t_col}, freq: {freq}, start: TODO, end: TODO}}   # TODO: 정책 전 최소 3시점"
        if not when
        else f"time: {{col: {t_col}, freq: {freq}, start: {_q(str(int(when[:4]) - 3) + (when[4:7] if monthly else '')) if monthly else int(when[:4]) - 3}, end: {_q(when[:4] + '-12') if monthly else int(when[:4]) + 2}}}   # TODO: 기간 확인",
        "",
        "treatment:",
        f"  definition: {_q(issue.treatment if issue else 'TODO: 정책을 받은 곳과 시점')}",
        "  group_col: treated",
        f"  treat_time: {_q(treat_time) if isinstance(treat_time, str) else treat_time if treat_time else 'TODO   # 공식 시행일'}",
        "control:",
        f"  definition: {_q(issue.control if issue else 'TODO: 같은 기간 정책을 받지 않은 곳')}",
        '  rationale: "TODO: 정책 전 추세가 나란했다고 볼 이유 (결과를 보고 고르지 않기)"',
        "",
        "outcomes:",
        f"  - name: {_q(issue.outcomes[0] if issue and issue.outcomes else (outs[0].measures[0] if outs and outs[0].measures else '주요 결과 지표'))}",
        "    col: outcome",
        '    definition: "TODO: 분자/분모/기간까지 조작적으로"',
        "    primary: true",
        f"    expected_direction: {expected}   # TODO: increase | decrease (데이터 보기 전에)",
        "",
        "estimator:",
        f"  method: {DESIGN_METHOD.get(issue.design, 'event_study') if issue else 'event_study'}",
        "  cluster_col: region_id",
        f"  covariates: []   # 공통 원인 후보(인과 그래프): {', '.join(d.name for d in covs) or '없음'}",
        "",
        "assumptions:",
        "  - name: 평행추세",
        '    description: "정책이 없었다면 두 집단의 추세는 같았을 것"',
        "    check: pretrend_test",
        "  - name: 동시 정책 없음",
        f"    description: {_q(issue.pitfalls[0] if issue and issue.pitfalls else '같은 시점에 결과에 영향을 준 다른 정책이 없음')}",
        "    check: manual",
        "",
        "refutations:",
        "  - kind: placebo_time",
        "    params: {shift: 2}",
        "",
        "abstention:",
        "  - when: pretrend_rejected",
        "    verdict: not_identified",
        "  - when: few_treated_clusters",
        "    verdict: conditional",
        "  - when: ci_crosses_zero",
        "    verdict: conditional",
        "",
        "data_sources:",
    ]
    for d in (outs[:2] + covs) or []:
        lic = d.license if d.license.startswith("KOGL") or d.license == "other" else "other"
        lines += [
            f"  - name: {_q(d.name)}",
            f"    provider: {_q(d.provider)}",
            f"    url: {_q(d.url)}",
            f"    license: {lic}   # 카탈로그: {d.license}",
            f"    notes: {_q('역할: ' + '/'.join(d.roles) + ' · 단위: ' + d.space + ' × ' + d.time)}",
        ]
    if not (outs or covs):
        lines += ['  - name: "TODO"', '    provider: "TODO"', "    license: other"]
    text = "\n".join(lines) + "\n"
    return {
        "matched": True,
        "topic": topic.id,
        "issue": issue.id if issue else None,
        "feasibility": feas,
        "plan_yaml": text,
        "todo": text.count("TODO"),
    }


def write(case_id: str, text: str) -> Path:
    case = ROOT / "cases" / case_id
    if case.exists():
        raise FileExistsError(f"{case} 가 이미 있어요. 다른 이름을 쓰세요")
    case.mkdir(parents=True)
    (case / "plan.yaml").write_text(text, encoding="utf-8")
    return case / "plan.yaml"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="질문 → 가설·데이터 점검 → plan.yaml 초안")
    ap.add_argument("question")
    ap.add_argument("--case", default="gildong-topic")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    r = draft(a.question, a.case)
    if not r["matched"]:
        print(r["message"], file=sys.stderr)
        return 1
    f = r["feasibility"]
    print(f"주제: {r['topic']} · 이슈: {r['issue'] or '없음'} · 판정: {f['label']}")
    print(f"가설: {f['hypothesis']['sentence']}")
    for c in f["checks"]:
        print(f"  [{c['status']:>4}] {c['label']} — {c['detail']}")
    print(f"\n--- plan.yaml 초안 (TODO {r['todo']}곳) ---\n{r['plan_yaml']}")
    if a.write:
        print("저장:", write(a.case, r["plan_yaml"]))
    yaml.safe_load(r["plan_yaml"])  # 최소한 YAML 로 읽혀야 한다
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
