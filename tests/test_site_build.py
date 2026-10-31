"""정적 대시보드가 모든 주제 페이지를 만들고, 로컬 경로·개인정보를 담지 않는지."""

import importlib.util
import json
import re
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
    assert 'id="topics"' in home and '<script src="ask.js"></script>' in home
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


def test_tracks_api_and_apps(tmp_path, monkeypatch):
    """트랙 A·C: 공개 API, 데이터 계보 페이지, 서비스 호스팅."""
    import json

    mod = _load_build()
    monkeypatch.setattr(mod, "OUT", tmp_path / "_site")
    mod.main()
    out = tmp_path / "_site"
    for name in ("index", "topics", "issues", "datasets", "lineage", "results"):
        assert (out / "api" / f"{name}.json").exists(), name
    for f in (out / "api").rglob("*.json"):  # 브라우저 JSON.parse 처럼 NaN 을 허용하지 않고 읽기
        json.loads(
            f.read_text(encoding="utf-8"),
            parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)),
        )
    index = json.loads((out / "api" / "index.json").read_text(encoding="utf-8"))
    assert "공식 평가" in index["terms"] and "results.json" in index["endpoints"]
    results = json.loads((out / "api" / "results.json").read_text(encoding="utf-8"))
    t3 = next(r for r in results if r["case"] == "t3-land-permit-2025")
    assert t3["topic"] == "housing-regulation" and t3["synthetic"] is True and t3["outcomes"]
    for f in t3["figures"]:
        assert (out / f).exists()
    assert (out / "lineage.html").exists() and (out / "apps.html").exists()
    assert (out / "apps" / "_template" / "index.html").exists()
    assert not (out / "apps" / "_template" / "app.yaml").exists()
    nav = (out / "index.html").read_text(encoding="utf-8")
    assert "데이터 계보" in nav and "서비스" in nav
    assert "데이터 온톨로지" in (out / "projects.html").read_text(encoding="utf-8")


def test_apps_have_meta_and_no_secrets():
    import re

    for d in (ROOT / "apps").iterdir():
        if not d.is_dir():
            continue
        assert (d / "app.yaml").exists(), f"{d.name}: app.yaml 필요"
        for f in d.rglob("*"):
            if f.is_file() and f.suffix in {".js", ".html", ".json", ".yaml"}:
                text = f.read_text(encoding="utf-8")
                assert not re.search(r"sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}", text), (
                    f"{f}: 비밀값처럼 보임"
                )


def test_projects_page_lists_every_case(tmp_path, monkeypatch):
    """참여자 프로젝트 화면: cases/ 의 모든 케이스가 나오고, 명단(projects.yaml)은 있는 폴더·주제만 가리킨다."""
    import yaml

    mod = _load_build()
    monkeypatch.setattr(mod, "OUT", tmp_path / "_site")
    mod.main()
    out = tmp_path / "_site"
    page = (out / "projects.html").read_text(encoding="utf-8")
    root = Path(__file__).resolve().parents[1]
    reg = yaml.safe_load((root / "catalog" / "projects.yaml").read_text(encoding="utf-8"))
    topics = {
        t["id"]
        for t in yaml.safe_load((root / "catalog" / "topics.yaml").read_text(encoding="utf-8"))[
            "topics"
        ]
    }
    for p in reg["projects"]:
        assert p["track"] in {"A", "B", "C"}, p["case"]
        assert p.get("topic") in topics, p["case"]
    for case in (root / "cases").iterdir():
        if case.is_dir() and not case.name.startswith("_") and (case / "plan.yaml").exists():
            assert f"cases/{case.name}" in page, case.name
    projects = json.loads((out / "api" / "projects.json").read_text(encoding="utf-8"))
    assert all({"case", "owner", "stages", "topic"} <= p.keys() for p in projects)
    assert "projects.html" in (out / "index.html").read_text(encoding="utf-8")


