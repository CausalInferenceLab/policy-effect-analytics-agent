"""서울 출산지원금 케이스의 결측·중복·정책 오분류 방지 검사. 모두 합성 입력이다."""

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

CASE = Path(__file__).resolve().parents[1] / "cases" / "ingyeoking13-seoul-birth-support"
SPEC = importlib.util.spec_from_file_location("seoul_birth_fetch", CASE / "fetch.py")
fetch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fetch)


@pytest.fixture
def policies():
    return [
        {
            "district": name,
            "status": "verified",
            "history_start": "2022-01-01",
            "history_end": "2024-12-31",
            "evidence_note": "합성 검증 데이터 — 실제 정책 근거가 아님",
            "sources": [
                {
                    "url": "https://example.org/policy",
                    "license": "other",
                    "checked_on": "2026-10-19",
                }
            ],
            "first_child_won": {
                "2022": 100,
                "2023": 200 if i == 0 else 100,
                "2024": 200 if i == 0 else 100,
            },
            "conditions_unchanged": True,
            "change_date": "2023-01-01" if i == 0 else None,
        }
        for i, name in enumerate(fetch.DISTRICTS)
    ]


@pytest.fixture
def births():
    return pd.DataFrame(
        [
            (district, year, month, month)
            for district in fetch.DISTRICTS
            for year in fetch.YEARS
            for month in range(1, 13)
        ],
        columns=["district", "year", "month", "births"],
    )


def test_full_panel_and_explicit_exclusion(policies, births):
    policies[-1] = {
        "district": fetch.DISTRICTS[-1],
        "status": "excluded",
        "reason": "정책 변경 시점이 다름",
    }
    groups, excluded = fetch.policy_groups(policies)
    panel = fetch.build_panel(births, groups)
    assert len(panel) == 24 * 7
    assert set(panel["treated"]) == {0, 1}
    assert panel["births"].eq(78).all()
    np.testing.assert_allclose(panel["log_births"], np.log(78))
    assert fetch.DISTRICTS[-1] in excluded


@pytest.mark.parametrize("status", ["unverified", None])
def test_unknown_policy_is_not_a_zero_or_control(policies, status):
    policies[0]["status"] = status
    with pytest.raises(ValueError, match="미확인"):
        fetch.policy_groups(policies)


def test_requires_all_districts_and_no_duplicates(policies):
    policies[-1] = policies[0]
    with pytest.raises(ValueError, match="25개"):
        fetch.policy_groups(policies)


@pytest.mark.parametrize("change", ["2023-07-01", None])
def test_wrong_or_missing_start_date_is_not_simultaneous_treatment(policies, change):
    policies[0]["change_date"] = change
    with pytest.raises(ValueError, match="다른 변경"):
        fetch.policy_groups(policies)


def test_missing_amount_is_not_zero(policies):
    policies[0]["first_child_won"]["2022"] = None
    with pytest.raises(ValueError, match="정수"):
        fetch.policy_groups(policies)


def test_changed_eligibility_requires_exclusion(policies):
    policies[0]["conditions_unchanged"] = False
    with pytest.raises(ValueError, match="지급조건"):
        fetch.policy_groups(policies)


@pytest.mark.parametrize("bad_value", [None, "-", "X", -1, 1.5, float("inf")])
def test_bad_birth_counts_cannot_be_summed(births, bad_value):
    births["births"] = births["births"].astype(object)
    births.loc[0, "births"] = bad_value
    with pytest.raises(ValueError):
        fetch.build_panel(births, {fetch.DISTRICTS[0]: 1, fetch.DISTRICTS[1]: 0})


def test_incomplete_year_fails_instead_of_partial_total(births):
    with pytest.raises(ValueError, match="누락"):
        fetch.build_panel(births.iloc[1:], {fetch.DISTRICTS[0]: 1, fetch.DISTRICTS[1]: 0})


def test_duplicate_month_is_not_double_counted(births):
    doubled = pd.concat([births, births.iloc[:1]])
    with pytest.raises(ValueError, match="중복"):
        fetch.build_panel(doubled, {fetch.DISTRICTS[0]: 1, fetch.DISTRICTS[1]: 0})


def test_seoul_total_or_neighborhood_is_rejected(births):
    births.loc[0, "district"] = "서울시"
    with pytest.raises(ValueError, match="총계"):
        fetch.build_panel(births, {fetch.DISTRICTS[0]: 1, fetch.DISTRICTS[1]: 0})


def test_unverified_policy_stops_before_outcomes_are_read(tmp_path, monkeypatch):
    case = tmp_path / "case"
    raw = case / "data" / "raw"
    raw.mkdir(parents=True)
    (case / "plan.yaml").write_text((CASE / "plan.yaml").read_text())
    import yaml

    (raw / "policy_review.yaml").write_text(
        yaml.safe_dump(
            [{"district": district, "status": "unverified"} for district in fetch.DISTRICTS]
        )
    )
    monkeypatch.setattr(
        fetch.subprocess, "run", lambda *args, **kwargs: type("Result", (), {"returncode": 0})()
    )
    monkeypatch.setattr(
        fetch.pd, "read_csv", lambda *args, **kwargs: pytest.fail("결과 CSV를 먼저 읽으면 안 됨")
    )
    with pytest.raises(ValueError, match="미확인"):
        fetch.prepare(case)
    assert not (case / "data" / "panel.csv").exists()
