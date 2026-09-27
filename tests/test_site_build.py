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
