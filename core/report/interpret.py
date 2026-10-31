"""판정을 넘지 않으면서 결과에서 '그래도 말할 수 있는 것'을 문장으로 만든다.

- 배제 범위(rule-out): 95% 범위 밖의 큰 효과는 이 자료와 맞지 않는다. 효과가 있었는지 판별하지 못한 결과에서도 쓸 수 있다.
- 검출 한계(대략의 최소 검출 효과, MDE): 설계가 80% 확률로 잡아낼 수 있는 효과 크기.
  95% 범위 폭으로 표준오차를 거꾸로 구해(폭 / 3.92) 2.8배 한다. **계획 단계용**이다 — 결과를 본 뒤의 '사후 검정력'은
  관측 추정치에 끌려가 해석을 흐리므로, 결과 화면에는 배제 범위만 쓴다.
로그 지표는 %로 바꿔 말한다. 범위가 로그 1.0 보다 넓으면(%로 바꾸면 의미가 없을 만큼) 문장을 만들지 않는다.
판단 불가(not_identified) 결과는 비교 자체가 성립하지 않았으므로 어떤 문장도 만들지 않는다.
"""

from __future__ import annotations

import math

Z95, Z80 = 1.959964, 0.841621
WIDE_LOG = 1.0


def is_log(col: str, unit: str | None = None) -> bool:
    u = (unit or "").lower()
    return (col or "").startswith("log") or "log" in u or "로그" in u


def _u(unit: str | None) -> str:
    if not unit:
        return ""
    return unit if unit in ("%", "%p") else f" {unit}"


def fmt(v: float, col: str, unit: str | None = None) -> str:
    if is_log(col, unit):
        return f"{(math.exp(v) - 1) * 100:+.1f}%"
    return f"{v:+.3g}{_u(unit)}"


def _ok(lo, hi, col, unit) -> bool:
    if lo is None or hi is None or any(map(math.isnan, (lo, hi))) or hi < lo:
        return False
    return not (is_log(col, unit) and hi - lo > WIDE_LOG)


def bounds(lo, hi, col: str, unit: str | None = None) -> tuple[str, str] | None:
    """(하한, 상한) 문자열. 쓸 수 없으면 None."""
    if not _ok(lo, hi, col, unit):
        return None
    return fmt(lo, col, unit), fmt(hi, col, unit)


def mde(lo, hi, col: str, unit: str | None = None) -> str | None:
    """대략의 최소 검출 효과(80% 검정력, 양측 5%). 쓸 수 없으면 None."""
    if not _ok(lo, hi, col, unit):
        return None
    m = (hi - lo) / (2 * Z95) * (Z95 + Z80)
    if is_log(col, unit):
        return f"{(math.exp(m) - 1) * 100:.1f}%"
    return f"{m:.3g}{_u(unit)}"


def rule_out_sentence(name: str, lo, hi, col: str, unit: str | None = None) -> str:
    b = bounds(lo, hi, col, unit)
    if not b:
        return ""
    return (
        f"{name}: {b[1]}보다 큰 증가나 {b[0]}보다 큰 감소는 이 자료와 맞지 않습니다"
        "(설계 가정이 맞다는 전제)."
    )


def statements(verdict: str, name: str, lo, hi, col: str, unit: str | None = None) -> dict:
    """결과 화면·리포트·API에 쓸 수 있는 문장. 지금은 '크기를 판별하지 못함'의 배제 범위만."""
    if verdict != "conditional":
        return {}
    ro = rule_out_sentence(name, lo, hi, col, unit)
    return {"rule_out": ro} if ro else {}
