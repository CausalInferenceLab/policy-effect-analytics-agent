"""수집 누락·오분류와 인증키 유출 방지. 실제 API 대신 합성 XML을 사용한다."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

CASE = Path(__file__).resolve().parents[1] / "cases" / "ingyeoking13-seoul-birth-support"
SPEC = importlib.util.spec_from_file_location("seoul_welfare", CASE / "collect_welfare.py")
welfare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(welfare)
KEY = "synthetic+credential/only=="


def service(service_id, name="노인 복지", district="종로구"):
    return (
        f"<servId>{service_id}</servId><servNm>{name}</servNm>"
        f"<ctpvNm>서울특별시</ctpvNm><sggNm>{district}</sggNm>"
    )


def response(body, status=200):
    return SimpleNamespace(status_code=status, content=body.encode())


def page(number, services, total=3):
    rows = "".join(f"<servList>{row}</servList>" for row in services)
    return response(
        f"<response><resultCode>0</resultCode><pageNo>{number}</pageNo>"
        f"<numOfRows>2</numOfRows><totalCount>{total}</totalCount>{rows}</response>"
    )


@pytest.fixture
def responses(monkeypatch):
    monkeypatch.setattr(welfare, "PAGE_SIZE", 2)
    monkeypatch.setattr(welfare.time, "sleep", lambda _: None)
    return [
        page(1, [service("A", "출산축하금"), service("B")]),
        page(2, [service("C", district="중구")]),
        response(
            "<response><resultCode>0</resultCode>"
            + service("A", "출산축하금")
            + "<baslawList><name>법1</name></baslawList>"
            + "<baslawList><name>법2</name></baslawList></response>"
        ),
    ]


def client(responses):
    pending = iter(responses)

    def get(url, **kwargs):
        assert url.startswith(welfare.BASE_URL + "/")
        assert kwargs["params"]["serviceKey"] == KEY
        assert kwargs["allow_redirects"] is False
        return next(pending)

    return SimpleNamespace(get=get)


def test_complete_pages_details_provenance_and_no_credentials(tmp_path, responses):
    result = welfare.collect(tmp_path, KEY, ("종로구", "중구", "용산구"), session=client(responses))
    directory = Path(result["directory"])
    assert result["total_services"] == 3
    assert result["detail_services"] == 1
    assert result["district_counts"]["용산구"] == {"all_services": 0, "candidates": 0}
    assert result["history_verified"] is False
    details = json.loads((directory / "details.json").read_text())
    assert details[0]["baslawList"] == [{"name": "법1"}, {"name": "법2"}]
    assert set(result["files_sha256"]) == {p.name for p in directory.iterdir()} - {"manifest.json"}
    for path in directory.iterdir():
        assert KEY not in path.read_text()
        assert "serviceKey" not in path.read_text()


@pytest.mark.parametrize(
    "problem", ["duplicate", "missing", "changed_total", "wrong_region", "wrong_detail"]
)
def test_incomplete_or_inconsistent_snapshot_has_no_manifest(tmp_path, responses, problem):
    if problem == "duplicate":
        responses[1] = page(2, [service("B")])
    elif problem == "missing":
        responses[1] = page(2, [])
    elif problem == "changed_total":
        responses[1] = page(2, [service("C")], total=4)
    elif problem == "wrong_region":
        responses[1].content = responses[1].content.replace(
            "서울특별시".encode(), "부산광역시".encode()
        )
    else:
        responses[2].content = responses[2].content.replace(
            b"<servId>A</servId>", b"<servId>Z</servId>"
        )
    with pytest.raises(ValueError):
        welfare.collect(tmp_path, KEY, ("종로구", "중구"), session=client(responses))
    assert not list(tmp_path.rglob("manifest.json"))


def test_authentication_error_does_not_expose_response_or_key():
    error = response(f"<response><resultCode>30</resultCode><message>{KEY}</message></response>")
    with pytest.raises(ValueError) as exc:
        welfare.request_xml(client([error]), "LcgvWelfarelist", {}, KEY)
    assert KEY not in str(exc.value)


def test_network_exception_does_not_expose_authenticated_url():
    def get(*args, **kwargs):
        raise requests.ConnectionError("https://example.test/?serviceKey=" + KEY)

    with pytest.raises(ValueError) as exc:
        welfare.request_xml(SimpleNamespace(get=get), "LcgvWelfarelist", {}, KEY)
    assert KEY not in str(exc.value)
    assert exc.value.__suppress_context__


def test_candidate_screening_is_broader_than_cash_benefits():
    assert welfare.is_candidate({"servNm": "건강관리", "lifeNmArray": "임신·출산"})
    assert welfare.is_candidate({"servNm": "산후조리 비용 지원"})
    assert not welfare.is_candidate({"servNm": "어르신 교통비"})


def test_education_office_is_preserved_separately_from_districts(tmp_path, responses):
    responses[1] = page(2, [service("C", district="서울특별시교육청")])
    result = welfare.collect(tmp_path, KEY, ("종로구", "중구"), session=client(responses))
    assert result["other_region_labels"] == {
        "서울특별시교육청": {"all_services": 1, "candidates": 0}
    }
    assert result["district_counts"]["중구"]["all_services"] == 0
