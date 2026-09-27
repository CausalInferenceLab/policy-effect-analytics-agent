"""순위 재료 수집(scripts/refresh_trends.py)의 계산 부분 — 네트워크 없이."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "refresh_trends", ROOT / "scripts" / "refresh_trends.py"
)
rt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rt)

IDS = {"housing-regulation", "local-currency"}


def test_topic_of_reads_issue_form_field():
    body = "### 궁금한 점\n\n집값?\n\n### 관련 주제\n\n부동산 거래 규제 (housing-regulation)\n\n### 대화 내용\n\n..."
    assert rt.topic_of(body, IDS) == "housing-regulation"
    assert rt.topic_of("### 관련 주제\n\n새 주제\n", IDS) is None
    assert rt.topic_of("### 관련 주제\n\nlocal-currency\n", IDS) == "local-currency"
    assert rt.topic_of("본문 없음", IDS) is None


def test_count_site_questions_skips_prs():
    issues = [
        {"body": "### 관련 주제\n\n지역화폐 (local-currency)"},
        {"body": "### 관련 주제\n\n지역화폐 (local-currency)"},
        {"body": "### 관련 주제\n\n새 주제"},
        {"body": "### 관련 주제\n\n지역화폐 (local-currency)", "pull_request": {}},
    ]
    counts, new = rt.count_site_questions(issues, IDS)
    assert counts["local-currency"] == 2 and new == 1


def test_combine_batches_rescales_by_anchor():
    # 두 번째 요청은 anchor 가 50 → 모든 값이 2배로 맞춰진 뒤 최대=100
    b1 = {"a": 100.0, "x": 50.0}
    b2 = {"a": 50.0, "y": 100.0}
    out = rt.combine_batches([b1, b2], "a")
    assert out == {"a": 50.0, "x": 25.0, "y": 100.0}
