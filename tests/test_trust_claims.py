"""판정 옆 '말할 수 있는 것', 검토 배지, 구조화 데이터(Dataset · ClaimReview)."""

import json
import re
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "site"))

import answers as ans  # noqa: E402
from quality import checks, next_steps  # noqa: E402

A = {a["case"]: a for a in ans.load_answers()}


def _ld(a):
    m = re.search(r'<script type="application/ld\+json">(.*)</script>', ans.jsonld(a), re.S)
    return json.loads(m.group(1))


def test_takeaway_never_leaves_only_dont_know():
    for a in A.values():
        t = ans.takeaway(a)
        if a["verdict"] == "not_identified" or a.get("execution_kind") == "descriptive_only":
            assert t and t["text"], a["case"]
    hy = ans.takeaway(A["hyun2-land-permit-spillover-2020"])
    assert hy["head"] == "그래도 말할 수 있는 것" and "맞지 않습니다" in hy["text"]


def test_usage_rules_shared_with_page():
    a = A["hyun2-land-permit-spillover-2020"]
    do, dont = ans.usage_rules(a)
    page = ans.page_body(escape, a, {}, {})
    assert all(escape(x) in page for x in do + dont)
    assert 'class="takeaway"' in page


def test_primary_range_in_percent_for_log_outcomes():
    pr = ans.primary_range(A["hyun2-land-permit-spillover-2020"])
    assert pr["unit"] == "%" and pr["lo"] < pr["est"] < pr["hi"]


def test_dataset_jsonld_and_no_claimreview_without_human_claims():
    a = A["hyun2-land-permit-spillover-2020"]
    d = _ld({**a, "claims": []})
    assert d["@type"] == "Dataset" and d["distribution"][0]["contentUrl"].endswith(".csv")


def test_claimreview_only_with_valid_rating():
    a = A["hyun2-land-permit-spillover-2020"]
    claim = {
        "text": "토허제로 옆 동네 집값이 20% 올랐다",
        "by": "어느 신문",
        "url": "https://example.org/n",
        "date": "2020-08-01",
    }
    d = _ld({**a, "claims": [claim | {"rating": "결과와 다름"}]})
    assert [x["@type"] for x in d] == ["Dataset", "ClaimReview"]
    assert (
        d[1]["reviewRating"]["alternateName"] == "결과와 다름"
        and d[1]["claimReviewed"] == claim["text"]
    )
    d2 = _ld({**a, "claims": [claim | {"rating": "아마도"}]})
    assert d2["@type"] == "Dataset"


def test_review_status_shows_in_trust_and_todo():
    a = dict(A["hyun2-land-permit-spillover-2020"])
    assert any(h.startswith("검토 · 아직") for _, h, _ in checks(a | {"reviewed_by": []}))
    assert any(h == "검토 · 통과" for _, h, _ in checks(a | {"reviewed_by": ["someone"]}))
    p = {"stages": [True, True, True, True]}
    assert any("검토 요청" in t for t in next_steps(p, a | {"reviewed_by": []}, True))
    card = ans.card(escape, a | {"reviewed_by": ["someone"]}, {})
    assert "검토됨" in card


def test_search_index_carries_claim_check_fields(tmp_path):
    import projects as proj
    import search

    from core.discovery.catalog import load_topics
    from core.discovery.links import all_lineages
    from core.discovery.ontology import load_datasets, load_issues

    items = search.index(
        load_topics(),
        load_issues(),
        load_datasets(),
        list(A.values()),
        proj.load_projects(),
        all_lineages(),
    )
    res = [i for i in items if i["t"] == "result"]
    assert all({"v", "ro", "pr", "rules", "rev"} <= i.keys() for i in res)
    js = (ROOT / "site" / "search.js").read_text(encoding="utf-8")
    assert "checkClaim" in js and "결과와 다름" in js and "공식 팩트체크가 아니에요" in js


def test_claim_record_link_and_template():
    js = (ROOT / "site" / "search.js").read_text(encoding="utf-8")
    assert "template=claim-review.yml" in js and "&claim=" in js and "&case=" in js
    tpl = (ROOT / ".github" / "ISSUE_TEMPLATE" / "claim-review.yml").read_text(encoding="utf-8")
    for fid in ("id: claim", "id: url", "id: case", "id: auto", "id: rating"):
        assert fid in tpl
    for rating in ans.CLAIM_RATINGS:
        assert rating in tpl


def test_review_pairs_never_assign_self():
    import projects as proj

    mentee = [p for p in proj.load_projects() if not p["mentor"]]
    html = proj.review_pairs(escape, mentee)
    assert 'id="review"' in html
    for row in re.findall(r"<tr><td>(.*?)</tr>", html):
        owner = re.search(r"<div class='muted small'>@([^<]+)</div>", row).group(1)
        reviewer = re.search(r"github.com/([^']+)'", row).group(1)
        assert owner != reviewer
