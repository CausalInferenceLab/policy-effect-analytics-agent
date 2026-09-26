"""모든 추정기가 공통으로 반환하는 결과 객체."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import pandas as pd

Verdict = Literal["identified", "conditional", "not_identified"]


@dataclass
class EffectResult:
    method: str
    outcome: str
    estimate: float
    se: float
    ci_low: float
    ci_high: float
    p_value: float
    n_obs: int
    n_clusters: int | None = None
    assumptions_checked: dict[str, Any] = field(default_factory=dict)  # 이름 -> {passed, stat, ...}
    warnings: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)  # 발생한 abstention 트리거 코드
    verdict: Verdict = "identified"
    extra: dict[str, Any] = field(default_factory=dict)  # 예: event study 계수표

    @property
    def identified(self) -> bool:
        return self.verdict == "identified"

    def warn(self, msg: str, trigger: str | None = None) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)
        if trigger and trigger not in self.triggers:
            self.triggers.append(trigger)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["identified"] = self.identified
        d["extra"] = {
            k: (
                v.to_dict("records")
                if isinstance(v, pd.DataFrame)
                else v.tolist()
                if hasattr(v, "tolist")
                else v
            )
            for k, v in self.extra.items()
        }
        return d

    def summary_ko(self) -> str:
        label = {"identified": "식별됨", "conditional": "조건부", "not_identified": "식별 불가"}[
            self.verdict
        ]
        s = (
            f"[{self.method}] {self.outcome}: 효과 {self.estimate:.3f} "
            f"(95% CI {self.ci_low:.3f} ~ {self.ci_high:.3f}, p={self.p_value:.3g}, "
            f"N={self.n_obs}, 클러스터={self.n_clusters}) → 판정: {label}"
        )
        return s + "".join(f"\n  - 경고: {w}" for w in self.warnings)
