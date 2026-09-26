"""소셜 반응 텍스트 → 카탈로그 정책 매칭.

기본은 결정론적 키워드 점수(긴 키워드일수록 가중). LLM 이 설정돼 있으면 상위 후보 중
하나를 고르고 이유를 한 줄로 달게 하되, 카탈로그 밖의 답은 버린다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .catalog import Policy


@dataclass
class Match:
    policy: Policy
    score: float
    hits: list[str]
    reason: str = ""
    picked_by: str = "keyword"  # keyword | llm
    extra: dict = field(default_factory=dict)


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


def score(text: str, p: Policy) -> tuple[float, list[str]]:
    t = _norm(text)
    hits = [k for k in p.keywords if _norm(k) in t]
    # 긴 키워드(고유명사)에 가중: '토지거래허가'(6자) > '집값'(2자)
    return float(sum(min(len(_norm(k)), 6) for k in hits)), hits


def match_issue(
    text: str, catalog: list[Policy], top_k: int = 3, use_llm: bool = False
) -> list[Match]:
    scored = sorted(
        (Match(p, *score(text, p)) for p in catalog), key=lambda m: m.score, reverse=True
    )
    out = [m for m in scored if m.score > 0][:top_k]
    for m in out:
        m.reason = "키워드 일치: " + ", ".join(m.hits)
    if use_llm and out:
        _llm_pick(text, out)
    return out


def _llm_pick(text: str, cands: list[Match]) -> None:
    """LLM 이 후보 중 하나를 고르게 한다. 실패하거나 목록 밖이면 키워드 순위를 유지."""
    from ..agent import llm

    if not llm.configured():
        return
    menu = "\n".join(f"- {m.policy.id}: {m.policy.name} — {m.policy.summary}" for m in cands)
    sys_msg = (
        "너는 공공정책 분석 보조자다. 사용자의 글이 어떤 정책에 대한 반응인지 후보 중에서만 고른다. "
        'JSON 한 줄로만 답한다: {"id": "<후보 id 또는 none>", "reason": "<한 문장>"}'
    )
    try:
        ans = json.loads(llm.strip_fence(llm.chat(sys_msg, f"글:\n{text}\n\n후보:\n{menu}")))
    except Exception:  # noqa: BLE001 - LLM 실패는 키워드 결과로 대체
        return
    for i, m in enumerate(cands):
        if m.policy.id == ans.get("id"):
            m.picked_by, m.reason = "llm", f"LLM: {ans.get('reason', '')} ({m.reason})"
            cands.insert(0, cands.pop(i))
            return
