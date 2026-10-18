"""시간 단위(freq=hour) 분석: 스키마, 시점 인덱스, 적용 시간대, 상대시점 묶음, 적용 외 시간대 반증 (이슈 #13)."""

import numpy as np
import pandas as pd
import pytest
import yaml
from pydantic import ValidationError

from core.pipeline import run_plan
from core.schema.plan import Plan
from core.schema.timeindex import hour_of_day, in_window, index_of, period_index

ORIGIN = "2019-11-01 00:00"
START = "2019-12-01 06:00"  # 녹색교통지역 운행제한 시작을 본뜬 가상 시점


def panel(effect=-0.3, n_units=15, n_treated=3, days=40, seed=1) -> pd.DataFrame:
    """측정소 × 시간. 효과는 처치 측정소의 06~21시에만 있다."""
    rng = np.random.default_rng(seed)
    ts = pd.date_range(ORIGIN, periods=days * 24, freq="h")
    t0 = index_of(START, "hour", ORIGIN)
    rows = []
    for u in range(n_units):
        a = rng.normal(3.0, 0.2)
        for t, when in zip(period_index(ts, "hour", ORIGIN), ts, strict=True):
            h = when.hour
            active = 6 <= h < 21
            y = a + 0.3 * np.sin(h / 24 * 2 * np.pi) + rng.normal(0, 0.1)
            if u < n_treated and t >= t0 and active:
                y += effect
            rows.append(
                {"station": u, "t": int(t), "hour": h, "treated": int(u < n_treated), "no2": y}
            )
    return pd.DataFrame(rows)


def plan_dict(**over) -> dict:
    d = {
        "case_id": "zz-green-zone",
        "title": "t",
        "question": "q",
        "unit": {"name": "측정소", "id_col": "station"},
        "time": {
            "col": "t",
            "freq": "hour",
            "start": ORIGIN,
            "end": "2019-12-10",
            "hour_col": "hour",
            "active_hours": [6, 21],
        },
        "treatment": {
            "definition": "d",
            "group_col": "treated",
            "treat_time": index_of(START, "hour", ORIGIN),
        },
        "control": {"definition": "d", "rationale": "r"},
        "outcomes": [{"name": "NO2", "col": "no2", "definition": "d", "primary": True}],
        "estimator": {
            "method": "event_study",
            "cluster_col": "station",
            "event_bin": 24,
            "window": [-5, 5],
            "ref_period": -1,
        },
        "assumptions": [{"name": "평행추세", "description": "d", "check": "pretrend_test"}],
        "refutations": [
            {"kind": "placebo_window"},
            {"kind": "placebo_time", "params": {"shift": 5}},
        ],
        "abstention": [{"when": "placebo_window_significant", "verdict": "conditional"}],
        "data_sources": [{"name": "test", "provider": "test", "license": "other"}],
    }
    for k, v in over.items():
        d[k] = {**d[k], **v} if isinstance(v, dict) else v
    return d


def test_timeindex_helpers():
    assert period_index(["2019-11-01 00:00", "2019-11-02 06:30"], "hour", ORIGIN).tolist() == [
        0,
        30,
    ]
    assert index_of("2020-03", "month", "2019-01") == 14
    assert index_of("2019-12-01", "day", "2019-11-01") == 30
    assert hour_of_day(["2019-12-01 05:00", "2019-12-01 24", "2019-12-01 24:00"]).tolist() == [
        5,
        0,
        0,
    ]
    assert in_window(pd.Series([5, 6, 20, 21]), (6, 21)).tolist() == [False, True, True, False]
    assert in_window(pd.Series([21, 23, 0, 5, 6]), (22, 6)).tolist() == [
        False,
        True,
        True,
        True,
        False,
    ]
    assert in_window(pd.Series([6, None, "7", "x"]), (6, 21)).tolist() == [True, False, True, False]
    # 에어코리아 형식(YYYYMMDDHH, 24시)과 '24:00:00', 분이 24인 경우
    assert period_index(
        ["2019110124", "2019-11-01 24:00:00", "2019-11-01 05:24:00"], "hour", ORIGIN
    ).tolist() == [24, 24, 5]
    assert hour_of_day(["2019110124", "2019-11-01 05:24:00", "모름"]).tolist()[:2] == [0, 5]
    with pytest.raises(ValueError, match="읽을 수 없는"):
        period_index(["2019-11-01", "모름"], "day", ORIGIN)
    with pytest.raises(ValueError):
        index_of("2019-12-01", "minute", ORIGIN)


def test_schema_rules_for_hourly():
    Plan.model_validate(plan_dict())
    d = plan_dict()
    d["estimator"].pop("event_bin")
    with pytest.raises(ValidationError, match="event_bin"):
        Plan.model_validate(d)
    d = plan_dict()
    d["time"].pop("hour_col")
    with pytest.raises(ValidationError, match="hour_col"):
        Plan.model_validate(d)
    d = plan_dict()
    d["time"].pop("active_hours")
    with pytest.raises(ValidationError, match="active_hours"):
        Plan.model_validate(d)
    Plan.model_validate(plan_dict(time={"active_hours": [22, 6]}))  # 자정을 넘는 시간대
    with pytest.raises(ValidationError):
        Plan.model_validate(plan_dict(time={"active_hours": [6, 6]}))


def test_hourly_event_study_with_day_bins_and_placebo_window():
    plan = Plan.model_validate(plan_dict())
    (r,) = run_plan(plan, panel())
    assert -0.4 < r.estimate < -0.2  # 적용 시간대 효과 -0.3
    rels = sorted(r.extra["coefs"]["rel_time"].tolist())
    assert rels[0] == -5 and rels[-1] == 5  # 상대시점이 '일' 단위로 묶임
    pw = r.assumptions_checked["placebo_window"]
    assert pw["passed"] and abs(pw["estimate"]) < 0.1  # 적용 외 시간대에는 효과 없음
    assert "placebo_window_significant" not in r.triggers
    assert r.assumptions_checked["pre_periods"] >= 5


def test_placebo_window_catches_all_day_shift():
    """하루 종일 움직였다면(정책 외 요인) 적용 외 시간대 반증이 잡아야 한다."""
    df = panel(effect=0.0)
    df.loc[(df.treated == 1) & (df.t >= index_of(START, "hour", ORIGIN)), "no2"] -= 0.3
    (r,) = run_plan(Plan.model_validate(plan_dict()), df)
    assert "placebo_window_significant" in r.triggers and r.verdict == "conditional"


def test_missing_hours_go_to_neither_window():
    from core.pipeline import split_hours

    df = panel(days=34)
    df.loc[df.index[::20], "hour"] = None
    plan = Plan.model_validate(plan_dict())
    on, off = split_hours(plan, df)
    assert len(on) + len(off) == df.hour.notna().sum()


def test_flow_end_to_end_hourly(tmp_path):
    from core.agent import run_flow

    case = tmp_path / "zz-green-zone"
    (case / "data").mkdir(parents=True)
    panel(days=36).to_csv(case / "data" / "panel.csv", index=False)
    (case / "plan.yaml").write_text(
        yaml.safe_dump(plan_dict(), allow_unicode=True), encoding="utf-8"
    )
    s = run_flow(case, None, True, False)
    assert s.status in {"ok", "warn"}, [(x.step, x.status, x.message) for x in s.steps]
    assert (case / "figures" / "raw_trends.png").exists() and (case / "report.md").exists()
