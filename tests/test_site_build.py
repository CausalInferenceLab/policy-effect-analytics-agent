"""정적 대시보드가 모든 주제 페이지를 만들고, 로컬 경로·개인정보를 담지 않는지."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_site_builds(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("site_build", ROOT / "site" / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "OUT", tmp_path / "_site")
    mod.main()
    out = tmp_path / "_site"
    topics = mod.load_topics()
    for name in ("index.html", "architecture.html", "data.html", "issues.html"):
        assert (out / name).exists(), name
    for t in topics:
        page = (out / "topics" / f"{t.id}.html").read_text(encoding="utf-8")
        assert t.name in page
    housing = (out / "topics" / "housing-regulation.html").read_text(encoding="utf-8")
    assert "시뮬레이션 데이터 결과" in housing  # 합성 결과 표시
    for f in out.rglob("*.html"):
        text = f.read_text(encoding="utf-8")
        assert "/home/" not in text and "/tmp/" not in text


def _load_build():
    spec = importlib.util.spec_from_file_location("site_build2", ROOT / "site" / "build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_home_has_chat_and_catalog(tmp_path, monkeypatch):
    """대화창이 동작하는 데 필요한 것: ask.js 복사, 카탈로그 JSON, 요소 id."""
    import json
    import re

    mod = _load_build()
    monkeypatch.setattr(mod, "OUT", tmp_path / "_site")
    mod.main()
    out = tmp_path / "_site"
    assert (out / "ask.js").exists()
    home = (out / "index.html").read_text(encoding="utf-8")
    for id_ in ("chat-log", "chat-form", "q", "ai-panel", "ai-provider", "ai-key", "mode", "cards"):
        assert f'id="{id_}"' in home, id_
    raw = re.search(
        r'<script type="application/json" id="catalog">(.*?)</script>', home, re.S
    ).group(1)
    cat = json.loads(raw.replace("<\\/", "</"))
    assert {"repo", "topics", "issues", "datasets"} <= cat.keys()
    assert "요즘 궁금해하는 주제" in home
    assert "공식 평가가 아닙니다" in home
    # 개별 참여로 바뀌었으므로 조 단위 안내가 남아 있으면 안 됨
    for f in out.rglob("*.html"):
        text = f.read_text(encoding="utf-8")
        assert "조별" not in text and "조원" not in text, f.name


def test_ranking_questions_first_then_recency():
    mod = _load_build()
    topics, issues = mod.load_topics(), mod.load_issues()
    rows, has_q, has_s, basis = mod.rank_topics(topics, issues, {}, today="2026-09-27")
    assert not has_q and not has_s and "최근 시행·발표 순" in basis
    dates = [r[3] for r in rows]
    assert dates == sorted(dates, reverse=True)
    last = topics[-1].id
    trends = {
        "sources": ["site_questions"],
        "updated": "2026-09-27",
        "topics": {last: {"questions": 3}},
    }
    rows, has_q, _, basis = mod.rank_topics(topics, issues, trends, today="2026-09-27")
    assert has_q and rows[0][0].id == last and "사이트 질문" in basis


def test_rank_questions_match_a_topic():
    """순위 항목을 누르면 주제 질문이 대화창으로 들어간다 → 그 질문이 같은 주제로 연결돼야 한다(ask.js 규칙과 같게)."""
    mod = _load_build()
    policies = mod.load_catalog()

    def norm(s):
        return "".join(s.split()).lower()

    for t in mod.load_topics():
        kws = t.keywords + [
            k for pid in t.policies for p in policies if p.id == pid for k in p.keywords
        ]
        assert any(norm(k) in norm(t.question) for k in kws), t.id


def test_issue_form_fields_match_chat():
    """ask.js 가 채우는 칸 이름과 이슈 양식의 id가 같아야 대화가 이슈에 들어간다."""
    import yaml

    form = yaml.safe_load(
        (ROOT / ".github/ISSUE_TEMPLATE/site-question.yml").read_text(encoding="utf-8")
    )
    ids = {b.get("id") for b in form["body"]}
    js = (ROOT / "site" / "ask.js").read_text(encoding="utf-8")
    for field in ("question", "topic", "conversation", "proposal"):
        assert field in ids, field
        assert f"{field}:" in js or f"fields.{field}" in js, field
    assert "from-site" in form["labels"]
    assert "site-question.yml" in js
