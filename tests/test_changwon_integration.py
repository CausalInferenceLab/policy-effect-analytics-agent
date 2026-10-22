"""창원 통합 케이스: 경계 재구성·대조군 선정·합성통제·흐름 실행 검사. 네트워크 없이 합성 입력만 쓴다."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "cases" / "buildergarlic-changwon-integration"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"changwon_{name}", CASE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


fetch = _load("fetch")
synth = _load("synth")


def _long(rows):
    return pd.DataFrame(rows, columns=["region_code", "region", "item", "period", "value"])


# ── 계획 ↔ 코드 정합성 ─────────────────────────────────────────────────────────────────────────
def test_plan_matches_folder_and_fetch_constants():
    from core.schema.plan import load_plan

    p = load_plan(CASE / "plan.yaml")
    assert p.case_id == CASE.name and not p.synthetic_data
    assert p.treatment.treat_time == fetch.TREAT_TIME == fetch.MERGE_YEAR + 1
    assert (p.time.start, p.time.end) == (fetch.START, fetch.END)
    tbls = {d.query["tblId"] for d in p.data_sources if d.adapter == "kosis"}
    assert {fetch.POP_TBL, fetch.MIG_TBL, fetch.FIS_TBL} <= tbls
    assert len(fetch.DONOR_CITIES) == len(set(fetch.DONOR_CITIES)) >= 50
    assert not set(fetch.PRE_MERGER) & set(fetch.DONOR_CITIES)
    # 경계가 바뀐 시와 인접 시는 대조군이 아니어야 한다
    for city in ("청주시", "공주시", "계룡시", "제주시", "서귀포시", "김해시", "밀양시", "세종시"):
        assert city not in fetch.DONOR_CITIES, city


# ── 경계 재구성 ────────────────────────────────────────────────────────────────────────────────
def test_city_rows_keeps_only_basic_local_governments():
    long = _long(
        [
            ("00", "전국", "총인구수", "2009", "1"),
            ("48", "경상남도", "총인구수", "2009", "1"),
            ("48120", "창원시", "총인구수", "2009", "10"),
            ("48121", "의창구", "총인구수", "2009", "5"),  # 일반구 → 제외(이중 계산 방지)
            ("41110", "경기도 수원시", "총인구수", "2009", "7"),  # 시도 접두어 제거
            ("48110", "마산시", "총인구수", "2009", "-"),  # 비공개 표기 → NaN
        ]
    )
    d = fetch.city_rows(long)
    assert set(d["region"]) == {"창원시", "수원시", "마산시"}
    assert d["year"].dtype.kind == "i" and d.loc[d["region"] == "마산시", "value"].isna().all()


def _toy(values_by_city: dict[str, float], years=(2008, 2009, 2010, 2011)):
    rows = []
    for y in years:
        for city, v in values_by_city.items():
            gone = city in ("마산시", "진해시") and y >= fetch.MERGE_YEAR
            rows.append((city, y, np.nan if gone else v))
    return pd.DataFrame(rows, columns=["region", "year", "value"])


def test_reconstruct_sums_three_cities_before_merger_and_drops_transition_year():
    d = _toy({"마산시": 1.0, "진해시": 2.0, "창원시": 4.0, "진주시": 9.0, "청주시": 99.0})
    out = fetch.reconstruct(d, "sum").set_index(["region", "year"])["value"]
    assert out["창원시", 2009] == 7.0 and out["창원시", 2011] == 4.0
    assert out["진주시", 2008] == 9.0
    assert fetch.MERGE_YEAR not in out.index.get_level_values("year")
    assert "청주시" not in out.index.get_level_values("region")  # 대조군 목록에 없는 시는 제외
    assert "마산시" not in out.index.get_level_values("region")


def test_reconstruct_refuses_partial_pre_merger_rows():
    d = _toy({"마산시": 1.0, "창원시": 4.0, "진주시": 9.0})  # 진해 없음
    with pytest.raises(ValueError, match="진해시"):
        fetch.reconstruct(d, "sum")


def test_reconstruct_refuses_double_counting_after_merger():
    d = _toy({"마산시": 1.0, "진해시": 2.0, "창원시": 4.0, "진주시": 9.0})
    d.loc[(d["region"] == "마산시") & (d["year"] == 2011), "value"] = 1.0
    with pytest.raises(ValueError, match="통합 후"):
        fetch.reconstruct(d, "sum")


def test_reconstruct_weighted_mean_uses_population_weights():
    fis = _toy({"마산시": 20.0, "창원시": 60.0, "진해시": 40.0, "진주시": 30.0})
    pop = _toy({"마산시": 1.0, "창원시": 1.0, "진해시": 2.0, "진주시": 5.0})
    out = fetch.reconstruct(fis, "wmean", weights=pop).set_index(["region", "year"])["value"]
    assert out["창원시", 2009] == pytest.approx((20 + 60 + 80) / 4)
    assert out["창원시", 2011] == 60.0 and out["진주시", 2009] == 30.0


def test_assemble_builds_balanced_panel_with_outcomes():
    years = (*fetch.YEARS, fetch.MERGE_YEAR)
    cities = (*fetch.DONOR_CITIES, *fetch.PRE_MERGER)
    pop, mig, fis = [], [], []
    for i, c in enumerate(cities):
        code = f"{10000 + i * 10:05d}"
        for y in years:
            gone = c in ("마산시", "진해시") and y >= fetch.MERGE_YEAR
            v = "-" if gone else str(100_000 + 1000 * i + y)
            pop.append((code, c, "총인구수", str(y), v))
            mig.append((code, c, "총전입", str(y), "-" if gone else "5000"))
            mig.append((code, c, "총전출", str(y), "-" if gone else "4000"))
            mig.append((code, c, "시군구내이동", str(y), "-" if gone else "9999"))
            fis.append((code, c, "재정자립도", str(y), "-" if gone else "30.0"))
    panel, chosen = fetch.assemble(_long(pop), _long(mig), _long(fis))
    assert chosen["in_moves"] == "총전입" and chosen["out_moves"] == "총전출"
    assert len(panel) == len(fetch.UNITS) * len(fetch.YEARS)
    assert panel["treated"].sum() == len(fetch.YEARS)
    cw = panel[panel["region_id"] == "창원시"].set_index("year")
    i_m, i_c, i_j = (cities.index(x) for x in ("마산시", "창원시", "진해시"))
    assert cw.loc[2009, "population"] == sum(100_000 + 1000 * k + 2009 for k in (i_m, i_c, i_j))
    assert cw.loc[2009, "net_migration_rate"] == pytest.approx(
        3 * 1000 / cw.loc[2009, "population"] * 1000
    )
    assert cw.loc[2011, "net_migration_rate"] == pytest.approx(
        1000 / cw.loc[2011, "population"] * 1000
    )
    assert cw["fiscal_independence"].eq(30.0).all()
    assert np.allclose(panel["log_population"], np.log(panel["population"]))


def test_finalize_refuses_missing_values_instead_of_filling():
    panel = fetch.simulate()
    panel.loc[3, "fiscal_independence"] = np.nan
    with pytest.raises(ValueError, match="결측"):
        fetch.finalize(panel.drop(columns=["log_population", "net_migration_rate"]))


def test_simulated_panel_is_balanced_single_treated():
    d = fetch.simulate()
    assert d.groupby("region_id")["year"].nunique().nunique() == 1
    assert d.loc[d["treated"] == 1, "region_id"].nunique() == 1
    assert fetch.MERGE_YEAR not in set(d["year"])


# ── 합성통제 ───────────────────────────────────────────────────────────────────────────────────
def _synth_panel(effect: float, seed: int = 3, n_donors: int = 12, t0: int = 2011):
    rng = np.random.default_rng(seed)
    years = [y for y in range(1998, 2024) if y != 2010]
    donors = {
        f"D{i:02d}": np.cumsum(rng.normal(0.01, 0.03, len(years))) + rng.normal(0, 0.5)
        for i in range(n_donors)
    }
    w = {"D00": 0.5, "D01": 0.3, "D02": 0.2}
    treated = sum(w[k] * donors[k] for k in w) + np.array(
        [effect if y >= t0 else 0.0 for y in years]
    )
    wide = pd.DataFrame({**donors, "T": treated}, index=pd.Index(years, name="year"))
    return wide, w


def test_synth_recovers_weights_and_planted_effect():
    wide, w = _synth_panel(effect=-0.2)
    donors = [c for c in wide.columns if c != "T"]
    main, placebos, inf = synth.placebo_in_space(wide, "T", 2011, donors)
    for k, v in w.items():
        assert main["weights"].get(k, 0.0) == pytest.approx(v, abs=0.02)
    assert main["pre_rmspe"] < 1e-3
    assert main["post_mean_gap"] == pytest.approx(-0.2, abs=0.01)
    assert inf["p_rmspe_ratio"] <= 2 / (len(donors) + 1)  # 처치 단위가 비율 순위 1~2위
    loo = synth.leave_one_out(wide, "T", 2011, donors, main["weights"])
    assert set(loo) == set(w) and all(abs(v + 0.2) < 0.15 for v in loo.values())


def test_synth_null_effect_gives_small_gap_and_large_p():
    wide, _ = _synth_panel(effect=0.0, seed=5)
    donors = [c for c in wide.columns if c != "T"]
    main, _, inf = synth.placebo_in_space(wide, "T", 2011, donors)
    assert abs(main["post_mean_gap"]) < 0.01
    assert inf["p_rmspe_ratio"] > 0.2


def test_fit_weights_is_a_simplex():
    rng = np.random.default_rng(0)
    y0 = rng.normal(size=(8, 6))
    w = synth.fit_weights(y0 @ np.array([0.2, 0.2, 0.2, 0.2, 0.1, 0.1]), y0)
    assert w.min() >= 0 and w.sum() == pytest.approx(1.0)


# ── 전체 흐름 (합성 패널, 사전 등록 게이트 우회) ─────────────────────────────────────────────────
def test_flow_and_synth_run_end_to_end_on_simulated_panel(tmp_path):
    from core.agent import run_flow

    case = tmp_path / "cases" / CASE.name
    shutil.copytree(
        CASE,
        case,
        ignore=shutil.ignore_patterns("data", "figures", "synth_*", "report.md", "*.json"),
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT), "MPLBACKEND": "Agg", "KOSIS_API_KEY": ""}
    subprocess.run([sys.executable, "fetch.py", "--simulate"], check=True, cwd=case, env=env)
    plan = yaml.safe_load((case / "plan.yaml").read_text(encoding="utf-8"))
    plan["synthetic_data"] = True  # 합성 패널이므로 리포트에 경고가 붙어야 한다
    plan["data_sources"].insert(
        0,
        {"name": "합성 패널 (fetch.py --simulate)", "provider": "fetch.py", "license": "synthetic"},
    )
    (case / "plan.yaml").write_text(
        yaml.safe_dump(plan, allow_unicode=True, sort_keys=False), "utf-8"
    )

    state = run_flow(str(case), allow_uncommitted=True)
    assert state.status in {"ok", "warn"}, [s.message for s in state.steps]
    assert [r.outcome for r in state.results] == [o["col"] for o in plan["outcomes"]]
    primary = state.results[0]
    assert "few_treated_clusters" in primary.triggers  # 처치 단위 1개 → 무작위화 추론
    assert "randomization" in primary.assumptions_checked["inference"]
    assert primary.verdict in {
        "conditional",
        "not_identified",
    }  # 단일 처치 단위는 '식별됨'이 될 수 없음
    report = (case / "report.md").read_text(encoding="utf-8")
    assert "합성(synthetic)" in report and (case / "figures" / "event_study.png").exists()

    res = synth.run(case)
    assert res["synthetic_data"] and set(res["outcomes"]) == {o["col"] for o in plan["outcomes"]}
    for col in res["outcomes"]:
        assert (case / "figures" / f"synth_{col}_path.png").exists()
    assert "합성(simulated)" in (case / "synth_report.md").read_text(encoding="utf-8")
