"""정책 × 데이터셋 카탈로그 로더."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = ROOT / "catalog" / "policies.yaml"

Design = Literal["did_simultaneous", "did_staggered", "scm", "its"]

# core 가 지금 추정할 수 있는 설계 (나머지는 추정 모듈 준비 중 → 보류 판정)
SUPPORTED: dict[str, str] = {
    "did_simultaneous": "지원",
    "its": "지원",
    "did_staggered": "준비 중 (W4, Callaway–Sant'Anna)",
    "scm": "준비 중 (W5, 합성통제)",
}
DESIGN_KO = {
    "did_simultaneous": "이중차분(동시 도입)",
    "did_staggered": "이중차분(시차 도입)",
    "scm": "합성통제",
    "its": "단절 시계열",
}


class Dataset(BaseModel):
    id: str
    name: str
    provider: str
    url: str
    access: Literal["api_key", "file", "manual"]
    license: str
    granularity: str = ""
    role: Literal["outcome", "treatment", "covariate"] = "outcome"


class Policy(BaseModel):
    id: str
    name: str
    keywords: list[str]
    summary: str
    announced: date | None = None
    effective: date | None = None
    sources: list[str] = []
    unit: str
    treated_units: list[str] = []
    control_units: str | None = None
    outcomes: list[str]
    design: Design
    datasets: list[Dataset] = Field(..., min_length=1)
    search_terms: list[str] = []
    pitfalls: list[str] = []
    sample_case: str | None = None

    @property
    def support(self) -> str:
        return SUPPORTED[self.design]

    @property
    def design_ko(self) -> str:
        return DESIGN_KO[self.design]


def load_catalog(path: str | Path = DEFAULT_CATALOG) -> list[Policy]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [Policy.model_validate(p) for p in raw["policies"]]
