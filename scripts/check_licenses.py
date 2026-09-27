"""이 프로젝트가 끌어오는 파이썬 패키지 중 GPL·AGPL 라이선스가 있는지 확인한다 (CI에서 실행).

이 프로젝트는 MIT입니다. GPL·AGPL 패키지를 필수 의존성으로 넣으면 배포 조건이 바뀔 수 있어 막습니다.
- 확인 범위: policy-effect-analytics-agent 와 선택 설치(agent, causal)가 끌어오는 의존성 전체 (설치된 것만)
- 허용: MIT·BSD·Apache 등, 그리고 LGPL·MPL 같은 약한 카피레프트, 여러 라이선스 중 고를 수 있는 경우(예: Apache 또는 GPL)
- 꼭 필요하면 선택 설치로 분리하고 ALLOW 에 이유와 함께 적습니다.

    python scripts/check_licenses.py
"""

from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError, distribution

from packaging.requirements import Requirement

ROOT_PKG = "policy-effect-analytics-agent"
EXTRAS = {"agent", "causal"}
ALLOW: dict[str, str] = {}  # {"패키지 이름": "허용 이유"}

STRONG = re.compile(r"\bA?GPL\b|GNU (Affero )?General Public License", re.I)
PERMISSIVE = re.compile(
    r"\bMIT\b|\bBSD\b|Apache|\bISC\b|\bPSF\b|Python Software Foundation|MPL|Mozilla", re.I
)


def canon(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def license_text(dist) -> str:
    md = dist.metadata
    parts = [
        md.get("License-Expression") or "",
        (md.get("License") or "").splitlines()[0][:120] if md.get("License") else "",
    ]
    parts += [
        c.split("::")[-1].strip()
        for c in md.get_all("Classifier") or []
        if c.startswith("License ::")
    ]
    return " | ".join(p for p in parts if p)


def is_blocked(text: str) -> bool:
    """강한 카피레프트만 있고 다른 선택지가 없으면 막는다. LGPL(Lesser)은 허용."""
    strong = STRONG.sub(
        "", re.sub(r"LGPL|Lesser General Public License|Library or Lesser", "", text, flags=re.I)
    )
    if strong == re.sub(
        r"LGPL|Lesser General Public License|Library or Lesser", "", text, flags=re.I
    ):
        return False  # GPL·AGPL 언급 없음
    return not PERMISSIVE.search(text)


def walk(root: str, extras: set[str]) -> dict[str, str]:
    seen: dict[str, str] = {}
    stack: list[tuple[str, set[str]]] = [(root, extras)]
    while stack:
        name, ex = stack.pop()
        key = canon(name)
        if key in seen:
            continue
        try:
            dist = distribution(name)
        except PackageNotFoundError:
            continue
        seen[key] = license_text(dist)
        for raw in dist.requires or []:
            req = Requirement(raw)
            env_ok = req.marker is None or any(
                req.marker.evaluate({"extra": e}) for e in (ex or {""})
            )
            if env_ok:
                stack.append((req.name, set(req.extras)))
    return seen


def main() -> int:
    tree = walk(ROOT_PKG, EXTRAS)
    if not tree:
        print(f"{ROOT_PKG} 가 설치되어 있지 않습니다: pip install -e .")
        return 1
    bad = [f"{n}: {t}" for n, t in sorted(tree.items()) if n not in ALLOW and is_blocked(t)]
    if bad:
        print("GPL·AGPL 라이선스 의존성이 있습니다 (CONTRIBUTING.md 6절 참고):")
        print("\n".join(f"  - {b}" for b in bad))
        return 1
    print(f"라이선스 확인: 의존성 {len(tree)}개 중 GPL·AGPL 없음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
