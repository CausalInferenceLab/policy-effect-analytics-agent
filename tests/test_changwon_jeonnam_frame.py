"""창원 통합(전남·광주 보고서 프레임) 케이스: 계획↔코드 정합성, KOSIS 다차원 표 정리, 경계 재구성, 스코어카드 규칙,
산업연관 대응, 6단계 흐름. 네트워크 없이 합성 입력만 쓴다."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "cases" / "buildergarlic-changwon-jeonnam-frame"


def _load(name: str, folder: Path = CASE):
    spec = importlib.util.spec_from_file_location(
        f"cwjf_{folder.name}_{name}", folder / f"{name}.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


fetch = _load("fetch")
io = _load("io_counterpart")
score = _load("scorecard")


def _resp(rows, cols):
    """KOSIS 응답 모양(C1, C1_NM, C2, C2_NM, …, ITM_NM, PRD_DE, DT)의 DataFrame."""
    return pd.DataFrame(rows, columns=cols)


# ── 계획 ↔ 코드 ↔ 지표 레지스트리 정합성 ───────────────────────────────────────────────────────
def test_plan_matches_folder_fetch_and_indicators():
    from core.schema.plan import load_plan

    p = load_plan(CASE / "plan.yaml")
    assert p.case_id == CASE.name and not p.synthetic_data
    assert p.treatment.treat_time == fetch.TREAT_TIME == fetch.MERGE_YEAR + 1
    assert (p.time.start, p.time.end) == (fetch.START, fetch.END)
    tbls = {d.query["tblId"] for d in p.data_sources if d.adapter == "kosis"}
    assert {fetch.TABLES[k].tbl_id for k in fetch.CORE_TABLES} <= tbls
    assert len(fetch.DONOR_CITIES) == len(set(fetch.DONOR_CITIES)) == 62
    assert not set(fetch.PRE_MERGER) & set(fetch.DONOR_CITIES)
    for city in ("청주시", "공주시", "계룡시", "제주시", "서귀포시", "김해시", "밀양시", "세종시"):
        assert city not in fetch.DONOR_CITIES, city
    cfg = yaml.safe_load((CASE / "indicators.yaml").read_text(encoding="utf-8"))
    core_cols = [i["col"] for i in cfg["indicators"] if i.get("core")]
    assert core_cols == [o.col for o in p.outcomes]
    assert cfg["scoring"]["primary"] == p.primary_outcome.col == "log_employees"
    assert all(i["goal"] in ("increase", "decrease", "unknown") for i in cfg["indicators"])
    assert cfg["treat_time"] == fetch.TREAT_TIME and cfg["merge_year"] == fetch.MERGE_YEAR
    for g in ("peer_big_cities", "gyeongnam_cities"):
        assert set(cfg["groups"][g]) <= set(fetch.DONOR_CITIES), g
    # 확장 지표의 통계표 키는 TABLES 에 있어야 한다
    for i in cfg["indicators"]:
        if not i.get("core"):
            assert i["source"] in fetch.TABLES, i["col"]
    assert (CASE / "framework.md").read_text(encoding="utf-8").count("|") > 100  # 프레임 추출 문서


# ── KOSIS 다차원 표 정리 ──────────────────────────────────────────────────────────────────────
BIZ_COLS = ["C1", "C1_NM", "C2", "C2_NM", "C3", "C3_NM", "ITM_NM", "PRD_DE", "DT"]


def _biz_rows(code, name, year, total_emp, mfg_emp, total_est):
    """사업체노동실태현황(9차 표) 모양: 항목 '사업체수'·'총종사자수_계', 산업 대분류는 'C. 제조업(10~33)' 처럼 알파벳 접두어,
    소분류('식료품제조업')는 접두어 없음, 규모 '전규모'."""
    rows = []
    for ind_code, ind in (
        ("0", "전체"),
        ("C", "C. 제조업(10~33)"),
        ("C10", "식료품제조업"),
        ("J", "J. 출판영상방송통신및정보서비스업(58~63)"),
        ("K", "K. 금융및보험업(64~66)"),
        ("K66", "금융및보험관련서비스업"),
    ):
        for size_code, size in (("00", "전규모"), ("01", "1~4인"), ("02", "5~9인")):
            emp = {"0": total_emp, "C": mfg_emp, "C10": mfg_emp // 4, "J": 300, "K": 200, "K66": 50}[ind_code]
            est = {"0": total_est, "C": total_est // 5, "C10": 10, "J": 20, "K": 30, "K66": 5}[ind_code]
            f = 1.0 if size == "전규모" else 0.3
            rows.append(
                (
                    code,
                    name,
                    ind_code,
                    ind,
                    size_code,
                    size,
                    "총종사자수_계",
                    str(year),
                    str(int(emp * f)),
                )
            )
            rows.append(
                (
                    code,
                    name,
                    ind_code,
                    ind,
                    size_code,
                    size,
                    "총종사자수_남자",
                    str(year),
                    str(int(emp * f * 0.6)),
                )
            )
            rows.append(
                (
                    code,
                    name,
                    ind_code,
                    ind,
                    size_code,
                    size,
                    "사업체수",
                    str(year),
                    str(int(est * f)),
                )
            )
    return rows


def test_tidy_keeps_classification_columns_and_detects_dims():
    d = fetch.tidy(_resp(_biz_rows("48120", "경상남도 창원시", 2015, 1000, 400, 100), BIZ_COLS))
    assert {
        "region_code",
        "region",
        "item",
        "period",
        "value",
        "C2",
        "C2_NM",
        "C3",
        "C3_NM",
    } <= set(d.columns)
    dims = fetch.detect_dims(d)
    assert dims == {"industry": "C2_NM", "size": "C3_NM"}


def test_pick_dims_selects_total_rows_and_sums_over_pattern():
    d = fetch.tidy(_resp(_biz_rows("48120", "창원시", 2015, 1000, 400, 100), BIZ_COLS))
    emp = fetch.pick_dims(fetch.pick_item(d, "종사자"), fetch.MEASURES["employees"])
    assert emp["value"].tolist() == [1000]
    mfg = fetch.pick_dims(fetch.pick_item(d, "종사자"), fetch.MEASURES["employees_mfg"])
    assert mfg["value"].tolist() == [400]
    hvs = fetch.pick_dims(fetch.pick_item(d, "종사자"), fetch.MEASURES["employees_hvs"])
    assert hvs["value"].tolist() == [500]  # J 300 + K 200 (대분류만 — 소분류 K66 제외, 규모 '전규모'만)
    with pytest.raises(ValueError, match="맞는 이름이 없습니다"):
        fetch.pick_dims(
            fetch.pick_item(d, "종사자"),
            fetch.Measure("x", ("lab07",), "종사자", select={"industry": "^농업"}),
        )


def test_item_and_industry_patterns_cover_all_table_generations():
    """8차(2001~2006)·9차·10차 표의 항목·분류 이름이 같은 정규식으로 잡혀야 한다."""
    import re

    assert re.search(fetch.EMP_ITEM, "총종사자수") and re.search(fetch.EMP_ITEM, "총종사자수_계")
    assert not re.search(fetch.EMP_ITEM, "총종사자수_남자")
    for name in ("제조업(15∼37)", "C. 제조업(10~33)", "C.제조업(10~34)"):
        assert re.match(fetch.MFG_PAT, name), name
    assert not re.match(fetch.MFG_PAT, "식료품제조업")
    for name in ("전산업", "전체", "전규모", "계"):
        assert re.match(fetch.TOTAL_PAT, name), name
    for name in (
        "J. 출판영상방송통신및정보서비스업(58~63)",
        "J.정보통신업(58~63)",
        "K. 금융및보험업(64~66)",
        "M.전문 과학 및 기술 서비스업(70~73)",
    ):
        assert re.search(fetch.HVS_PAT, name), name
    assert not re.search(fetch.HVS_PAT, "금융및보험관련서비스업")
    assert re.search(fetch.MEASURES["unemployment_rate"].item, "실업률 (％)")
    assert not re.search(fetch.MEASURES["unemployment_rate"].item, "실업률(RSE)")
    assert re.search(fetch.MEASURES["employment_rate"].item, "고용률 (%)")
    assert not re.search(fetch.MEASURES["employment_rate"].item, "15~64세 고용률 (%)")


AGE_COLS = ["C1", "C1_NM", "C2", "C2_NM", "C3", "C3_NM", "ITM_NM", "PRD_DE", "DT"]


def _age_rows(code, name, year, by_age: dict[str, int]):
    rows = []
    for sex_code, sex in (("0", "계"), ("1", "남"), ("2", "여")):
        total = sum(by_age.values())
        rows.append(
            (
                code,
                name,
                sex_code,
                sex,
                "000",
                "계",
                "인구",
                str(year),
                str(total if sex == "계" else total // 2),
            )
        )
        for i, (age, v) in enumerate(by_age.items()):
            rows.append(
                (
                    code,
                    name,
                    sex_code,
                    sex,
                    f"{i:03d}",
                    age,
                    "인구",
                    str(year),
                    str(v if sex == "계" else v // 2),
                )
            )
    return rows


def test_age_measures_sum_youth_and_under65_bands():
    """주민등록연앙인구 표처럼 '80세 이상'·'85세 이상' 합계행이 세부 계급과 함께 있어도 65세 이상을 이중 계산하지 않는다
    (65세 이상 = 계 − 0~64세 합). '통합창원시' 는 창원시로 맞춘다."""
    detail = {
        "0 - 4세": 50,
        "15 - 19세": 60,
        "20 - 24세": 70,
        "25 - 29세": 80,
        "30 - 34세": 90,
        "60 - 64세": 40,
        "65 - 69세": 30,
        "70 - 74세": 20,
        "80 - 84세": 6,
        "85 - 89세": 3,
        "100세 이상": 1,
    }
    rows = _age_rows("38110", "통합창원시", 2015, detail)
    for sex_code, sex in (("0", "계"), ("1", "남"), ("2", "여")):
        for i, (k, v) in enumerate((("80세 이상", 10), ("85세 이상", 4))):
            rows.append(("38110", "통합창원시", sex_code, sex, f"9{i}0", k, "인구", "2015", str(v if sex == "계" else v // 2)))
    rows = [(*r[:6], "주민등록연앙인구", *r[7:]) for r in rows]
    d = fetch.tidy(_resp(rows, AGE_COLS))
    assert fetch.detect_dims(d) == {"sex": "C2_NM", "age": "C3_NM"}
    tot = fetch.pick_dims(fetch.pick_item(d, "인구"), fetch.MEASURES["pop_age_total"])
    youth = fetch.pick_dims(fetch.pick_item(d, "인구"), fetch.MEASURES["pop_youth"])
    under65 = fetch.pick_dims(fetch.pick_item(d, "인구"), fetch.MEASURES["pop_under65"])
    assert tot["value"].tolist() == [sum(detail.values())]
    assert youth["value"].tolist() == [70 + 80 + 90]
    assert under65["value"].tolist() == [50 + 60 + 70 + 80 + 90 + 40]
    assert fetch.city_rows(tot)["region"].tolist() == ["창원시"]


def test_pick_dims_refuses_ambiguous_untouched_dimension():
    """성별을 고르지 않으면 남·여·계가 합산돼 이중 계산되므로 멈춰야 한다."""
    d = fetch.tidy(
        _resp(_age_rows("48120", "창원시", 2015, {"20~24세": 10, "65~69세": 5}), AGE_COLS)
    )
    with pytest.raises(ValueError, match="모호"):
        fetch.pick_dims(
            fetch.pick_item(d, "인구"),
            fetch.Measure("x", ("age",), "인구", sum_over={"age": fetch.YOUTH_PAT}),
        )


def test_pick_dims_skips_select_dimension_absent_from_table():
    """2002~ 표는 성별이 항목(총종사자수_계)에 있어 'sex' 분류가 없다 — select 의 sex 조건은 건너뛴다."""
    d = fetch.tidy(_resp(_biz_rows("15118ZONE_07383811", "창원시", 2015, 1000, 400, 100), BIZ_COLS))
    emp = fetch.pick_dims(fetch.pick_item(d, fetch.EMP_ITEM), fetch.MEASURES["employees"])
    assert emp["value"].tolist() == [1000]  # 성별 분류가 없어도 전체·전규모 행 하나
    mfg = fetch.pick_dims(fetch.pick_item(d, fetch.EMP_ITEM), fetch.MEASURES["employees_mfg"])
    assert mfg["value"].tolist() == [400]  # 'C. 제조업(10~33)' 만 — 소분류 '식료품제조업' 은 제외


# ── 경계 재구성 ───────────────────────────────────────────────────────────────────────────────
def _toy(values_by_city: dict[str, float], years=(2008, 2009, 2010, 2011)):
    rows = []
    for y in years:
        for city, v in values_by_city.items():
            gone = city in ("마산시", "진해시") and y >= fetch.MERGE_YEAR
            rows.append((city, y, np.nan if gone else v))
    return pd.DataFrame(rows, columns=["region", "year", "value"])


def test_reconstruct_sums_before_merger_and_weighted_mean_for_rates():
    d = _toy({"마산시": 1.0, "진해시": 2.0, "창원시": 4.0, "진주시": 9.0, "청주시": 99.0})
    out = fetch.reconstruct(d, "sum").set_index(["region", "year"])["value"]
    assert out["창원시", 2009] == 7.0 and out["창원시", 2011] == 4.0 and out["진주시", 2008] == 9.0
    assert fetch.MERGE_YEAR not in out.index.get_level_values("year")
    assert "청주시" not in out.index.get_level_values("region")
    fis = _toy({"마산시": 20.0, "창원시": 60.0, "진해시": 40.0, "진주시": 30.0})
    pop = _toy({"마산시": 1.0, "창원시": 1.0, "진해시": 2.0, "진주시": 5.0})
    w = fetch.reconstruct(fis, "wmean", weights=pop).set_index(["region", "year"])["value"]
    assert w["창원시", 2009] == pytest.approx((20 + 60 + 80) / 4) and w["창원시", 2011] == 60.0
    with pytest.raises(ValueError, match="진해시"):
        fetch.reconstruct(_toy({"마산시": 1.0, "창원시": 4.0, "진주시": 9.0}), "sum")


def test_city_rows_treats_zero_filled_defunct_codes_as_missing_and_matches_by_name():
    long = pd.DataFrame(
        [
            ("48160", "마산시", "종사자수", "2011", 0),  # 폐지 코드: KOSIS 가 '-' 대신 0 으로 채움
            ("48120", "경상남도 창원시", "종사자수", "2011", 400000),
            ("48121", "의창구", "종사자수", "2011", 90000),  # 일반구 → 제외
            ("1236010", "전라남도 목포시", "재정자립도(세입과목개편전)", "2011", 25.3),
            ("48", "경상남도", "종사자수", "2011", 1),
            ("3803", "진주시", "고용률 (%)", "201302", 63.2),  # 지역별고용조사 4자리 코드·반기 시점
            ("15118ZONE_07383805", "통영시", "사업체수", "2009", 3000),  # 사업체노동실태현황 코드
            ("3099", "경기도", "고용률 (%)", "201302", 60.0),  # 시도 행 → 제외
        ],
        columns=["region_code", "region", "item", "period", "value"],
    )
    d = fetch.city_rows(long).set_index("region")
    assert set(d.index) == {"마산시", "창원시", "목포시", "진주시", "통영시"}
    assert (
        np.isnan(d.loc["마산시", "value"])
        and d.loc["창원시", "value"] == 400000
        and d.loc["목포시", "value"] == 25.3
    )
    assert d.loc["진주시", "year"] == 2013 and d.loc["통영시", "year"] == 2009


def _biz_long(years, cities, with_prefix=False):
    rows = []
    for i, c in enumerate(cities):
        code = f"{10000 + i * 10:05d}"
        for y in years:
            gone = c in ("마산시", "진해시") and y >= fetch.MERGE_YEAR
            if gone:
                rows += [(code, c, "0", "전체", "00", "전규모", "총종사자수_계", str(y), "0"),
                         (code, c, "0", "전체", "00", "전규모", "사업체수", str(y), "0"),
                         (code, c, "C", "C. 제조업(10~33)", "00", "전규모", "총종사자수_계", str(y), "0")]  # fmt: skip
            else:
                rows += _biz_rows(
                    code,
                    (f"어느도 {c}" if with_prefix else c),
                    y,
                    10_000 + 100 * i + y,
                    3_000 + 10 * i,
                    2_000 + i,
                )
    return fetch.tidy(_resp(rows, BIZ_COLS))


def test_build_measure_concatenates_tables_and_prefers_latest_on_overlap():
    cities = (*fetch.PRE_MERGER, "진주시")
    raw = {
        "lab04": _biz_long(range(2001, 2006), cities),
        "lab07": _biz_long(range(2005, 2012), cities, True),
    }
    out = fetch.build_measure(fetch.MEASURES["employees"], raw).set_index(["region", "year"])[
        "value"
    ]
    i_m, i_c, i_j = (cities.index(x) for x in fetch.PRE_MERGER)
    assert out["창원시", 2003] == sum(10_000 + 100 * k + 2003 for k in (i_m, i_c, i_j))
    assert out["창원시", 2011] == 10_000 + 100 * i_c + 2011
    assert out["진주시", 2005] == 10_000 + 100 * 3 + 2005  # 겹치는 2005 는 뒤 표 값(같은 값)
    assert 2010 not in out.index.get_level_values("year")


def test_finalize_core_builds_balanced_panel_with_shares():
    years = (*fetch.YEARS, fetch.MERGE_YEAR)
    cities = (*fetch.DONOR_CITIES, *fetch.PRE_MERGER)
    biz = _biz_long(years, cities)
    pop_rows, fis_rows = [], []
    for i, c in enumerate(cities):
        code = f"{10000 + i * 10:05d}"
        for y in years:
            gone = c in ("마산시", "진해시") and y >= fetch.MERGE_YEAR
            pop_rows.append((code, c, "총인구수", str(y), "0" if gone else str(100_000 + i)))
            fis_rows.append(
                (code, c, "재정자립도(세입과목개편전)", str(y), "0" if gone else "30.0")
            )
            if y >= 2014:
                fis_rows.append(
                    (code, c, "재정자립도(세입과목개편후)", str(y), "0" if gone else "45.0")
                )
    raw = {
        "pop": pd.DataFrame(pop_rows, columns=["region_code", "region", "item", "period", "value"]),
        "lab04": biz[biz["period"].astype(int) <= 2006], "lab07": biz[biz["period"].astype(int).between(2007, 2016)],
        "lab17": biz[biz["period"].astype(int) >= 2017],
        "fiscal": pd.DataFrame(fis_rows, columns=["region_code", "region", "item", "period", "value"]),
    }  # fmt: skip
    pop_city = fetch.city_measure(fetch.MEASURES["population"], raw)
    pop = fetch.reconstruct(pop_city, "sum")
    parts = {
        n: (
            pop
            if n == "population"
            else fetch.build_measure(fetch.MEASURES[n], raw, population=pop_city)
        )
        for n in fetch.CORE_MEASURES
    }
    panel = fetch.finalize_core(parts)
    assert len(panel) == len(fetch.UNITS) * len(fetch.YEARS) and panel["treated"].sum() == len(
        fetch.YEARS
    )
    cw = panel[panel["region_id"] == "창원시"].set_index("year")
    i_m, i_c, i_j = (cities.index(x) for x in fetch.PRE_MERGER)
    assert cw.loc[2009, "employees"] == sum(10_000 + 100 * k + 2009 for k in (i_m, i_c, i_j))
    assert cw.loc[2009, "employees_mfg"] == sum(3_000 + 10 * k for k in (i_m, i_c, i_j))
    assert cw.loc[2009, "manufacturing_emp_share"] == pytest.approx(
        cw.loc[2009, "employees_mfg"] / cw.loc[2009, "employees"] * 100
    )
    assert panel["fiscal_independence"].eq(30.0).all()  # 개편전 계열
    assert np.allclose(panel["log_employees"], np.log(panel["employees"]))
    # 결측은 채우지 않고 멈춘다
    bad = {k: v.copy() for k, v in parts.items()}
    bad["employees"] = bad["employees"][
        ~((bad["employees"]["region"] == "진주시") & (bad["employees"]["year"] == 2015))
    ]
    with pytest.raises(ValueError, match="결측"):
        fetch.finalize_core(bad)


def test_finalize_extended_computes_ratio_indicators_and_allows_gaps():
    rows = []
    for c in ("창원시", "진주시"):
        for y in (2011, 2012):
            rows.append((c, y))
    base = pd.DataFrame(rows, columns=["region", "year"])
    parts = {
        "pop_age_total": base.assign(value=1000.0), "pop_youth": base.assign(value=200.0), "pop_under65": base.assign(value=850.0),
        "mig_youth_in": base.assign(value=30.0), "mig_youth_out": base.assign(value=50.0),
        "employment_rate": base[base["year"] == 2012].assign(value=60.0),
    }  # fmt: skip
    ext = fetch.finalize_extended(parts)
    assert ext["youth_share"].eq(20.0).all() and ext["elderly_share"].eq(15.0).all()
    assert ext["youth_net_migration_rate"].eq(-100.0).all()
    assert ext["employment_rate"].isna().sum() == 2  # 2011 은 없음 — 결측 허용


def test_simulated_panels_are_balanced_single_treated():
    core, ext = fetch.simulate()
    assert core.groupby("region_id")["year"].nunique().nunique() == 1
    assert core.loc[
        core["treated"] == 1, "region_id"
    ].nunique() == 1 and fetch.MERGE_YEAR not in set(core["year"])
    assert set(ext["year"]) == {y for y in fetch.YEARS if y >= 2008}


# ── 산업연관 대응 ─────────────────────────────────────────────────────────────────────────────
def test_leontief_and_employment_effect_on_two_sector_table():
    A = np.array([[0.2, 0.3], [0.1, 0.4]])
    L = io.leontief_inverse(A)
    assert np.allclose(L @ (np.eye(2) - A), np.eye(2))
    y = np.array([100.0, 0.0])
    x = io.production_effect(A, y)
    assert np.allclose((np.eye(2) - A) @ x, y) and (x >= y).all()
    assert np.allclose(
        io.employment_effect(A, y, np.array([0.01, 0.02])), np.array([0.01, 0.02]) * x
    )
    with pytest.raises(ValueError):
        io.leontief_inverse(np.array([[0.6, 0.0], [0.5, 0.2]]))  # 열 합 ≥ 1


def test_report_multipliers_and_scale_comparison():
    m = io.implied_multipliers()
    assert m["production_national"] == pytest.approx(1.80) and m[
        "production_region"
    ] == pytest.approx(0.85)
    assert m["jobs_per_bn_national"] == pytest.approx(8.8) and m[
        "jobs_per_bn_region"
    ] == pytest.approx(4.6)
    assert m["region_retention_share"] == pytest.approx(17 / 36)
    r = io.expected_effects(1460, 10, baseline_employees=400_000, baseline_population=1_080_000)
    assert r["jobs_per_year"]["region"] == pytest.approx(14.6 * 4.6)
    assert r["production_total_bn_krw"]["region"] == pytest.approx(1460 * 0.85)
    assert r["jobs_region_share_of_baseline_pct"] < 0.1  # 창원 종사자의 0.1% 미만
    assert r["scale_vs_report"]["ratio_changwon_to_report"] < 0.02
    assert io.split_8_1_1(20)["핵심산업"] == 16


# ── 스코어카드 규칙 ─────────────────────────────────────────────────────────────────────────────
def _res(est, lo, hi, verdict="conditional"):
    from core.estimators.result import EffectResult

    return EffectResult("event_study", "x", est, 0.1, lo, hi, 0.5, 100, 63, verdict=verdict)


def test_classify_follows_preregistered_rule():
    assert score.classify(_res(0.05, 0.01, 0.09), "increase")[0] == "success"
    assert score.classify(_res(0.05, 0.01, 0.09), "decrease")[0] == "failure"
    assert score.classify(_res(0.05, -0.01, 0.09), "increase")[0] == "undetermined"
    assert score.classify(_res(0.05, 0.01, 0.09), "unknown")[0] == "undetermined"
    assert score.classify(_res(0.05, 0.01, 0.09, "not_identified"), "increase")[0] == "undetermined"


def test_overall_rules():
    sc = {"primary": "log_employees", "min_decidable": 3}

    def rows(*classes):
        cols = ["log_employees", "b", "c", "d"]
        return [{"col": c, "class": k} for c, k in zip(cols, classes, strict=False)]

    assert (
        score.overall(rows("success", "success", "undetermined", "undetermined"), sc)[0]
        == "success"
    )
    assert (
        score.overall(rows("failure", "undetermined", "undetermined", "undetermined"), sc)[0]
        == "failure"
    )
    assert (
        score.overall(rows("success", "failure", "undetermined", "undetermined"), sc)[0] == "mixed"
    )
    assert (
        score.overall(rows("undetermined", "undetermined", "undetermined", "undetermined"), sc)[0]
        == "undetermined"
    )
    assert (
        score.overall(rows("undetermined", "success", "success", "success"), sc)[0]
        == "undetermined"
    )  # 1차 지표가 안 갈림
    assert (
        score.overall(rows("success", "no_data", "no_data", "no_data"), sc)[0] == "undetermined"
    )  # 판정 가능 지표 부족


def _case_copy(tmp_path: Path) -> Path:
    dst = tmp_path / "cases" / CASE.name
    dst.mkdir(parents=True)
    for f in (
        "plan.yaml",
        "indicators.yaml",
        "fetch.py",
        "scorecard.py",
        "io_counterpart.py",
        "discussion.md",
    ):
        shutil.copy(CASE / f, dst / f)
    return dst


def test_scorecard_runs_on_simulated_panels(tmp_path):
    dst = _case_copy(tmp_path)
    f = _load("fetch", dst)
    core, ext = f.simulate()
    f.write(core, ext, {"synthetic_data": True, "license": "synthetic"})
    s = _load("scorecard", dst)
    res = s.run(n_perm=29, make_figs=True)
    assert res["synthetic_data"] and len(res["indicators"]) == 12
    assert all(
        x["class"] in ("success", "failure", "undetermined") for x in res["indicators"]
    )  # 합성에서는 모두 추정됨
    assert res["overall"]["verdict"] in ("success", "failure", "mixed", "undetermined")
    assert (dst / "scorecard.md").exists() and (dst / "scorecard.json").exists()
    assert (dst / "figures" / "scorecard_forest.png").exists() and (
        dst / "figures" / "benchmark_log_employees.png"
    ).exists()
    md = (dst / "scorecard.md").read_text(encoding="utf-8")
    assert "합성 데이터" in md and "산업연관분석 대응" in md
    ys = next(x for x in res["indicators"] if x["col"] == "youth_share")
    assert ys["n_pre"] == 2 and "short_pre_period" in ys["triggers"]  # 2008~2009 만 사전 → 조건부
    assert ys["benchmark"]["all_donors"]["n"] == 62


def test_flow_runs_end_to_end_on_simulated_panel(tmp_path):
    from core.agent import run_flow

    dst = _case_copy(tmp_path)
    f = _load("fetch", dst)
    core, ext = f.simulate()
    f.write(core, ext, {"synthetic_data": True, "license": "synthetic"})
    state = run_flow(dst, allow_uncommitted=True)
    assert state.status in ("ok", "warn"), [s.message for s in state.steps]
    assert {r.outcome for r in state.results} == {
        "log_employees",
        "log_establishments",
        "manufacturing_emp_share",
        "fiscal_independence",
    }
    assert all("few_treated_clusters" in r.triggers for r in state.results)
    assert (dst / "report.md").exists() and (dst / "figures" / "event_study.png").exists()
