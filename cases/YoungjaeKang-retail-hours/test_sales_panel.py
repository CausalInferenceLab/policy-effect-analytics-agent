"""실제 지역·매출을 사용하지 않는 패널 변환 검사."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sales_panel import build_panels  # noqa: E402


@pytest.fixture
def totals():
    return pd.DataFrame(
        [
            (gu, q, industry, value)
            for gu in ("synthetic-treated", "synthetic-control")
            for q in range(16)
            for industry, value in (
                ("CS300007", 10),
                ("CS300008", 20),
                ("CS300009", 30),
                ("CS300010", 40),
            )
        ],
        columns=["gu_code", "quarter_idx", "industry_code", "sales_krw"],
    )


def build(frame):
    return build_panels(
        frame, treated_code="synthetic-treated", control_codes=["synthetic-control"]
    )


def test_periods_totals_and_treatment(totals):
    full, panel = build(totals)
    assert len(full) == 32 and len(panel) == 30
    assert full.sales_krw.eq(100).all()
    assert np.allclose(panel.log_sales, np.log(100))
    for _, group in panel.groupby("gu_code"):
        assert group.quarter_idx.tolist() == [*range(12), 13, 14, 15]
        assert group.treated.nunique() == 1
    assert panel.loc[panel.gu_code == "synthetic-treated", "treated"].eq(1).all()
    assert panel.loc[panel.gu_code == "synthetic-control", "treated"].eq(0).all()
    assert set(panel.loc[panel.quarter_idx < 13, "quarter_idx"]) == set(range(12))
    pd.testing.assert_frame_equal(build(totals.sample(frac=1, random_state=7))[1], panel)


@pytest.mark.parametrize("value", [np.nan, np.inf, -1])
def test_invalid_amount(totals, value):
    totals["sales_krw"] = totals.sales_krw.astype(float)
    totals.loc[0, "sales_krw"] = value
    with pytest.raises(ValueError):
        build(totals)


def test_missing_or_duplicate_industry(totals):
    with pytest.raises(ValueError, match="16분기"):
        build(totals.iloc[1:])
    with pytest.raises(ValueError, match="중복"):
        build(pd.concat([totals, totals.iloc[:1]]))


@pytest.mark.parametrize("quarter", [0.5, 16, -1])
def test_invalid_quarter(totals, quarter):
    totals["quarter_idx"] = totals.quarter_idx.astype(float)
    totals.loc[0, "quarter_idx"] = quarter
    with pytest.raises(ValueError, match="quarter_idx"):
        build(totals)


def test_zero_and_transition_retention(totals):
    totals.loc[totals.quarter_idx == 12, "sales_krw"] = 0
    full, panel = build(totals)
    assert full.loc[full.quarter_idx == 12, "sales_krw"].eq(0).all()
    assert len(panel) == 30
    totals.loc[totals.quarter_idx == 11, "sales_krw"] = 0
    with pytest.raises(ValueError, match="로그"):
        build(totals)


def test_no_automatic_selection(totals):
    with pytest.raises(ValueError, match="명단"):
        build(totals.loc[totals.gu_code == "synthetic-treated"])
    with pytest.raises(ValueError, match="중복 없는"):
        build_panels(totals, treated_code="synthetic-treated", control_codes=[])
