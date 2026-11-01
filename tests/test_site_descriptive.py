"""Synthetic site contract fixtures; these are not research data or policy estimates."""

import copy
import csv
import html
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "site"))
import answers  # noqa: E402
import api  # noqa: E402
import projects  # noqa: E402
import quality  # noqa: E402


@pytest.fixture
def case(tmp_path, monkeypatch):
    folder = tmp_path / "cases" / "fixture-descriptive"
    folder.mkdir(parents=True)
    plan = yaml.safe_load((ROOT / "cases/t3-land-permit-2025/plan.yaml").read_text())
    plan.update(
        case_id=folder.name, title="Fixture <사례>", question="관측값은?", synthetic_data=False
    )
    (folder / "plan.yaml").write_text(yaml.safe_dump(plan, allow_unicode=True))
    (folder / "discussion.md").write_text(
        "## 결과를 한 문장으로\n사고 관측값은 바뀌었지만 정책 효과는 판단할 수 없다.\n"
        "\n## 조심할 점\n- 코로나19와 노출량 변화는 분리하지 않았다.\n"
    )
    (folder / "figures").mkdir()
    for i in range(4):
        (folder / "figures" / f"0{i}_observed.png").write_bytes(b"fixture image reference")
    log = {
        "execution_kind": "descriptive_only",
        "causal_estimation": "not_run",
        "verdict": "not_identified",
        "results": [],
        "steps": [],
        "status": "warn",
        "ended_at": "2026-11-01T00:00:00Z",
        "descriptive": {
            "columns": [
                {"key": "year", "label": "연도", "unit": "년"},
                {"key": "count", "label": "관측 사고건수", "unit": "건"},
                {"key": "share", "label": "관측 구성비", "unit": "%"},
            ],
            "rows": [
                {"year": y, "count": 1000 + y - 2019, "share": 10.5} for y in range(2019, 2025)
            ],
            "definitions": {"count": "공개 스냅샷의 사고건수 <관측>", "share": "전체 대비 구성비"},
            "sources": [
                {
                    "name": "공개 자료 <원문>",
                    "url": "https://example.go.kr/stats?a=1&b=2",
                    "provider": "기관",
                    "license": "이용조건 원문 확인",
                    "notes": "스냅샷",
                }
            ],
            "reproduction": {
                "command": "python cases/fixture-descriptive/replay.py --input '<snapshot>'",
                "mode": "local_snapshot_replay",
                "prerequisites": ["동일 원자료 스냅샷을 먼저 확보"],
            },
        },
    }
    (folder / "flow_log.json").write_text(json.dumps(log, ensure_ascii=False))
    for mod in (answers, api, projects):
        monkeypatch.setattr(mod, "CASES", folder.parent)
        monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(quality, "prereg", lambda _: None)
    monkeypatch.setattr(projects, "load_registry", lambda: {})
    monkeypatch.setattr(projects, "load_activity", lambda: {})
    return folder, log


def test_observed_page_preserves_values_and_structure(case):
    _, log = case
    a = answers.load_answers()[0]
    assert a.get("execution_kind") == "descriptive_only"
    assert a.get("causal_estimation") == "not_run"
    assert a.get("descriptive") == log["descriptive"]
    page = answers.page_body(html.escape, a, {}, {})
    for text in (
        "관측 통계 · 정책 효과 미추정",
        "작성자 해석",
        "인용문",
        "관측 사고건수",
        "건",
        "구성비",
        "%",
        "2024",
        "1005",
        "코로나19",
        "이용조건 원문 확인",
        "local_snapshot_replay",
        "동일 원자료 스냅샷을 먼저 확보",
        "전체 리포트",
    ):
        assert text in page, text
    for text in (
        "추정 효과",
        "95% 범위",
        "진단용",
        "파이프라인 자동 요약",
        "make flow",
        "직접 받아 같은 결과",
    ):
        assert text not in page, text
    assert page.count("<img src=") == 4
    assert "&lt;원문&gt;" in page and "&lt;snapshot&gt;" in page
    assert "관측 통계" in answers.card(html.escape, a, {})
    p = projects.load_projects()[0]
    assert "관측 통계" in projects.project_card(html.escape, p, {})
    assert "파이프라인 자동 판정" not in projects.project_card(html.escape, p, {})


