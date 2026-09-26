"""discover(): 소셜 반응 한 건을 정책·데이터셋·분석계획까지 잇는다."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .catalog import ROOT, Policy, load_catalog
from .match import Match, match_issue
from .search import SearchHit, search_datago


@dataclass
class DiscoveryResult:
    text: str
    matches: list[Match]
    live_hits: list[SearchHit] = field(default_factory=list)
    live_status: str = "실시간 검색 안 함"

    @property
    def top(self) -> Policy | None:
        return self.matches[0].policy if self.matches else None

    @property
    def sample_case(self) -> Path | None:
        p = self.top
        return ROOT / p.sample_case if p and p.sample_case else None

    @property
    def next_step(self) -> str:
        p = self.top
        if p is None:
            return "카탈로그에서 정책을 찾지 못했습니다. 정책명이나 지역·시점을 넣어 다시 입력하거나, catalog/policies.yaml 에 정책을 추가하세요."
        if self.sample_case and (self.sample_case / "plan.yaml").exists():
            return f"사전 등록된 분석계획이 있습니다: {p.sample_case} → Flow 로 효과 분석을 실행하세요."
        if p.support != "지원":
            return f"설계가 '{p.design_ko}'입니다. 추정 모듈 {p.support}. 지금은 데이터 수집과 plan.yaml 작성까지 진행하세요."
        return "cases/_template 을 복사해 이 정책의 plan.yaml 을 작성하고 PR 로 사전 등록하세요."


def discover(
    text: str,
    live_search: bool = False,
    use_llm: bool = False,
    catalog: list[Policy] | None = None,
) -> DiscoveryResult:
    cat = catalog if catalog is not None else load_catalog()
    res = DiscoveryResult(text=text, matches=match_issue(text, cat, use_llm=use_llm))
    if live_search and res.top and res.top.search_terms:
        res.live_hits, res.live_status = search_datago(res.top.search_terms)
    return res
