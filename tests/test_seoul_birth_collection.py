"""공식 CSV 형태를 모사한 합성 입력으로 집계·원문 변경 방어를 검사한다."""

import csv
import hashlib
import importlib.util
import io
from pathlib import Path

import pytest

CASE = Path(__file__).resolve().parents[1] / "cases" / "ingyeoking13-seoul-birth-support"


def module(name):
    spec = importlib.util.spec_from_file_location(name, CASE / f"{name}.py")
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


births = module("collect_births")
policies = module("policy_rules")
fetch = module("fetch")


@pytest.fixture
def rows():
    header = ["행정구역"] + [
        f"2018년{month:02}월_{sex}"
        for month in range(1, 13)
        for sex in ("남자인구수", "여자인구수", "계")
    ]
    return [header, ["서울특별시  (1100000000)", *["50", "75", "125"] * 12]] + [
        [f"서울특별시 {district} ({code}00000)", *["2", "3", "5"] * 12]
        for code, district in births.DISTRICT_CODES.items()
    ]


def encode(rows):
    stream = io.StringIO()
    csv.writer(stream).writerows(rows)
    return stream.getvalue().encode("cp949")


def test_monthly_totals_exclude_city_and_sex_duplicates(rows):
    result = births.parse_birth_csv(encode(rows), 2018)
    assert len(result) == 25 * 12
    assert result.births.sum() == 25 * 12 * 5
    assert set(result.district) == set(fetch.DISTRICTS)


@pytest.mark.parametrize("defect", ["month", "duplicate", "code", "sex", "city", "missing"])
def test_bad_official_export_is_rejected(rows, defect):
    if defect == "month":
        rows[0][1] = "2019년01월_남자인구수"
    elif defect == "duplicate":
        rows[-1] = rows[-2]
    elif defect == "code":
        rows[2][0] = "서울특별시 중구 (1111000000)"
    elif defect == "sex":
        rows[2][3] = "6"
    elif defect == "city":
        rows[1][1:4] = ["51", "75", "126"]
    elif defect == "missing":
        rows[2][1] = "-"
    with pytest.raises(ValueError):
        births.parse_birth_csv(encode(rows), 2018)


def test_error_html_is_not_a_successful_csv():
    with pytest.raises(ValueError):
        births.parse_birth_csv(b"<html>temporarily unavailable</html>", 2018)


def test_policy_source_change_stops_review():
    source = {"id": "synthetic", "sha256": hashlib.sha256(b"original").hexdigest()}
    policies.verify_source(b"original", source)
    with pytest.raises(ValueError, match="원문 변경"):
        policies.verify_source(b"changed", source)


def test_uncommitted_protocol_stops_before_birth_download(monkeypatch):
    monkeypatch.syspath_prepend(str(CASE))
    monkeypatch.setattr(
        fetch, "require_committed", lambda path: (_ for _ in ()).throw(ValueError("미커밋"))
    )
    import collect_births

    monkeypatch.setattr(
        collect_births, "collect_births", lambda *args, **kwargs: pytest.fail("출생 조회 금지")
    )
    with pytest.raises(ValueError, match="미커밋"):
        fetch.collect_inputs()


def test_offline_missing_files_do_not_call_network(tmp_path, monkeypatch):
    monkeypatch.setattr(
        births.requests.Session, "post", lambda *args, **kwargs: pytest.fail("네트워크 금지")
    )
    with pytest.raises(ValueError, match="오프라인"):
        births.collect_births(tmp_path, offline=True)