def test_observed_api_csv_are_separate_from_effects(case, tmp_path):
    _, log = case
    rows = api.case_results(tmp_path / "out")
    row = rows[0]
    assert row.get("execution_kind") == "descriptive_only"
    assert row.get("causal_estimation") == "not_run"
    assert row.get("descriptive") == log["descriptive"]
    assert row["outcomes"] == [] and answers.csv_rows(rows) == []
    answers.write_csv(tmp_path / "out", rows)
    effect = tmp_path / "out/api/results.csv"
    assert list(csv.DictReader(effect.open(encoding="utf-8-sig"))) == []
    observed = tmp_path / "out/answers/fixture-descriptive-descriptive.csv"
    with observed.open(encoding="utf-8-sig") as f:
        assert list(csv.DictReader(f)) == [
            {k: str(v) for k, v in r.items()} for r in log["descriptive"]["rows"]
        ]
    assert not (tmp_path / "out/answers/fixture-descriptive.csv").exists()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda x: x.update(results=[{"outcome": "count", "estimate": 0}]),
        lambda x: x.update(causal_estimation="done"),
        lambda x: x.pop("execution_kind"),
        lambda x: x.pop("causal_estimation"),
        lambda x: x.update(verdict="identified"),
        lambda x: x.update(steps=[{"step": "estimate", "status": "ok"}]),
        lambda x: x.update(steps=[{"step": "estimate", "status": []}]),
        lambda x: x["descriptive"]["rows"][0].update(count=True),
        lambda x: x["descriptive"]["rows"][0].update(count=float("nan")),
        lambda x: x["descriptive"]["rows"][0].update(count=float("inf")),
        lambda x: x["descriptive"]["rows"][0].update(year=True),
        lambda x: x["descriptive"]["rows"][0].update(year=10**400),
        lambda x: x["descriptive"]["rows"][1].update(year=2019),
        lambda x: x["descriptive"]["rows"][0].update(ci_low=0),
        lambda x: x["descriptive"].update(estimate=0),
        lambda x: x["descriptive"]["columns"][1].update(p_value=0.1),
        lambda x: x["descriptive"]["columns"][1].update(key="estimate"),
        lambda x: x["descriptive"]["columns"][1].update(unit=""),
        lambda x: x["descriptive"]["rows"][0].pop("count"),
    ],
)
def test_descriptive_contradictions_never_fall_back_to_effects(case, tmp_path, capsys, mutate):
    folder, original = case
    log = copy.deepcopy(original)
    mutate(log)
    (folder / "flow_log.json").write_text(json.dumps(log))
    assert answers.load_answers() == []
    assert api.case_results(tmp_path / "out") == []
    p = projects.load_projects()[0]
    assert p["verdict"] is None and not p["stages"][2]
    assert p.get("result_error")
    assert "기술통계" in capsys.readouterr().out


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "//evil.example/a",
        "https://[broken",
        'https://example.go.kr/" onclick="evil',
    ],
)
def test_descriptive_source_urls_cannot_execute(case, url):
    folder, log = case
    log["descriptive"]["sources"][0]["url"] = url
    (folder / "flow_log.json").write_text(json.dumps(log))
    loaded = answers.load_answers()
    if loaded:
        page = answers.page_body(html.escape, loaded[0], {}, {})
        assert f'href="{url}"' not in page
        assert 'href="javascript:' not in page and 'href="data:' not in page
        assert "<script>alert(1)</script>" not in page


def test_causal_fixture_keeps_effect_page_and_api(case, tmp_path):
    folder, _ = case
    log = json.loads((ROOT / "cases/t3-land-permit-2025/flow_log.json").read_text())
    (folder / "flow_log.json").write_text(json.dumps(log))
    a = answers.load_answers()[0]
    page = answers.page_body(html.escape, a, {}, {})
    assert "추정 효과" in page and "95% 범위" in page
    assert "make flow CASE=cases/fixture-descriptive" in page
    row = api.case_results(tmp_path / "out")[0]
    assert len(row["outcomes"]) == len(log["results"])
    assert row["outcomes"][0]["estimate"] == log["results"][0]["estimate"]
