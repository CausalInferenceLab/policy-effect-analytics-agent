"""케이스 ↔ 데이터 ↔ 계보 잇기 — 참여자가 따로 적지 않아도 plan.yaml 에서 자동으로 연결한다.

1. case_sources(): plan.yaml 의 data_sources 를 catalog/datasets.yaml 과 맞춘다.
   URL 이 같거나, 이름·URL·메모에 카탈로그 id(OA-12914, 15126468, DT_1B040A3 …)가 그대로 있으면 같은 데이터.
   맞는 것이 없으면 dataset=None — 카탈로그에 추가할 후보로 화면에 보인다.
2. auto_lineage(): 손으로 쓴 계보(catalog/lineage/*.yaml)가 없는 케이스에 plan.yaml 로 계보를 그린다.
       처치 정의(plan.yaml) ─▶ 원천 데이터 ─▶ 분석 단위 패널 ─▶ 결과 지표 ─▶ 케이스
   id 는 'auto-<케이스>'. 시행일·가공 세부처럼 plan.yaml 에 없는 것은 지어내지 않는다.

계보 파일을 직접 쓰면 그쪽이 우선한다(같은 케이스를 used_by 로 가진 계보가 있으면 자동 계보를 만들지 않음).
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from .lineage import CASES_DIR, Lineage, Step

REPO = "https://github.com/CausalInferenceLab/policy-effect-analytics-agent"
AUTO = "auto-"
MAX_SOURCES = 6
MAX_METRICS = 3
# 데이터가 아니라 정책 근거(발표문·사례집·공고·회의록)인 줄 — 카탈로그에 없으면 계보의 데이터에서 뺀다
EVIDENCE = re.compile(r"발표|사례집|근거|공고|조례|회의록|고시문")


def _url_key(u: str | None) -> str:
    u = re.sub(r"^https?://(www\.)?", "", (u or "").split("#")[0].strip())
    return u.rstrip("/").lower()


def _plan(case: Path) -> dict:
    try:
        return yaml.safe_load((case / "plan.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def match_source(src: dict, datasets) -> str | None:
    """data_sources 한 줄 → 카탈로그 데이터셋 id (없으면 None)."""
    by_url = {_url_key(d.url): d.id for d in datasets}
    hit = by_url.get(_url_key(src.get("url")))
    if hit:
        return hit
    text = " ".join(str(src.get(k) or "") for k in ("name", "url", "notes"))
    for d in sorted(datasets, key=lambda d: -len(d.id)):  # 긴 id 먼저 (DT_1B26001_A01 > DT_1B26001)
        if len(d.id) >= 5 and re.search(rf"(?<![\w-]){re.escape(d.id)}(?![\w-])", text):
            return d.id
    return None


def case_sources(case: Path, datasets, plan: dict | None = None) -> list[dict]:
    """[{name, url, dataset}] — 합성 데이터·이름 없는 줄·정책 근거 문서는 뺀다. 같은 데이터셋은 한 번만."""
    plan = _plan(case) if plan is None else plan
    out, seen = [], set()
    for s in plan.get("data_sources") or []:
        if not isinstance(s, dict) or not s.get("name") or s.get("license") == "synthetic":
            continue
        did = match_source(s, datasets)
        if not did and EVIDENCE.search(s["name"]):
            continue
        key = did or _url_key(s.get("url")) or s["name"]
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": s["name"], "url": s.get("url"), "dataset": did})
    return out


def dataset_users(datasets, cases_dir: Path = CASES_DIR) -> dict[str, list[str]]:
    """데이터셋 id → 그 데이터를 쓴 케이스 목록."""
    users: dict[str, list[str]] = {}
    for case in sorted(cases_dir.iterdir()):
        if not case.is_dir() or case.name.startswith("_") or not (case / "plan.yaml").exists():
            continue
        for s in case_sources(case, datasets):
            if s["dataset"]:
                users.setdefault(s["dataset"], []).append(case.name)
    return users


def _first_sentence(text: str, n: int = 70) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    t = re.split(r"(?<=[.다])\s", t, maxsplit=1)[0]
    return t if len(t) <= n else t[: n - 1] + "…"


def auto_lineage(case: Path, datasets, topic: str | None, owner: str) -> Lineage | None:
    """plan.yaml → 계보. 처치 정의와 데이터가 하나도 없으면 None."""
    plan = _plan(case)
    treat = plan.get("treatment") or {}
    sources = case_sources(case, datasets, plan)
    if not isinstance(treat, dict) or not treat.get("definition") or not sources:
        return None
    steps = [
        Step(
            id="policy",
            kind="policy",
            label=_first_sentence(treat["definition"]),
            source=f"{REPO}/blob/main/cases/{case.name}/plan.yaml",
            note="plan.yaml 의 처치 정의. 시행일 근거는 그 케이스의 README·discussion.md 를 보세요.",
        )
    ]
    ds_ids = []
    for i, s in enumerate(sources[:MAX_SOURCES], 1):
        sid = f"ds{i}"
        ds_ids.append(sid)
        steps.append(
            Step(
                id=sid,
                kind="dataset",
                label=s["name"][:60],
                ref=s["dataset"],
                url=None if s["dataset"] else (s["url"] or None),
                status="done" if (s["dataset"] or s["url"]) else "missing",
            )
        )
    if len(sources) > MAX_SOURCES:
        steps[-1].note = f"이 밖에 데이터 {len(sources) - MAX_SOURCES}개 더 (plan.yaml)"
    unit = plan.get("unit") or {}
    tm = plan.get("time") or {}
    unit_name = unit.get("name", "분석 단위") if isinstance(unit, dict) else "분석 단위"
    freq = {
        "year": "연",
        "quarter": "분기",
        "month": "월",
        "week": "주",
        "day": "일",
        "hour": "시간",
    }
    freq_ko = freq.get(tm.get("freq"), tm.get("freq") or "시점") if isinstance(tm, dict) else "시점"
    keys = [
        k
        for k in (
            unit.get("id_col") if isinstance(unit, dict) else None,
            tm.get("col") if isinstance(tm, dict) else None,
        )
        if k
    ]
    steps.append(
        Step(
            id="panel",
            kind="transform",
            label=f"{_first_sentence(unit_name, 30)} × {freq_ko} 패널",
            inputs=ds_ids,
            how="fetch.py 가 원천 데이터를 받아 분석 단위 × 시점 표(data/panel.csv)로 만든다",
            keys=keys,
        )
    )
    outs = [o for o in plan.get("outcomes") or [] if isinstance(o, dict) and o.get("name")]
    outs.sort(key=lambda o: not o.get("primary"))
    for i, o in enumerate(outs[:MAX_METRICS], 1):
        steps.append(
            Step(
                id=f"m{i}",
                kind="metric",
                label=str(o["name"])[:40] + (" (주 지표)" if o.get("primary") else ""),
                inputs=["panel"],
                how=_first_sentence(o.get("definition") or o["name"], 90),
                used_by=[case.name],
            )
        )
    if not outs:  # 관측 통계 케이스 등: 지표 정의가 없으면 패널에서 바로 케이스로
        steps[-1].used_by = [case.name]
    return Lineage(
        id=f"{AUTO}{case.name}",
        owner=owner,
        topic=topic or "",
        title=str(plan.get("title") or case.name),
        question=str(plan.get("question") or "").strip(),
        steps=steps,
    )


def auto_lineages(datasets, registry: dict, hand: list[Lineage], cases_dir: Path = CASES_DIR):
    """손 계보가 없는 등록 케이스마다 자동 계보. registry: projects.yaml 의 {case: meta}."""
    covered = {c for lin in hand for s in lin.steps for c in s.used_by}
    out = []
    for name, meta in sorted(registry.items()):
        case = cases_dir / name
        if name in covered or not (case / "plan.yaml").exists():
            continue
        lin = auto_lineage(case, datasets, meta.get("topic"), meta.get("owner", ""))
        if lin:
            out.append(lin)
    return out


def is_auto(lin: Lineage) -> bool:
    return lin.id.startswith(AUTO)


def all_lineages() -> list[Lineage]:
    """손으로 쓴 계보 + 자동 계보 (사이트·API 가 쓰는 전체 목록)."""
    from .lineage import ROOT, load_lineages
    from .ontology import load_datasets

    hand = load_lineages()
    try:
        reg = yaml.safe_load((ROOT / "catalog" / "projects.yaml").read_text(encoding="utf-8"))
        registry = {p["case"]: p for p in (reg or {}).get("projects", []) if p.get("case")}
    except (OSError, yaml.YAMLError):
        registry = {}
    return hand + auto_lineages(load_datasets(), registry, hand)
