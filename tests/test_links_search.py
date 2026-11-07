"""케이스 ↔ 데이터 자동 연결, 자동 계보, 통합 검색 목록, 검색어 지표."""

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "site"))

from core.discovery.lineage import load_lineages, validate  # noqa: E402
from core.discovery.links import (  # noqa: E402
    all_lineages,
    auto_lineage,
    case_sources,
    dataset_users,
    is_auto,
    match_source,
)
from core.discovery.ontology import load_datasets  # noqa: E402

DS = load_datasets()


def test_match_by_url_and_by_id_in_name():
    assert (
        match_source({"url": "https://www.data.go.kr/data/15126468/openapi.do"}, DS) == "15126468"
    )
    # 주소 없이 이름에 id 가 적혀 있어도 맞춘다 (긴 id 우선)
    assert (
        match_source({"name": "시군구별 이동자수 (KOSIS DT_1B26001_A01)"}, DS) == "DT_1B26001_A01"
    )
    assert match_source({"name": "없는 데이터", "url": "https://example.org/x"}, DS) is None


def test_case_sources_skip_synthetic_and_policy_evidence(tmp_path):
    case = tmp_path / "x"
    case.mkdir()
    (case / "plan.yaml").write_text(
        yaml.safe_dump(
            {
                "data_sources": [
                    {"name": "합성", "provider": "-", "license": "synthetic"},
                    {"name": "강남구 2023년 지원금 확대 발표", "url": "https://gangnam.go.kr/a"},
                    {"name": "실거래가", "url": "https://www.data.go.kr/data/15126468/openapi.do"},
                    {
                        "name": "실거래가 다시",
                        "url": "https://data.go.kr/data/15126468/openapi.do/",
                    },
                ]
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    src = case_sources(case, DS)
    assert [s["dataset"] for s in src] == ["15126468"]


def test_every_registered_case_with_data_has_a_valid_lineage():
    reg = yaml.safe_load((ROOT / "catalog" / "projects.yaml").read_text(encoding="utf-8"))
    lins = all_lineages()
    covered = {c for lin in lins for s in lin.steps for c in s.used_by}
    for p in reg["projects"]:
        case = ROOT / "cases" / p["case"]
        plan = yaml.safe_load((case / "plan.yaml").read_text(encoding="utf-8")) or {}
        if (plan.get("treatment") or {}).get("definition") and case_sources(case, DS):
            assert p["case"] in covered, p["case"]
    for lin in lins:
        errors, _ = validate(lin)
        assert not errors, (lin.id, errors)


def test_hand_lineage_wins_over_auto():
    hand = load_lineages()
    hand_cases = {c for lin in hand for s in lin.steps for c in s.used_by}
    autos = [lin for lin in all_lineages() if is_auto(lin)]
    assert not hand_cases & {lin.id[5:] for lin in autos}


def test_auto_lineage_does_not_invent_dates():
    lin = auto_lineage(ROOT / "cases" / "yesolee-green-traffic", DS, "air-quality", "yesolee")
    assert lin is not None and lin.id == "auto-yesolee-green-traffic"
    assert all(s.date is None for s in lin.steps)
    assert lin.steps[-1].used_by == ["yesolee-green-traffic"]


def test_most_case_data_is_in_catalog():
    users = dataset_users(DS)
    assert sum(len(v) for v in users.values()) >= 25


def test_search_index_covers_every_kind():
    import answers as ans
    import projects as proj
    import search

    from core.discovery.catalog import load_topics
    from core.discovery.ontology import load_issues

    a = ans.load_answers()
    items = search.index(load_topics(), load_issues(), DS, a, proj.load_projects(), all_lineages())
    kinds = {i["t"] for i in items}
    assert {"result", "issue", "topic", "dataset", "lineage", "law"} <= kinds
    assert sum(i["t"] == "result" for i in items) == len(a)
    assert all(i["url"] and i["title"] for i in items)


def test_search_terms_split_found_and_zero():
    from impact import search_terms

    assert search_terms(None)["on"] is False
    sq = search_terms({"events": {"q-토허제": 3, "q0-반려동물": 2, "q-반려동물": 1, "ev-ask": 9}})
    assert sq["total"] == 6
    assert sq["top"] == [("반려동물", 3), ("토허제", 3)]  # 횟수 같으면 가나다순
    assert sq["zero"] == [("반려동물", 2)]


def test_query_tracking_strips_personal_patterns():
    js = (ROOT / "site" / "track.js").read_text(encoding="utf-8")
    assert "window.trackSearch" in js and "\\S+@\\S+" in js and "slice(0, 30)" in js
    assert "doNotTrack" in js
