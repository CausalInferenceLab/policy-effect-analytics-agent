"""결과 수집 전 확정한 수동 정책 판정을 재현한다. 자동 법률 해석기가 아니다.

policy-review.md의 근거·제외 판단을 코드로 고정한다. 원문을 내려받아 검토 당시
내용과 대조한 뒤 로컬 검토표를 생성한다. 원문 변경 시 재검토 없이 진행하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

import requests
import yaml


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def normalized_text(content: bytes) -> str:
    parser = _VisibleText()
    parser.feed(content.decode("utf-8"))
    return " ".join(" ".join(parser.parts).split())


def verify_source(content: bytes, source: dict) -> None:
    if source.get("sha256"):
        valid = hashlib.sha256(content).hexdigest() == source["sha256"]
    else:
        text = normalized_text(content)
        if source.get("text_sha256"):
            valid = hashlib.sha256(text.encode()).hexdigest() == source["text_sha256"]
        else:
            valid = all(term in text for term in source["required_text"])
    if not valid:
        raise ValueError(f"정책 원문 변경/불일치: {source['id']}. policy-review.md 재검토 필요")


def collect_policy(
    case_dir: Path, districts: tuple[str, ...], *, offline: bool = False
) -> list[dict]:
    sources = json.loads((case_dir / "policy-sources.json").read_text())
    target = case_dir / "data" / "raw" / "policy_sources"
    target.mkdir(parents=True, exist_ok=True)
    for source in sources:
        path = target / source["filename"]
        if not path.exists():
            if offline:
                raise ValueError(f"오프라인 재현용 정책 원문 없음: {source['id']}")
            try:
                response = requests.get(source["download_url"], timeout=(10, 60))
                response.raise_for_status()
            except requests.RequestException as exc:
                raise ValueError(f"정책 근거 다운로드 실패: {source['id']}") from exc
            verify_source(response.content, source)
            path.write_bytes(response.content)
            path.with_suffix(".source.json").write_text(
                json.dumps(
                    {**source, "retrieved_at": datetime.now(UTC).isoformat()},
                    ensure_ascii=False,
                    indent=2,
                )
            )
        verify_source(path.read_bytes(), source)

    by_id = {source["id"]: source for source in sources}
    # 아래는 원자료 테이블이 아닌 사전 등록된 포함 판정의 실행 규칙이다.
    # 정책 해석·금액은 연구자가 공식 원문과 PDF를 대조했다(policy-review.md).
    accepted = {
        "중구": (200_000, 1_000_000, ["junggu-old", "junggu", "junggu-history"]),
        "강남구": (
            300_000,
            2_000_000,
            ["gangnam-old", "gangnam-2022", "gangnam-2023", "gangnam", "gangnam-history"],
        ),
        "용산구": (0, 0, ["yongsan-2022", "yongsan", "yongsan-history"]),
        "성동구": (0, 0, ["seongdong"]),
        "송파구": (0, 0, ["songpa"]),
    }
    reasons = {
        "광진구": "첫째아 증액 적용일은 2024-01-01. 2023년 증액 설계와 다름(조례 부칙).",
        "동작구": "2023년 시행 조례가 2022-07-01 출생아부터 소급 적용. 연중 변경 제외.",
        "금천구": "사례집과 조례의 첫째·둘째 규정 잔존 및 소급 규정을 완전히 해소하지 못함.",
        "성북구": "2022 사례집 첫째 금액과 2023~2024 미등재 사이 종료 적용일 확인 부족.",
        "서대문구": "2022 사례집은 2021년 출생아 지급. 2022~2024 전체 이력 추가 검증 부족.",
        "구로구": "2022 사례집은 2021년 출생아 지급. 2023~2024 전체 이력 추가 검증 부족.",
        "마포구": "2022 의회에서 2021년 출생아 잔여 지급 확인. 이후 전체 이력 검증 부족.",
    }
    review = []
    for district in districts:
        if district not in accepted:
            review.append(
                {
                    "district": district,
                    "status": "excluded",
                    "reason": reasons.get(
                        district,
                        "2022~2024 사례집을 조사했으나 개별 종료 적용일·전체 기간 조건 검증 부족. "
                        "표 미등재를 0원으로 대체하지 않음.",
                    ),
                }
            )
            continue
        before, after, ids = accepted[district]
        ids += ["mohw-2022", "mohw-2023", "mohw-2024"]
        review.append(
            {
                "district": district,
                "status": "verified",
                "history_start": "2022-01-01",
                "history_end": "2024-12-31",
                "first_child_won": {"2022": before, "2023": after, "2024": after},
                "conditions_unchanged": True,
                "change_date": "2023-01-01" if before < after else None,
                "evidence_note": (
                    "policy-review.md의 수동 대조 판정. 첫째아 자체 일시금에 한정하며 "
                    "첫째 미지원 구는 첫째 자격 없음이 계속됨을 뜻한다. "
                    "다자녀·산후조리 등 다른 정책의 불변을 뜻하지 않는다."
                ),
                "sources": [
                    {
                        "url": by_id[key]["url"],
                        "license": by_id[key]["license"],
                        "checked_on": "2026-10-19",
                    }
                    for key in ids
                ],
            }
        )
    path = case_dir / "data" / "raw" / "policy_review.yaml"
    path.write_text(yaml.safe_dump(review, allow_unicode=True, sort_keys=False))
    return review
