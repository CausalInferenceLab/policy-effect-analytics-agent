"""분석계획(plan.yaml) 스키마.

케이스마다 `plan.yaml` 하나로 "무엇을, 어떤 가정 아래, 어떤 방법으로 추정하고,
어떤 조건이면 답을 보류(abstain)하는가"를 선언한다. 에이전트(W3~)는 이 스키마를
채우는 것이 목표이고, 추정 모듈(W4~5)은 이 스키마만 읽고 실행한다.

사용:
    from core.schema.plan import load_plan
    plan = load_plan("cases/_example_night_clinic/plan.yaml")
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

# 공공누리(KOGL) 유형 + 기타. 1유형(출처표시)만 상업적 이용·변경 모두 허용.
License = Literal[
    "KOGL-1",  # 공공누리 제1유형: 출처표시
    "KOGL-2",  # 제2유형: 출처표시 + 상업적 이용금지
    "KOGL-3",  # 제3유형: 출처표시 + 변경금지
    "KOGL-4",  # 제4유형: 출처표시 + 상업적 이용금지 + 변경금지
    "CC-BY-4.0",
    "CC0",
    "synthetic",  # 합성 데이터 (실데이터 아님)
    "other",
]

Method = Literal["did", "event_study", "its"]

# 기계적으로 평가 가능한 보류(abstention) 트리거 목록.
# core.estimators.diagnostics.apply_abstention 이 EffectResult 에 적용한다.
AbstainTrigger = Literal[
    "pretrend_rejected",  # 사전추세 결합검정 p < pretrend_alpha
    "few_clusters",  # 클러스터 수 < min_clusters
    "staggered_adoption",  # 도입시점이 여러 개인데 TWFE 사용
    "placebo_significant",  # 가짜 도입시점 검정이 유의
    "ci_crosses_zero",  # 신뢰구간이 0을 포함 (효과 '없음'이 아니라 '불확실')
    "short_pre_period",  # 사전 기간 관측치 부족
]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 오타 필드 즉시 오류


class Unit(_Base):
    name: str = Field(..., description="분석 단위 (예: 시군구)")
    id_col: str


class TimeSpec(_Base):
    col: str
    freq: Literal["year", "quarter", "month", "week", "day"] = "year"
    start: int | str
    end: int | str


class Treatment(_Base):
    definition: str = Field(..., description="처치(정책)의 조작적 정의")
    group_col: str = Field(..., description="처치집단 여부(0/1) 컬럼")
    first_treat_col: str | None = Field(
        None, description="단위별 최초 처치 시점 컬럼 (미처치=결측). 시차도입이면 필수"
    )
    treat_time: int | str | None = Field(None, description="단일 도입 시점 (동시 도입일 때)")

    @model_validator(mode="after")
    def _need_timing(self):
        if self.treat_time is None and self.first_treat_col is None:
            raise ValueError("treat_time 또는 first_treat_col 중 하나는 필요합니다")
        return self


class Control(_Base):
    definition: str
    rationale: str = Field(..., description="왜 이 집단이 반사실(counterfactual)로 적절한가")


class Outcome(_Base):
    name: str
    col: str
    definition: str
    unit: str | None = None
    primary: bool = False
    expected_direction: Literal["increase", "decrease", "unknown"] = "unknown"


class EstimatorSpec(_Base):
    method: Method
    cluster_col: str | None = None
    covariates: list[str] = []
    ref_period: int = Field(-1, description="event study 기준 상대시점")
    window: tuple[int, int] = Field((-4, 4), description="event study 상대시점 범위 (양끝 binning)")
    alpha: float = 0.05


class Assumption(_Base):
    name: str
    description: str
    check: Literal["pretrend_test", "placebo_time", "manual", "none"] = "manual"


class Refutation(_Base):
    kind: Literal["placebo_time", "placebo_outcome", "drop_unit"]
    params: dict = {}


class AbstentionRule(_Base):
    when: AbstainTrigger
    verdict: Literal["not_identified", "conditional"] = "conditional"
    note: str = ""


class DataSource(_Base):
    name: str
    provider: str = Field(..., description="예: KOSIS, 공공데이터포털, 서울 열린데이터광장")
    url: str | None = None
    license: License
    adapter: str | None = Field(None, description="core.adapters 의 어댑터 이름")
    path: str = Field("data/panel.csv", description="케이스 폴더 기준 분석용 스냅샷 경로")
    query: dict = Field({}, description="어댑터 fetch() 인자 (fetch.py 가 없을 때 사용)")
    notes: str = ""


class Thresholds(_Base):
    pretrend_alpha: float = 0.10
    min_clusters: int = 20
    min_pre_periods: int = 3


class Plan(_Base):
    case_id: str
    title: str
    question: str
    synthetic_data: bool = Field(
        False, description="합성 데이터면 반드시 true — 리포트에 경고 표시"
    )
    unit: Unit
    time: TimeSpec
    treatment: Treatment
    control: Control
    outcomes: list[Outcome] = Field(..., min_length=1)
    estimator: EstimatorSpec
    assumptions: list[Assumption] = Field(..., min_length=1)
    refutations: list[Refutation] = []
    abstention: list[AbstentionRule] = Field(..., min_length=1)
    thresholds: Thresholds = Thresholds()
    data_sources: list[DataSource] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _consistency(self):
        if self.synthetic_data != any(d.license == "synthetic" for d in self.data_sources):
            raise ValueError("synthetic_data 플래그와 data_sources.license='synthetic' 이 불일치")
        if self.estimator.method == "its" and self.treatment.treat_time is None:
            raise ValueError("ITS 는 단일 treat_time 이 필요합니다")
        return self

    @property
    def primary_outcome(self) -> Outcome:
        return next((o for o in self.outcomes if o.primary), self.outcomes[0])


def load_plan(path: str | Path) -> Plan:
    """YAML 파일을 읽어 검증된 Plan 을 반환. 스키마 위반 시 pydantic.ValidationError."""
    with open(path, encoding="utf-8") as f:
        return Plan.model_validate(yaml.safe_load(f))
