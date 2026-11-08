"""데이터 연동(core.data)과 지금 이슈의 출처·자동 후보, 검색 탭."""

import sys
from pathlib import Path

import pytest

from core.data import connector, fetch, main
from core.discovery.links import dataset_users
from core.discovery.ontology import load_datasets, load_issues

ROOT = Path(__file__).resolve().parents[1]
DS = {d.id: d for d in load_datasets()}
USERS = dataset_users(list(DS.values()))


def test_every_dataset_has_a_connector():
    kinds = {connector(d, USERS)["kind"] for d in DS.values()}
    assert kinds <= {"adapter", "case", "api_key", "file", "manual"}
    for d in DS.values():
        c = connector(d, USERS)
        assert c["label"] and c["code"] and c["steps"]


def test_builtin_adapters_are_wired():
    assert (
        connector(DS["DT_1B040A3"])["kind"] == "adapter"
        and 'tblId="DT_1B040A3"' in connector(DS["DT_1B040A3"])["python"]
    )
    assert connector(DS["15126468"])["env"] == "DATA_GO_KR_API_KEY"
    assert connector(DS["OA-12914"])["auto"] is True


def test_case_code_is_offered_when_a_participant_already_fetched_it():
    c = connector(DS["airkorea-final"], USERS)
    assert c["kind"] == "case" and "yesolee-green-traffic" in c["code"]


def test_fetch_refuses_without_adapter():
    with pytest.raises(ValueError):
        fetch(DS["15134761"])


def test_cli_issue_lists_all_issue_datasets(capsys):
    iss = load_issues()[0]
    assert main(["issue", iss.id]) == 0
    out = capsys.readouterr().out
    assert iss.source in out and all(x in out for x in iss.datasets if x in DS)


def test_issue_sources_and_candidates():
    sys.path.insert(0, str(ROOT / "site"))
    import build

    from core.discovery.catalog import load_topics

    topics, issues = load_topics(), load_issues()
    c = build.issue_candidates(topics, issues, today="2026-11-08")
    assert c and all(x["kind"] in {"법령 개정", "뉴스", "사이트 질문"} for x in c)
    assert all(x["date"] <= "2026-11-08" for x in c)
    html = build.issue_sources(issues, topics)
    assert (
        "지금 이슈는 어디서 오나" in html
        and "이슈로 제안" in html
        and "catalog/issues.yaml" in html
    )


def test_search_tabs_behave_the_same():
    js = (ROOT / "site" / "search.js").read_text(encoding="utf-8")
    assert "b.disabled" not in js  # 0개인 탭도 눌러서 빈 안내를 본다
    assert "function tabView" in js and "TAB_HINT" in js
    assert 'render("")' in js  # 검색어 없이도 탭별 전체 목록
