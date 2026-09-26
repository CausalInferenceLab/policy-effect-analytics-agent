"""소셜 반응 → 주제 → 주제 안의 정책 전체 → 데이터셋 → 분석계획 (Flow ① 앞단).

원칙(출발 키트 B): 소셜 신호는 '어느 주제를 볼지'까지만 정한다. 화제가 된 정책 하나만
골라 분석하면 결과를 보고 사례를 고르는 셈이 되어 효과가 과대 추정된다.

    from core.discovery import discover
    r = discover("토허제 확대하고 강남 집값 잡혔나요?")
    r.matches[0].policy.name, r.datasets, r.sample_case

규칙
- 정책 식별은 카탈로그(catalog/policies.yaml) 키워드 매칭이 기본이다. LLM이 설정돼 있으면
  후보 중 하나를 고르는 보조 역할만 하고, 카탈로그에 없는 정책을 만들어 내지 못한다.
- 데이터셋 추천 = 카탈로그에 검증해 둔 데이터셋 + (선택) 공공데이터포털 실시간 검색.
- 분석 방법은 LLM이 아니라 카탈로그의 design(규칙 기반 판별 결과)으로 정한다.
"""

from .catalog import Dataset, Policy, Topic, load_catalog, load_topics
from .match import Match, TopicMatch, match_issue, match_topic
from .pipeline import DiscoveryResult, discover
from .search import SearchHit, search_datago

__all__ = [
    "Dataset",
    "Policy",
    "load_catalog",
    "Topic",
    "load_topics",
    "TopicMatch",
    "match_topic",
    "Match",
    "match_issue",
    "SearchHit",
    "search_datago",
    "DiscoveryResult",
    "discover",
]
