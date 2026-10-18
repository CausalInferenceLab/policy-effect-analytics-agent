"""데이터 계보(Lineage) — 공공 이슈에서 출발해 정책·원천 데이터·가공·지표·분석까지 이어지는 길.

트랙 A(데이터 온톨로지)의 산출물입니다. 한 파일(catalog/lineage/<내ID>-<주제>.yaml)이 한 개의 길을 적습니다.

    이슈 ──▶ 정책(법령·공고·발표) ──▶ 원천 데이터 ──▶ 가공 ──▶ 지표 ──▶ 분석(cases/)

- step.kind
    issue     : catalog/issues.yaml 의 id                         (ref 필수)
    policy    : 법령·행정규칙 이름(법제처 스냅샷) 또는 발표 자료       (ref 또는 source 필수)
    dataset   : catalog/datasets.yaml 의 id, 없으면 url 필수 → 카탈로그에 추가 권장
    transform : 가공 단계. inputs(앞 단계 id)와 how(무엇을 했나), keys(결합 키)
    metric    : 분석에 쓰는 지표. inputs, how(계산식), used_by(쓰는 케이스)
- validate() 는 오류(틀린 참조)와 경고(카탈로그에 없음 등)를 나눠 돌려줍니다.
- graph() 는 카탈로그(주제·이슈·데이터셋·근거 법률·케이스)에서 자동으로 만든 연결과
  계보 파일의 연결을 합친 그래프를 만들어, 사이트와 JSON API(api/lineage.json)에 씁니다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .catalog import load_catalog, load_topics
from .ontology import load_datasets, load_issues

ROOT = Path(__file__).resolve().parents[2]
LINEAGE_DIR = ROOT / "catalog" / "lineage"
SNAP_DIR = ROOT / "catalog" / "snapshots"
CASES_DIR = ROOT / "cases"

Kind = Literal["issue", "policy", "dataset", "transform", "metric"]
KIND_KO = {
    "issue": "이슈",
    "policy": "정책",
    "dataset": "원천 데이터",
    "transform": "가공",
    "metric": "지표",
    "case": "분석",
}
ID = re.compile(r"^[a-z0-9][a-z0-9_]*$")
DATE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?$")


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="이 파일 안에서 쓰는 짧은 이름 (소문자·숫자·_)")
    kind: Kind
    label: str = ""
    ref: str | None = None  # issue id · dataset id · 법령/행정규칙 이름
    source: str | None = None  # 근거 URL (정책 발표문, 데이터 페이지 등)
    url: str | None = None  # 카탈로그에 없는 데이터셋의 주소
    date: str | None = None  # 정책 시행일 등 (YYYY-MM-DD 또는 YYYY-MM)
    inputs: list[str] = []
    how: str = ""
    keys: list[str] = []
    used_by: list[str] = []  # cases/ 폴더 이름
    note: str = ""

    @model_validator(mode="after")
    def _check(self):
        if not ID.match(self.id):
            raise ValueError(f"step id '{self.id}' 는 소문자·숫자·_ 만 씁니다")
        if self.date and not DATE.match(self.date):
            raise ValueError(
                f"{self.id}: date '{self.date}' 는 YYYY-MM-DD 또는 YYYY-MM 로 적습니다"
            )
        if self.kind in {"issue"} and not self.ref:
            raise ValueError(f"{self.id}: issue 는 ref(issues.yaml id)가 필요합니다")
        if self.kind == "policy" and not (self.ref or self.source):
            raise ValueError(
                f"{self.id}: policy 는 ref(법령 이름) 또는 source(발표 URL)가 필요합니다"
            )
        if self.kind == "dataset" and not (self.ref or self.url):
            raise ValueError(f"{self.id}: dataset 은 ref(datasets.yaml id) 또는 url 이 필요합니다")
        if self.kind in {"transform", "metric"} and not self.inputs:
            raise ValueError(f"{self.id}: {self.kind} 는 inputs(앞 단계)가 필요합니다")
        if self.kind in {"transform", "metric"} and not self.how:
            raise ValueError(f"{self.id}: {self.kind} 는 how(무엇을 했나)가 필요합니다")
        return self

    @property
    def title(self) -> str:
        return self.label or self.ref or self.id


class Lineage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    owner: str  # GitHub ID
    topic: str  # topics.yaml id
    title: str
    question: str = ""
    steps: list[Step]

    @model_validator(mode="after")
    def _order(self):
        seen: set[str] = set()
        for s in self.steps:
            if s.id in seen:
                raise ValueError(f"step id 중복: {s.id}")
            missing = [i for i in s.inputs if i not in seen]
            if missing:
                raise ValueError(
                    f"{s.id}: inputs {missing} 가 앞에 없습니다 (원천 → 가공 → 지표 순서로 적습니다)"
                )
            seen.add(s.id)
        return self


def load_lineages(path: Path = LINEAGE_DIR) -> list[Lineage]:
    out = []
    for f in sorted(path.glob("*.yaml")):
        if f.name.startswith("_"):
            continue
        out.append(Lineage.model_validate(yaml.safe_load(f.read_text(encoding="utf-8"))))
    return out


def _legal_names(topic: str) -> set[str]:
    f = SNAP_DIR / f"legal_{topic}.csv"
    return set(pd.read_csv(f, dtype=str)["name"].dropna()) if f.exists() else set()


def validate(lin: Lineage, file_stem: str | None = None) -> tuple[list[str], list[str]]:
    """(오류, 경고). 오류가 있으면 CI가 실패합니다."""
    errors, warns = [], []
    topics = {t.id for t in load_topics()}
    issues = {i.id: i for i in load_issues()}
    datasets = {d.id for d in load_datasets()}
    legal = _legal_names(lin.topic)
    if lin.topic not in topics:
        errors.append(f"topic '{lin.topic}' 이 topics.yaml 에 없습니다")
    if file_stem and file_stem != lin.id:
        errors.append(f"파일 이름({file_stem}.yaml)과 id({lin.id})가 다릅니다")
    for s in lin.steps:
        if s.kind == "issue" and s.ref not in issues:
            errors.append(f"{s.id}: issue '{s.ref}' 가 issues.yaml 에 없습니다")
        if s.kind == "dataset":
            if s.ref and s.ref not in datasets:
                errors.append(
                    f"{s.id}: dataset '{s.ref}' 가 datasets.yaml 에 없습니다 (새 데이터면 ref 대신 url)"
                )
            if not s.ref:
                warns.append(
                    f"{s.id}: 카탈로그에 없는 데이터({s.url}) → datasets.yaml 에 추가하면 데이터 지도에 나옵니다"
                )
        if s.kind == "policy" and s.ref and s.ref not in legal and not s.source:
            warns.append(
                f"{s.id}: '{s.ref}' 는 법제처 스냅샷에 없습니다 → source(발표 URL)를 함께 적어 주세요"
            )
        for c in s.used_by:
            if not (CASES_DIR / c).is_dir():
                warns.append(f"{s.id}: used_by '{c}' 케이스 폴더가 아직 없습니다")
    if not any(s.kind == "metric" for s in lin.steps):
        warns.append("metric 단계가 없습니다 — 계보는 분석에 쓰는 지표까지 이어져야 합니다")
    return errors, warns


# ─── 그래프 ───────────────────────────────────────────────────────────────────
def _case_topics(policies) -> dict[str, str]:
    """cases/<폴더> → 주제 id (policies.yaml sample_case 와 계보 used_by 로 연결)."""
    out = {}
    pol_topic = {p: t.id for t in load_topics() for p in t.policies}
    for p in policies:
        if p.sample_case and p.id in pol_topic:
            out[Path(p.sample_case).name] = pol_topic[p.id]
    return out


def graph(lineages: list[Lineage] | None = None) -> dict:
    """주제를 중심으로 이슈·근거 법률·데이터셋·케이스·계보 단계를 잇는 그래프 (JSON 직렬화 가능)."""
    lineages = load_lineages() if lineages is None else lineages
    topics, issues, datasets = load_topics(), load_issues(), load_datasets()
    policies = load_catalog()
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def node(nid, kind, label, **kw):
        nodes.setdefault(nid, {"id": nid, "kind": kind, "label": label, **kw})

    for t in topics:
        node(f"topic:{t.id}", "topic", t.name)
        for law in t.legal.laws if t.legal else []:
            node(f"law:{law}", "policy", law)
            edges.append({"from": f"law:{law}", "to": f"topic:{t.id}", "rel": "근거"})
    for i in issues:
        node(f"issue:{i.id}", "issue", i.name, date=i.effective)
        edges.append({"from": f"issue:{i.id}", "to": f"topic:{i.topic}", "rel": "속함"})
        for d in i.datasets:
            edges.append({"from": f"dataset:{d}", "to": f"issue:{i.id}", "rel": "씀"})
    for d in datasets:
        node(f"dataset:{d.id}", "dataset", d.name, url=d.url, roles=d.roles)
        for t in d.topics:
            edges.append({"from": f"dataset:{d.id}", "to": f"topic:{t}", "rel": "/".join(d.roles)})
    for case, topic in _case_topics(policies).items():
        node(f"case:{case}", "case", case)
        edges.append({"from": f"topic:{topic}", "to": f"case:{case}", "rel": "분석"})
    for lin in lineages:
        local = {}
        for s in lin.steps:
            if s.kind == "issue":
                nid = f"issue:{s.ref}"
            elif s.kind == "dataset" and s.ref:
                nid = f"dataset:{s.ref}"
            else:
                nid = f"{lin.id}:{s.id}"
                node(
                    nid,
                    s.kind,
                    s.title,
                    lineage=lin.id,
                    how=s.how,
                    date=s.date,
                    source=s.source or s.url,
                )
            local[s.id] = nid
            if s.kind in {
                "issue",
                "policy",
            }:  # 이슈·정책은 주제에 붙여 그래프에서 고립되지 않게 한다
                edges.append(
                    {"from": nid, "to": f"topic:{lin.topic}", "rel": "근거", "lineage": lin.id}
                )
            for i in s.inputs:
                edges.append(
                    {
                        "from": local[i],
                        "to": nid,
                        "rel": "가공" if s.kind == "transform" else "계산",
                        "lineage": lin.id,
                    }
                )
            for c in s.used_by:
                node(f"case:{c}", "case", c)
                edges.append({"from": nid, "to": f"case:{c}", "rel": "씀", "lineage": lin.id})
        node(f"topic:{lin.topic}", "topic", lin.topic)
    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "lineages": [lin.model_dump() for lin in lineages],
    }


def depth(lin: Lineage) -> dict[str, int]:
    """그리기용: 각 단계의 열 번호. 입력이 없는 단계는 종류 순서(이슈·정책 → 데이터)로 놓는다."""
    base = {"issue": 0, "policy": 0, "dataset": 1, "transform": 2, "metric": 3}
    d: dict[str, int] = {}
    for s in lin.steps:
        d[s.id] = max([base[s.kind]] + [d[i] + 1 for i in s.inputs])
    return d
