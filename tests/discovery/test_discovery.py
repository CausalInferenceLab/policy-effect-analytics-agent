from pathlib import Path

from core.discovery import discover, load_catalog
from core.discovery.search import parse_results

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "datago" / "search_apt_trade.html"


def test_catalog_loads_and_sample_case_exists():
    cat = load_catalog()
    assert {p.id for p in cat} >= {"T1", "T3", "T5"}
    t3 = next(p for p in cat if p.id == "T3")
    assert t3.design == "did_simultaneous" and t3.support == "지원"
    assert (Path(__file__).resolve().parents[2] / t3.sample_case / "plan.yaml").exists()


def test_social_text_maps_to_policy():
    r = discover("토허제 강남3구·용산까지 확대하고 집값 잡혔나? 옆 동네만 올랐다던데")
    assert r.top.id == "T3" and "토허제" in r.matches[0].hits
    assert r.sample_case is not None


def test_unrelated_text_returns_no_match():
    r = discover("오늘 점심 뭐 먹지")
    assert r.matches == [] and "찾지 못했습니다" in r.next_step


def test_unsupported_design_is_flagged():
    r = discover("안전속도 5030 이후 보행자 교통사고")
    assert r.top.id == "T4" and "준비 중" in r.next_step


def test_parse_datago_search_fixture():
    hits = parse_results(FIX.read_text(encoding="utf-8"), limit=10)
    assert any(h.id == "15126468" and h.kind.startswith("오픈API") for h in hits)
    assert all(h.url.startswith("https://www.data.go.kr/data/") for h in hits)
