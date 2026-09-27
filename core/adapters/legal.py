"""법령·정책 온톨로지 수집기 — 법제처 국가법령정보 공동활용 OPEN API.

주제 하나에 '근거 법률'과 '행정규칙 검색어'만 적어 두면, 관련된 것을 모두 따라가 모읍니다.

    근거 법률 ──연혁──▶ 법률·시행령·시행규칙의 모든 개정 (공포일·시행일)
        └──체계도──▶ 하위 행정규칙(훈령·고시·공고) · 자치법규(조례·규칙)
    행정규칙 검색어 ──이력──▶ 지정·해제 공고 (예: 투기과열지구 지정, 조정대상지역 지정 해제)
    기간 조회 ──▶ 최근 N일 사이 바뀐 것 (변경 감지)

- 인증: LAW_OC 환경변수 (open.law.go.kr 에서 신청한 OC). 값은 레포·로그·결과 파일 어디에도 남기지 않습니다.
  API 응답의 상세 링크에는 OC 가 들어 있으므로 링크는 버리고, OC 없는 공개 주소(law.go.kr/법령/이름)를 새로 만듭니다.
- 이용 조건: 영리 포함 자유 이용, **출처 표시 필수** ("출처: 법제처 국가법령정보센터"). 메타데이터만 저장합니다.
- 한계: 지자체 고시·공고(예: 서울시 토지거래허가구역 지정)와 금융당국 행정지도(예: 대출 한도)는 이 API에 없습니다.
  그런 사건은 topics.yaml 의 events 에 사람이 출처와 함께 적습니다.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from datetime import date
from urllib.parse import quote

import pandas as pd

from .base import MissingAPIKey, load_env

BASE = "https://www.law.go.kr/DRF"
ATTRIBUTION = "출처: 법제처 국가법령정보센터 (law.go.kr)"
COLUMNS = [
    "group",  # 법령 | 행정규칙 | 자치법규
    "kind",  # 법률·대통령령·부령 / 고시·공고·훈령 / 조례·규칙
    "name",
    "seed",  # 어떤 씨앗(근거 법률·검색어)에서 왔나
    "relation",  # 연혁 | 체계도 | 이력
    "change",  # 제정 · 일부개정 · 폐지 ...
    "announced",  # 공포일(법령) · 발령일(행정규칙) YYYY-MM-DD
    "effective",  # 시행일
    "status",  # 현행 · 연혁 · 시행예정
    "ministry",
    "law_id",
    "url",  # OC 없는 공개 주소
]


class LawAPIError(RuntimeError):
    pass


def _d(s: str | None) -> str:
    s = (s or "").strip()
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() and s != "99991231" else ""


def public_url(group: str, name: str) -> str:
    path = {"법령": "법령", "행정규칙": "행정규칙", "자치법규": "자치법규"}[group]
    return f"https://www.law.go.kr/{path}/{quote(name)}"


def _as_list(x) -> list:
    if x is None or x == "":
        return []
    return x if isinstance(x, list) else [x]


class LawClient:
    """재시도·속도 제한·OC 가림을 담당하는 얇은 클라이언트."""

    def __init__(self, oc: str | None = None, pause: float = 0.4, session=None):
        load_env()
        self.oc = oc or os.getenv("LAW_OC", "")
        if not self.oc:
            raise MissingAPIKey(
                "환경변수 LAW_OC 가 필요합니다 (레포 Secrets 또는 .env, 커밋 금지)."
            )
        self.pause = pause
        if session is None:
            import requests

            session = requests.Session()
        self.s = session

    def get(self, service: str, **params) -> dict:
        params = {**params, "OC": self.oc, "type": "JSON"}
        last = ""
        for i in range(5):
            try:
                r = self.s.get(f"{BASE}/{service}", params=params, timeout=30)
                text = r.text
                if "사용자 정보 검증에 실패" in text:
                    raise LawAPIError(
                        "법제처 인증 실패: OC 신청·승인 상태와 등록한 서버 IP·도메인을 확인하세요."
                    )
                time.sleep(self.pause)
                return r.json()
            except LawAPIError:
                raise
            except Exception as e:  # 연결 끊김·JSON 아님 → 잠깐 쉬고 다시
                last = type(e).__name__
                time.sleep(1.5 * (i + 1))
        raise LawAPIError(f"법제처 API 호출 실패({service}, {params.get('target')}): {last}")

    def search(
        self, target: str, root: str, key: str, max_pages: int = 10, **params
    ) -> Iterator[dict]:
        page = 1
        while page <= max_pages:
            d = self.get("lawSearch.do", target=target, display=100, page=page, **params).get(
                root, {}
            )
            rows = _as_list(d.get(key))
            yield from rows
            total = int(d.get("totalCnt") or 0)
            if page * 100 >= total or not rows:
                break
            page += 1


# ─── 1. 근거 법률의 연혁 (법률·시행령·시행규칙) ─────────────────────────────
def law_versions(c: LawClient, law: str) -> list[dict]:
    out = []
    for r in c.search("eflaw", "LawSearch", "law", query=law):
        name = r.get("법령명한글", "")
        if name != law and not name.startswith(law + " 시행"):
            continue
        out.append(
            {
                "group": "법령",
                "kind": r.get("법령구분명", ""),
                "name": name,
                "seed": law,
                "relation": "연혁",
                "change": r.get("제개정구분명", ""),
                "announced": _d(r.get("공포일자")),
                "effective": _d(r.get("시행일자")),
                "status": r.get("현행연혁코드", ""),
                "ministry": r.get("소관부처명", ""),
                "law_id": r.get("법령ID", ""),
                "url": public_url("법령", name),
            }
        )
    return out


# ─── 2. 체계도: 하위 행정규칙·자치법규 ───────────────────────────────────────
def _walk(node, path: tuple[str, ...]) -> Iterator[tuple[tuple[str, ...], dict]]:
    if isinstance(node, dict):
        if "기본정보" in node and isinstance(node["기본정보"], dict):
            yield path, node["기본정보"]
        for k, v in node.items():
            if k != "기본정보":
                yield from _walk(v, (*path, k))
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v, path)


def flatten_hierarchy(doc: dict, seed: str) -> list[dict]:
    """법령 체계도 응답(JSON)에서 행정규칙·자치법규를 평평한 표로 만든다. 법령 자신과 시행령·규칙은 연혁에서 받는다."""
    body = doc.get("법령체계도", {}).get("상하위법", {})
    out = []
    for path, info in _walk(body, ()):
        if "행정규칙" in path:
            group, name = "행정규칙", info.get("행정규칙명", "")
            announced = info.get("발령일자")
        elif "자치법규" in path:
            group, name = "자치법규", info.get("자치법규명", "")
            announced = info.get("공포일자")
        else:
            continue
        change = info.get("제개정구분")
        out.append(
            {
                "group": group,
                "kind": path[-1],
                "name": name,
                "seed": seed,
                "relation": "체계도",
                "change": change.get("content", "") if isinstance(change, dict) else (change or ""),
                "announced": _d(announced),
                "effective": _d(info.get("시행일자")),
                "status": "현행",
                "ministry": info.get("소관부처명", "") or info.get("지자체기관명", ""),
                "law_id": info.get("행정규칙ID") or info.get("자치법규ID") or "",
                "url": public_url(group, name),
            }
        )
    return out


def hierarchy(c: LawClient, law: str) -> list[dict]:
    mst = next(
        (
            r["법령일련번호"]
            for r in c.search("lsStmd", "LsStmdSearch", "law", max_pages=1, query=law)
            if r.get("법령명") == law
        ),
        None,
    )
    if not mst:
        return []
    return flatten_hierarchy(c.get("lawService.do", target="lsStmd", MST=mst), law)


# ─── 3. 행정규칙 이력 (지정·해제 공고 등) ─────────────────────────────────────
def admin_rule_row(r: dict, seed: str, relation: str = "이력") -> dict:
    name = r.get("행정규칙명", "")
    return {
        "group": "행정규칙",
        "kind": r.get("행정규칙종류", ""),
        "name": name,
        "seed": seed,
        "relation": relation,
        "change": r.get("제개정구분명", ""),
        "announced": _d(r.get("발령일자")),
        "effective": _d(r.get("시행일자")),
        "status": r.get("현행연혁구분", ""),
        "ministry": r.get("소관부처명", ""),
        "law_id": r.get("행정규칙ID", ""),
        "url": public_url("행정규칙", name),
    }


def admin_rule_versions(c: LawClient, query: str) -> list[dict]:
    return [
        admin_rule_row(r, query)
        for r in c.search("admrul", "AdmRulSearch", "admrul", query=query, nw=2)
        if r.get("행정규칙명", "").startswith(query)
    ]


# ─── 주제 단위로 모으기 ─────────────────────────────────────────────────────
def collect_topic(c: LawClient, laws: list[str], admin_rules: list[str]) -> pd.DataFrame:
    rows: list[dict] = []
    for law in laws:
        rows += law_versions(c, law)
        rows += hierarchy(c, law)
    for q in admin_rules:
        rows += admin_rule_versions(c, q)
    return tidy(pd.DataFrame(rows, columns=COLUMNS))


def tidy(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=COLUMNS)
    # 같은 규칙이 체계도와 이력 양쪽에서 오면, 정보가 더 많은 이력·연혁 쪽을 남긴다
    order = {"이력": 0, "변경": 0, "연혁": 1, "체계도": 2}
    df = df.assign(_o=df["relation"].map(order).fillna(3)).sort_values("_o")
    df = df.drop_duplicates(["group", "name", "announced", "effective", "change"]).drop(
        columns="_o"
    )
    return df.sort_values(
        ["announced", "group", "name"], ascending=[False, True, True]
    ).reset_index(drop=True)


# ─── 4. 변경 감지: 최근 기간에 바뀐 것 ────────────────────────────────────────
def changes_between(
    c: LawClient, known_laws: set[str], admin_rules: list[str], start: date, end: date
) -> pd.DataFrame:
    """start~end 사이 공포된 법령(이름이 known_laws 에 있는 것)과 발령된 행정규칙(검색어로 시작하는 것)."""
    span = f"{start:%Y%m%d}~{end:%Y%m%d}"
    rows = []
    for r in c.search("law", "LawSearch", "law", ancYd=span):
        name = r.get("법령명한글", "")
        if name in known_laws:
            rows.append(
                {
                    **{k: "" for k in COLUMNS},
                    "group": "법령",
                    "kind": r.get("법령구분명", ""),
                    "name": name,
                    "relation": "변경",
                    "change": r.get("제개정구분명", ""),
                    "announced": _d(r.get("공포일자")),
                    "effective": _d(r.get("시행일자")),
                    "status": r.get("현행연혁코드", ""),
                    "ministry": r.get("소관부처명", ""),
                    "law_id": r.get("법령ID", ""),
                    "url": public_url("법령", name),
                }
            )
    for q in admin_rules:
        for r in c.search("admrul", "AdmRulSearch", "admrul", query=q, nw=2, prmlYd=span):
            if r.get("행정규칙명", "").startswith(q):
                rows.append({**admin_rule_row(r, q, "변경")})
    return tidy(pd.DataFrame(rows, columns=COLUMNS))
