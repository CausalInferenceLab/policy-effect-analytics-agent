"""법령 온톨로지 수집기 — 네트워크 없이 응답 모양만 재현해 확인한다."""

from datetime import date

import pytest

from core.adapters.base import MissingAPIKey
from core.adapters.legal import (
    LawClient,
    admin_rule_versions,
    changes_between,
    collect_topic,
    flatten_hierarchy,
    law_versions,
)

SEED = "부동산 거래신고 등에 관한 법률"

EFLAW = [
    {
        "법령명한글": SEED,
        "법령구분명": "법률",
        "현행연혁코드": "현행",
        "제개정구분명": "타법개정",
        "공포일자": "20240206",
        "시행일자": "20240517",
        "소관부처명": "국토교통부",
        "법령ID": "012480",
        "법령상세링크": "/DRF/lawService.do?OC=secret&target=law&MST=1",
    },
    {
        "법령명한글": SEED + " 시행령",
        "법령구분명": "대통령령",
        "현행연혁코드": "연혁",
        "제개정구분명": "일부개정",
        "공포일자": "20250429",
        "시행일자": "20250429",
        "소관부처명": "국토교통부",
        "법령ID": "012481",
    },
    {
        "법령명한글": "공인중개사법",
        "법령구분명": "법률",
        "현행연혁코드": "현행",
        "제개정구분명": "일부개정",
        "공포일자": "20260227",
        "시행일자": "20260828",
        "소관부처명": "국토교통부",
        "법령ID": "001654",
    },
]
STMD = {
    "법령체계도": {
        "상하위법": {
            "법률": {
                "자치법규": {
                    "조례": [
                        {
                            "기본정보": {
                                "자치법규ID": "1",
                                "자치법규명": "구로구 주택 임대차 계약의 신고 조례",
                                "제개정구분": {"content": "제정"},
                                "공포일자": "20210429",
                                "시행일자": "20210601",
                                "본문상세링크": "/DRF/lawService.do?OC=test",
                            }
                        }
                    ]
                },
                "행정규칙": {
                    "공고": [
                        {
                            "기본정보": {
                                "행정규칙ID": "85053",
                                "행정규칙명": "투기과열지구 지정",
                                "제개정구분": {"content": "일부개정"},
                                "발령일자": "20260701",
                                "시행일자": "20260701",
                            }
                        }
                    ]
                },
                "시행령": {"기본정보": {"법령명": SEED + " 시행령", "시행일자": "20260529"}},
            }
        }
    }
}
ADMRUL = [
    {
        "행정규칙명": "투기과열지구 지정",
        "행정규칙종류": "공고",
        "제개정구분명": "일부개정",
        "발령일자": "20251016",
        "시행일자": "20251016",
        "현행연혁구분": "연혁",
        "소관부처명": "국토교통부",
        "행정규칙ID": "85053",
    },
    {
        "행정규칙명": "투기과열지구 지정 해제",
        "행정규칙종류": "공고",
        "제개정구분명": "일부개정",
        "발령일자": "20230105",
        "시행일자": "20230105",
        "현행연혁구분": "연혁",
        "소관부처명": "국토교통부",
        "행정규칙ID": "85053",
    },
    {"행정규칙명": "상호 투기과열지구 무관 고시", "행정규칙종류": "고시", "발령일자": "20200101"},
]


class Fake:
    """LawClient 대신: target 별로 정해 둔 행을 돌려준다."""

    def search(self, target, root, key, max_pages=10, **params):
        if target == "eflaw":
            return iter(EFLAW)
        if target == "lsStmd":
            return iter([{"법령명": SEED, "법령일련번호": "259641"}])
        if target == "admrul":
            return iter(ADMRUL)
        if target == "law":
            return iter(EFLAW)
        return iter([])

    def get(self, service, **params):
        return STMD


def test_law_versions_keeps_seed_and_its_decrees_only():
    rows = law_versions(Fake(), SEED)
    assert [r["name"] for r in rows] == [SEED, SEED + " 시행령"]
    assert rows[0]["announced"] == "2024-02-06" and rows[0]["effective"] == "2024-05-17"


def test_hierarchy_flattens_rules_and_ordinances():
    rows = flatten_hierarchy(STMD, SEED)
    kinds = {(r["group"], r["kind"], r["name"]) for r in rows}
    assert ("자치법규", "조례", "구로구 주택 임대차 계약의 신고 조례") in kinds
    assert ("행정규칙", "공고", "투기과열지구 지정") in kinds
    assert all(r["group"] != "법령" for r in rows)  # 시행령은 연혁에서 받는다


def test_admin_rule_history_filters_by_prefix():
    rows = admin_rule_versions(Fake(), "투기과열지구")
    assert [r["name"] for r in rows] == ["투기과열지구 지정", "투기과열지구 지정 해제"]


def test_collect_topic_has_no_secret_links_and_prefers_history_rows():
    df = collect_topic(Fake(), [SEED], ["투기과열지구"])
    text = df.to_csv(index=False)
    assert "OC=" not in text and "secret" not in text
    assert all(u.startswith("https://www.law.go.kr/") for u in df["url"])
    assert list(df["announced"]) == sorted(df["announced"], reverse=True)


def test_changes_between_filters_known_names():
    df = changes_between(Fake(), {SEED}, ["투기과열지구"], date(2020, 1, 1), date(2026, 9, 1))
    assert set(df["name"]) == {SEED, "투기과열지구 지정", "투기과열지구 지정 해제"}


def test_client_needs_oc(monkeypatch):
    monkeypatch.delenv("LAW_OC", raising=False)
    with pytest.raises(MissingAPIKey):
        LawClient()


def test_snapshots_have_no_oc():
    from pathlib import Path

    for f in (Path(__file__).resolve().parents[2] / "catalog" / "snapshots").glob("*"):
        assert "OC=" not in f.read_text(encoding="utf-8"), f.name