def test_answer_pages_for_users(tmp_path, monkeypatch):
    """분석 결과 화면: 결과가 있는 케이스마다 답 페이지가 있고, 판단 불가 결과는 숫자를 진단용으로 표시한다."""
    mod = _load_build()
    monkeypatch.setattr(mod, "OUT", tmp_path / "_site")
    mod.main()
    out = tmp_path / "_site"
    root = Path(__file__).resolve().parents[1]
    results = json.loads((out / "api" / "results.json").read_text(encoding="utf-8"))
    assert results and (out / "results.html").exists()
    for r in results:
        page = (out / r["page"]).read_text(encoding="utf-8")
        assert "이 결과를 쓰려면" in page and "인용문" in page and "직접 돌려 보기" in page
        assert f"make flow CASE=cases/{r['case']}" in page
        assert "이 결과를 얼마나 믿을 수 있나" in page
        assert 'property="og:url"' in page and (out / "answers" / f"{r['case']}.csv").exists()
        if r["verdict"] == "not_identified":
            assert "진단용" in page
    for case in (root / "cases").glob("*/flow_log.json"):
        if not case.parent.name.startswith("_"):
            assert (out / "answers" / f"{case.parent.name}.html").exists(), case.parent.name
    home = (out / "index.html").read_text(encoding="utf-8")
    cat = json.loads(
        re.search(r'<script type="application/json" id="catalog">(.*?)</script>', home, re.S)
        .group(1)
        .replace("<\\/", "</")
    )
    assert cat["results"] and all("page" in x for x in cat["results"])
    # 첫 화면: 흐름 띠·질문 → 이슈 보드(흐름 지도) → 이미 나온 답 → 지금 이슈 → 다음에 할 수 있는 것
    assert home.index('id="ask"') < home.index('id="topics"') < home.index('id="answers"')
    assert 'id="next"' in home and 'class="levels"' in home and "impact.html" in home
    assert 'id="reuse"' in (out / "results.html").read_text(encoding="utf-8")
    # 주제 페이지(이슈 보드)에는 분석 단계가 있고, 결과 CSV는 엑셀용 BOM 을 붙인다
    for t in (out / "topics").glob("*.html"):
        assert "id='s-analysis'" in t.read_text(encoding="utf-8"), t.name
    raw = (out / "api" / "results.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and b"rule_out" in raw.splitlines()[0]


def test_impact_page_and_tracking(tmp_path, monkeypatch):
    """성과 화면: 측정 못 한 칸은 '측정 전', 이벤트 이름은 사이트 버튼과 같고, 통계 코드가 없으면 추적하지 않는다."""
    mod = _load_build()
    monkeypatch.setattr(mod, "OUT", tmp_path / "_site")
    monkeypatch.delenv("GOATCOUNTER_CODE", raising=False)
    mod.main()
    out = tmp_path / "_site"
    page = (out / "impact.html").read_text(encoding="utf-8")
    for sec in ("쓰임", "외부 검증", "결과의 질", "참여"):
        assert f"<h2>{sec}</h2>" in page
    kpi = json.loads((out / "api" / "metrics.json").read_text(encoding="utf-8"))
    assert kpi["quality"]["all"] >= kpi["quality"]["results"] > 0
    assert (out / "track.js").exists() and "data-gc" not in (out / "index.html").read_text(
        encoding="utf-8"
    )
    import sys

    sys.path.insert(0, str(ROOT / "site"))
    import impact

    used = set()
    for f in out.rglob("*.html"):
        used |= set(re.findall(r'data-track="([a-z-]+)"', f.read_text(encoding="utf-8")))
    js = (ROOT / "site" / "ask.js").read_text(encoding="utf-8")
    used |= set(re.findall(r'track\("([a-z-]+)"', js))
    assert used - {"propose-case"} <= set(impact.EVENTS), used - set(impact.EVENTS)
    monkeypatch.setenv("GOATCOUNTER_CODE", "policy-effect")
    assert 'data-gc="policy-effect"' in mod.page("t", "", "index.html")
    monkeypatch.setenv("GOATCOUNTER_CODE", 'bad code"><script>')
    assert "data-gc" not in mod.page("t", "", "index.html")


def test_issue_boards_show_the_whole_flow(tmp_path, monkeypatch):
    """이슈 보드: 홈의 흐름 띠·흐름 지도, 주제마다 다섯 단계, 계수가 있는 결과는 대시보드 그림."""
    mod = _load_build()
    monkeypatch.setattr(mod, "OUT", tmp_path / "_site")
    mod.main()
    out = tmp_path / "_site"
    home = (out / "index.html").read_text(encoding="utf-8")
    assert 'class="flow"' in home and home.count('class="topic fm-row"') == len(mod.load_topics())
    assert (out / "board.js").exists()
    for t in mod.load_topics():
        page = (out / "topics" / f"{t.id}.html").read_text(encoding="utf-8")
        ids = [f"id='s-{k}'" for k in ("issue", "data", "lineage", "analysis", "dashboard")]
        assert all(i in page for i in ids), t.id
        assert page.index(ids[0]) < page.index(ids[-1])
    pt = (out / "topics" / "public-transit.html").read_text(encoding="utf-8")
    assert 'class="lin-svg"' in pt and 'class="es"' in pt and "data-tip=" in pt
    kpi = json.loads((out / "api" / "metrics.json").read_text(encoding="utf-8"))
    sp = kpi["supply"]
    assert sp["topics"] == len(mod.load_topics()) and 0 <= sp["complete"] <= sp["topics"]
    assert sp["ready"] <= sp["datasets"] and "north_star" in kpi
