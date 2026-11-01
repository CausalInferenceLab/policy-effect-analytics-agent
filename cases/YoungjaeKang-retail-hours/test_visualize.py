"""보고서가 미관측 금액과 관측 진입·이탈을 잘못 표현하지 않는지 검사한다."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import visualize  # noqa: E402
from sales_panel import INDUSTRIES  # noqa: E402


def fixture():
    rows = []
    for q in range(16):
        for i, ind in enumerate(INDUSTRIES):
            present = i == 0
            count = (2 if q >= 1 else 1) if present else 0
            rows.append(
                (
                    "동대문구",
                    q,
                    ind,
                    count,
                    10 if present else None,
                    None if q == 0 else int(present and q == 1),
                    None if q == 0 else 0,
                )
            )
    return pd.DataFrame(
        rows,
        columns=[
            "gu_name",
            "quarter_idx",
            "industry_code",
            "observed_areas",
            "observed_raw_amount_krw",
            "entered_observation",
            "left_observation",
        ],
    )


def test_first_period_unknown_and_absent_amount_not_zero():
    summary = visualize.summarize(fixture(), ["동대문구"])
    assert summary.loc[0, ["entered_observation", "left_observation"]].isna().all()
    assert summary.missing_industries.eq(3).all()
    assert summary.observed_raw_amount_krw.eq(10).all()
    assert summary.loc[1, "entered_observation"] == 1


@pytest.mark.parametrize("error", ["zero", "grid", "turnover", "first"])
def test_reject_misleading_diagnostics(error):
    rows = fixture()
    if error == "zero":
        rows.loc[1, "observed_raw_amount_krw"] = 0
    elif error == "grid":
        rows = rows.iloc[1:]
    elif error == "turnover":
        rows.loc[4, "entered_observation"] = 0
    else:
        rows.loc[0, "entered_observation"] = 0
    with pytest.raises(ValueError):
        visualize.summarize(rows, ["동대문구"])


def test_failed_audit_never_draws(tmp_path, monkeypatch):
    monkeypatch.setattr(
        visualize, "audit", lambda *a, **k: {"panel_written": False, "blockers": ["bad hash"]}
    )
    monkeypatch.setattr(visualize, "draw", lambda *a: pytest.fail("must not draw stale input"))
    assert visualize.main(["--snapshot", str(tmp_path)]) == 2
