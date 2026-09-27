"""데이터 지도(온톨로지): 주제 · 이슈 · 데이터셋과 그 관계.

    주제(Topic) ──포함──▶ 이슈(Issue, 지금 논쟁 중인 정책)
       │                    │
       └──쓴다(역할)──▶ 데이터셋(Dataset) ──제공──▶ 포털(Portal)
                              │
                              ├─ 역할: 처치(누가·언제) / 결과(무엇이 변했나) / 통제(다른 요인)
                              ├─ 단위: 공간(시군구 등) × 시간(월 등)
                              └─ 접근: 오픈API·파일 + 승인 방식 + 라이선스

파일: catalog/topics.yaml · catalog/issues.yaml · catalog/datasets.yaml
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from .catalog import ROOT, Design, load_topics

Role = Literal["treatment", "outcome", "covariate"]
ROLE_KO = {
    "treatment": "처치 · 누가 언제",
    "outcome": "결과 · 무엇이 변했나",
    "covariate": "통제 · 다른 요인",
}
ROLE_SHORT = {"treatment": "처치", "outcome": "결과", "covariate": "통제"}
PORTAL_KO = {
    "data.go.kr": "공공데이터포털",
    "kosis": "KOSIS 국가통계포털",
    "seoul": "서울 열린데이터광장",
    "law": "법제처 국가법령정보",
    "airkorea": "에어코리아",
    "reb": "한국부동산원 R-ONE",
    "koroad": "도로교통공단",
    "komsco": "한국조폐공사",
    "other": "기타",
}
ACCESS_KO = {"open_api": "오픈API", "file": "파일", "manual": "수동"}
DESIGN_PLAIN = {
    "did_simultaneous": "같은 날 시작한 지역과 안 한 지역의 변화 차이를 비교 (이중차분)",
    "did_staggered": "지역마다 시작일이 다를 때, 아직 안 한 지역과 순서대로 비교 (시차 도입 이중차분)",
    "scm": "정책 지역이 몇 곳뿐일 때, 비슷한 지역을 섞어 '가상의 대조 지역'을 만듦 (합성통제)",
    "its": "대조 지역이 없을 때, 시행 전 추세가 이어졌다면의 값과 비교 (단절 시계열)",
}


class Dataset(BaseModel):
    id: str
    name: str
    provider: str
    portal: str
    url: str
    access: Literal["open_api", "file", "manual"]
    approval: str
    license: str
    license_note: str | None = None
    space: str
    time: str
    period: str = "미기재"
    measures: list[str] = []
    roles: list[Role]
    topics: list[str]
    notes: str | None = None
    verified: str


class Issue(BaseModel):
    id: str
    name: str
    topic: str
    issue: str
    effective: str
    effective_note: str | None = None
    source: str
    treatment: str
    control: str
    outcomes: list[str]
    design: Design
    datasets: list[str]
    pitfalls: list[str] = []
    difficulty: int


def load_datasets(path: Path = ROOT / "catalog" / "datasets.yaml") -> list[Dataset]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [Dataset.model_validate(d) for d in raw["datasets"]]


def load_issues(path: Path = ROOT / "catalog" / "issues.yaml") -> list[Issue]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [Issue.model_validate(d) for d in raw["issues"]]


def check_links() -> list[str]:
    """깨진 관계를 찾는다: 없는 주제·데이터셋을 가리키는 항목, 중복 id."""
    topics = {t.id for t in load_topics()}
    ds = load_datasets()
    ids = [d.id for d in ds]
    errs = [f"중복 데이터셋 id: {i}" for i in {i for i in ids if ids.count(i) > 1}]
    errs += [f"{d.id}: 없는 주제 {t}" for d in ds for t in d.topics if t not in topics]
    for i in load_issues():
        if i.topic not in topics:
            errs.append(f"{i.id}: 없는 주제 {i.topic}")
        errs += [f"{i.id}: 없는 데이터셋 {x}" for x in i.datasets if x not in ids]
    return errs
