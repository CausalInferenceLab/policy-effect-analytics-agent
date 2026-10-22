"""② 수집 — KOSIS OpenAPI 로 한국은행 전남·광주 보고서의 지표 세트를 받아 '통합 경계로 재구성한 기초 시 × 연도' 패널을 만듭니다.

    python fetch.py                    # KOSIS_API_KEY 필요(.env, 무료). data/panel.csv(핵심 4지표) + data/extended.csv(확장 지표)
    python fetch.py --simulate         # 키 없이 파이프라인만 점검하는 합성 패널 — 실데이터 아님, 결과 해석 금지
    python fetch.py --discover 사업체수  # KOSIS 통계표 검색으로 통계표 ID 후보를 보여줌
    python fetch.py --probe            # TABLES 의 각 통계표: 메타정보(분류·항목·수록기간)로 존재·구조를 확인(키 필요, 자료 호출 없음)
    python fetch.py --only core        # 핵심 4지표만 (확장 지표 통계표가 아직 확인되지 않았을 때)

핵심 패널(data/panel.csv, plan.yaml 이 쓰는 열): region_id, year, treated, employees, establishments, employees_mfg,
  population, log_employees, log_establishments, manufacturing_emp_share, fiscal_independence — 2001~2023(2010 제외) 균형 패널.
확장 패널(data/extended.csv, indicators.yaml 이 쓰는 열): 지표마다 수록 기간이 달라 결측을 허용한다. scorecard.py 가
  지표별로 균형 구간을 잘라 쓴다. 후보 통계표 수집이 실패하면 그 지표 열은 만들지 않고 source.json 에 사유를 남긴다.

통계표(실수집 2026-10-22 에 확정 — 계획의 후보 ID 에서 바뀐 것은 plan.yaml 머리글과 discussion.md 에 적음)
- 사업체수·종사자수·제조업 종사자수: KOSIS 에 올라온 전국사업체조사 통계표(DT_1K52*)는 모두 시도 단위라(OpenAPI 로 시군구 행이
  없음) 고용노동부 「사업체노동실태현황」의 시군구별(9개도)·산업별·규모별 표(DT_SAUP120, DT_118N_SAUP17/37/57/78, SAUPN78 —
  산재보험 적용 사업체 기준, 1999~) 를 2001~2023 으로 이어 붙인다. 산업분류 개정(8차→9차 2007, 9차→10차 2017)은 표가 나뉘어
  있어 각 표의 '전산업/전체'·'제조업' 행을 쓴다.
- 재정자립도·재정자주도: e-지방지표(DT_1YL20921, DT_1YL20891), 주민등록인구: DT_1B040A3 — PR #35 실수집으로 확인.
- 연령별 인구: 시군구/성/연령(5세)별 주민등록연앙인구(DT_1B040M5 1993~2022, DT_1B040M5_1 2023~) — 계획의 DT_1B04005N(2011~)
  보다 사전 기간이 길다. 청년 이동: 시군구/성/연령(5세)별 이동자수(DT_1B26001, 1970~).
- 고용률·실업률: 지역별고용조사 시군구 경제활동인구 총괄 — 2008~2010 연간(DT_1ES1A01S), 2010.4/4~2012.4/4 분기(DT_1ES2A01S,
  4분기만), 2013~ 반기(DT_1ES3A01S, 하반기만).
- 공무원 1인당 주민수: 시군구별 공무원 현원 표(DT_110027_001, 행안부)가 2015 년부터라 통합 전 자료가 없어 수집하지 않는다.

행정경계 변경 처리(PR #35 케이스와 같은 규칙)
- 통합 전(≤2009) 마산시·창원시·진해시 값을 합산해 통합 창원시와 같은 경계로 맞춘다. 개수(종사자·사업체·인구)는 합계,
  비율은 분자·분모를 합산한 뒤 다시 계산하고, 표에서 비율로만 주는 지표(재정자립도·고용률 등)는 인구 가중 평균(근사).
- 2010년은 7월에 통합된 전환연도라 모든 단위에서 제외한다(균형 패널 유지).
- 2001~2023 사이 통합·분리·승격이 있었던 시와 창원에 접한 김해·밀양은 대조군에서 뺀다(DONOR_CITIES).
- KOSIS 는 폐지된 시군구 코드를 남기고 폐지 후 연도를 0 으로 채운다 → city_rows 가 0 을 결측으로 본다.
- 통계표마다 지역 코드 체계가 다르다(48120 / 38110 / 3811 / 15118ZONE_07383801 …) → 지역은 코드가 아니라 이름(마지막 어절)으로
  맞추고, 통합 전 3개 시와 대조군 62개 시만 남긴다(일반구·시도 행은 이름이 달라 자연히 빠진다).

주의: data/ 아래 파일은 git 에 올라가지 않는다. KOSIS 가공본은 재배포하지 않고 각자 받는다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from core.adapters.base import MissingAPIKey  # noqa: E402
from core.adapters.kosis import URL as KOSIS_URL  # noqa: E402
from core.adapters.kosis import KosisAdapter  # noqa: E402

META_URL = "https://kosis.kr/openapi/statisticsData.do"  # getMeta: 통계표의 항목·분류 코드·수록 기간
OUT = HERE / "data" / "panel.csv"
EXT = HERE / "data" / "extended.csv"
RAW = HERE / "data" / "raw"

START, END = 2001, 2023
MERGE_YEAR = 2010  # 2010-07-01 통합 → 반년만 통합된 전환연도, 패널에서 제외
TREAT_TIME = 2011  # 첫 완전 사후연도 (plan.yaml treatment.treat_time 과 같아야 함)
MERGED = "창원시"
PRE_MERGER = ("마산시", "창원시", "진해시")  # 통합 전 3개 시 → 합산
NAME_FIX = {"통합창원시": "창원시"}  # 표에 따라 통합 뒤 이름이 다름 ('통합 창원시'는 마지막 어절 규칙으로 처리)

# 대조군: 2001~2023 사이 행정구역 통합·분리·승격이 없었던 기초 시 62곳 (PR #35 케이스와 같은 목록).
DONOR_CITIES = (
    # 경기 23
    "수원시", "성남시", "의정부시", "안양시", "부천시", "광명시", "평택시", "동두천시", "안산시",
    "고양시", "과천시", "구리시", "남양주시", "오산시", "시흥시", "군포시", "의왕시", "하남시",
    "용인시", "파주시", "이천시", "안성시", "김포시",
    # 강원 7
    "춘천시", "원주시", "강릉시", "동해시", "태백시", "속초시", "삼척시",
    # 충북 2 · 충남 4
    "충주시", "제천시", "천안시", "보령시", "아산시", "서산시",
    # 전북 6 · 전남 5
    "전주시", "군산시", "익산시", "정읍시", "남원시", "김제시",
    "목포시", "여수시", "순천시", "나주시", "광양시",
    # 경북 10 · 경남 5
    "포항시", "경주시", "김천시", "안동시", "구미시", "영주시", "영천시", "상주시", "문경시", "경산시",
    "진주시", "통영시", "사천시", "거제시", "양산시",
)  # fmt: skip

YEARS = tuple(y for y in range(START, END + 1) if y != MERGE_YEAR)
UNITS = (MERGED, *DONOR_CITIES)

TOTAL_PAT = r"^(전\s*산업|전체\s*산업|전체|전\s*규모|합계|총계|계|소계|전국|전\s*체)$"  # 분류의 '전체' 행 이름
MFG_PAT = r"^(?:[A-Z]\.?\s*)?제조업"  # '제조업(15∼37)', 'C. 제조업(10~33)', 'C.제조업(10~34)'
HVS_PAT = r"^[JKM]\.\s*"  # 9차·10차 대분류 J(출판·정보통신) K(금융·보험) M(전문·과학·기술) — 소분류는 알파벳 접두어가 없다
YOUTH_PAT = r"^(?:20|25|30)\s*[~∼-]"  # 5세 계급 20~24·25~29·30~34
UNDER65_PAT = r"^(?:\d|[1-5]\d|60)\s*[~∼-]"  # 0~4 … 60~64 (65세 이상 = 계 − 이 합계; 표마다 80+·85+ 합계행이 섞여 있어 빼서 구함)


# ── 통계표 레지스트리 ──────────────────────────────────────────────────────────────────────────
@dataclass
class Table:
    key: str
    tbl_id: str
    name: str
    years: tuple[int, int]
    status: str = "candidate"  # verified(실수집으로 확인) | candidate(ID 후보 — --probe 로 확인) | unavailable(쓸 수 없음)
    org_id: str = "101"
    itm_id: str = "ALL"
    chunk: int = 6  # 한 호출의 연도 수 (KOSIS 셀 수 제한 4만)
    levels: int | None = None  # objL1~objLn 의 개수 — None 이면 메타정보에서 알아낸다 (표마다 달라 틀리면 err 20/21)
    prd_se: str = "Y"  # Y(년) | H(반기) | Q(분기)
    period_keep: str | None = None  # PRD_DE 정규식 — 예: 반기 표에서 하반기만 '02$'
    note: str = ""


LAB_COMMON = "시군구별(9개도)·산업별·규모별 사업체수 및 종사자수 — 사업체노동실태현황(고용노동부)"
# 핵심 통계표(plan.yaml data_sources 와 같아야 함 — 테스트가 확인) + 확장 지표 통계표.
TABLES: dict[str, Table] = {
    "pop": Table("pop", "DT_1B040A3", "행정구역(시군구)별 성별 인구수(주민등록)", (2001, 2023), "verified", itm_id="T20", levels=1),
    "lab01": Table("lab01", "DT_SAUP120", f"시도별·시군구별 사업체수 및 종사자수(1999~2001) — {LAB_COMMON}", (2001, 2001), "verified",
                   org_id="118", levels=4, chunk=1, note="성별이 분류(C2)에 있고 항목은 사업체수·총종사자수. 산업분류 8차"),
    "lab02": Table("lab02", "DT_118N_SAUP17", f"{LAB_COMMON} (2002~2003, 산업분류 8차)", (2002, 2003), "verified", org_id="118", levels=3),
    "lab04": Table("lab04", "DT_118N_SAUP37", f"{LAB_COMMON} (2004~2006, 산업분류 8차)", (2004, 2006), "verified", org_id="118", levels=3),
    "lab07": Table("lab07", "DT_118N_SAUP57", f"{LAB_COMMON} (2007~2011, 산업분류 9차)", (2007, 2011), "verified", org_id="118", levels=3,
                   note="2010 부터 '창원시' 행이 통합 경계(마산·진해 행은 결측)"),
    "lab12": Table("lab12", "DT_118N_SAUP78", f"{LAB_COMMON} (2012~2016, 산업분류 9차)", (2012, 2016), "verified", org_id="118", levels=3),
    "lab17": Table("lab17", "DT_118N_SAUPN78", f"{LAB_COMMON} (2017~2023, 산업분류 10차)", (2017, 2023), "verified", org_id="118", levels=3),
    "fiscal": Table("fiscal", "DT_1YL20921", "재정자립도(시도/시/군/구) e-지방지표", (2001, 2023), "verified", levels=1),
    # 확장 지표
    "age": Table("age", "DT_1B040M5", "시군구/성/연령(5세)별 주민등록연앙인구(1993~2022)", (2001, 2022), "verified", levels=3, chunk=4,
                 note="통합 뒤 이름이 '통합창원시'(38110) → NAME_FIX. 80세 이상·85세 이상 합계행이 세부 계급과 함께 있음"),
    "age_new": Table("age_new", "DT_1B040M5_1", "시군구/성/연령(5세)별 주민등록연앙인구(2023~)", (2023, 2023), "verified", levels=3, chunk=1),
    "mig_age": Table("mig_age", "DT_1B26001", "시군구/성/연령(5세)별 이동자수(국내인구이동통계)", (2001, 2023), "verified", levels=3, chunk=3,
                     note="항목 총전입·총전출·순이동 등 8개. 폐지 코드(48110·48160·48190)는 폐지 후 0"),
    "fiscal_autonomy": Table("fiscal_autonomy", "DT_1YL20891", "재정자주도(시도/시/군/구) e-지방지표", (2001, 2023), "verified", levels=1),
    "emp08": Table("emp08", "DT_1ES1A01S", "시군(9개도)별 경제활동인구 총괄 — 지역별고용조사 2008~2010(연간)", (2008, 2010), "verified",
                   levels=1, note="4자리 지역코드(3801 창원, 3802 마산, 3804 진해, 3811 통합 창원시)"),
    "emp10": Table("emp10", "DT_1ES2A01S", "시군(9개도)별 경제활동인구 총괄 — 지역별고용조사 2010.4/4~2012.4/4(분기)", (2011, 2012),
                   "verified", levels=1, chunk=2, prd_se="Q", period_keep=r"04$", note="4분기(10월) 값만 씀"),
    "emp13": Table("emp13", "DT_1ES3A01S", "시군구 경제활동인구 총괄 — 지역별고용조사 2013~(반기)", (2013, 2023), "verified",
                   levels=1, chunk=3, prd_se="H", period_keep=r"02$", note="하반기(10월) 값만 씀"),
    "civil_servants": Table("civil_servants", "DT_110027_001", "시군구별 총괄 현원 — 지방자치단체공무원인사통계(행안부)", (2015, 2023),
                            "unavailable", org_id="110", levels=2,
                            note="시군구별 공무원 현원은 2015년부터 수록 — 통합 전(≤2009) 자료가 없어 사전추세·효과를 추정할 수 없으므로 수집하지 않음. "
                                 "e-지방지표에는 시도 단위 '공무원 1인당 주민수'(경찰·소방)만 있음"),
}  # fmt: skip
LAB_TABLES = ("lab01", "lab02", "lab04", "lab07", "lab12", "lab17")
CORE_TABLES = ("pop", *LAB_TABLES, "fiscal")


# ── 측정치 정의: 통계표 → (region, year, value) ──────────────────────────────────────────────────
@dataclass
class Measure:
    name: str
    tables: tuple[str, ...]  # TABLES 키 (여러 표면 연도별로 이어 붙임)
    item: str  # ITM_NM 정규식
    item_exclude: str | None = None
    select: dict[str, str] = field(default_factory=dict)  # 분류 종류 → 한 행을 고르는 이름 정규식 (표에 그 분류가 없으면 건너뜀)
    sum_over: dict[str, str] = field(
        default_factory=dict
    )  # 분류 종류 → 여러 행을 합산하는 이름 정규식
    how: str = "sum"  # 통합 전 3개 시 처리: sum | wmean(인구 가중)


EMP_ITEM = r"^총종사자수(_계)?$"  # 1999~2001 표는 '총종사자수'(성별이 분류), 2002~ 표는 '총종사자수_계/_남자/_여자'
LAB_TOTAL = {"industry": TOTAL_PAT, "size": TOTAL_PAT, "sex": TOTAL_PAT}
LAB_9TH = ("lab07", "lab12", "lab17")  # 9차·10차 산업분류 표 (대분류 J·K·M 이 있음)
AGE_TABLES = ("age", "age_new")
EMP_TABLES = ("emp08", "emp10", "emp13")
MEASURES: dict[str, Measure] = {
    "population": Measure("population", ("pop",), r"총인구|인구"),
    "employees": Measure("employees", LAB_TABLES, EMP_ITEM, select=LAB_TOTAL),
    "establishments": Measure("establishments", LAB_TABLES, r"^사업체수$", select=LAB_TOTAL),
    "employees_mfg": Measure("employees_mfg", LAB_TABLES, EMP_ITEM, select={**LAB_TOTAL, "industry": MFG_PAT}),
    "fiscal_independence": Measure("fiscal_independence", ("fiscal",), r"재정자립도", item_exclude="개편후", how="wmean"),
    # 확장
    "employees_hvs": Measure("employees_hvs", LAB_9TH, EMP_ITEM, select={"size": TOTAL_PAT}, sum_over={"industry": HVS_PAT}),
    "employees_from2007": Measure("employees_from2007", LAB_9TH, EMP_ITEM, select=LAB_TOTAL),
    "pop_age_total": Measure("pop_age_total", AGE_TABLES, r"연앙인구|인구|계|총", select={"sex": TOTAL_PAT, "age": TOTAL_PAT}),
    "pop_youth": Measure("pop_youth", AGE_TABLES, r"연앙인구|인구|계|총", select={"sex": TOTAL_PAT}, sum_over={"age": YOUTH_PAT}),
    "pop_under65": Measure("pop_under65", AGE_TABLES, r"연앙인구|인구|계|총", select={"sex": TOTAL_PAT}, sum_over={"age": UNDER65_PAT}),
    "mig_youth_in": Measure("mig_youth_in", ("mig_age",), r"^총전입", select={"sex": TOTAL_PAT}, sum_over={"age": YOUTH_PAT}),
    "mig_youth_out": Measure("mig_youth_out", ("mig_age",), r"^총전출", select={"sex": TOTAL_PAT}, sum_over={"age": YOUTH_PAT}),
    "fiscal_autonomy": Measure("fiscal_autonomy", ("fiscal_autonomy",), r"재정자주도", item_exclude="개편후", how="wmean"),
    "employment_rate": Measure("employment_rate", EMP_TABLES, r"^고용률", how="wmean"),
    "unemployment_rate": Measure("unemployment_rate", EMP_TABLES, r"^실업률\s*\(\s*[%％]", how="wmean"),
    "civil_servants": Measure("civil_servants", ("civil_servants",), r"현원", select={"sex": TOTAL_PAT}),
}  # fmt: skip

CORE_MEASURES = (
    "population",
    "employees",
    "establishments",
    "employees_mfg",
    "fiscal_independence",
)
# 확장 지표 열 ← 필요한 측정치 (source.json 에 지표별 수집 실패 사유를 남기기 위한 대응표)
INDICATOR_NEEDS = {
    "youth_share": ("pop_youth", "pop_age_total"),
    "elderly_share": ("pop_under65", "pop_age_total"),
    "youth_net_migration_rate": ("mig_youth_in", "mig_youth_out", "pop_youth"),
    "fiscal_autonomy": ("fiscal_autonomy",),
    "employment_rate": ("employment_rate",),
    "unemployment_rate": ("unemployment_rate",),
    "high_value_service_share": ("employees_hvs", "employees_from2007"),
    "residents_per_civil_servant": ("civil_servants",),
}

# 분류 종류를 이름 패턴으로 알아본다 (KOSIS 응답의 C2_NM, C3_NM … 가운데 어느 열이 산업·규모·성·연령인지)
DIM_HINTS = {
    "industry": r"제조업|농업|도매|서비스|광업",
    "size": r"\d+\s*[~∼-]\s*\d+\s*(인|명)|인\s*이상|인\s*미만|종사자규모|사업체구분|개인|회사법인|전\s*규모",
    "sex": r"^(남|여|남자|여자|남성|여성)$",
    "age": r"\d+\s*[~∼-]\s*\d+\s*세|세\s*이상|세\s*미만",
}


# ── 순수 함수 (테스트 대상) ───────────────────────────────────────────────────────────────────
def tidy(raw: pd.DataFrame) -> pd.DataFrame:
    """KOSIS 응답 → region_code, region, item, period, value + 분류열(C2_NM…)을 그대로 둔 롱포맷."""
    d = raw.rename(
        columns={
            "C1": "region_code",
            "C1_NM": "region",
            "ITM_NM": "item",
            "PRD_DE": "period",
            "DT": "value",
        }
    )
    keep = ["region_code", "region", "item", "period", "value"] + sorted(
        c for c in d.columns if re.fullmatch(r"C[2-8](_NM)?", c)
    )
    d = d[[c for c in keep if c in d.columns]].copy()
    d["value"] = pd.to_numeric(d["value"], errors="coerce")  # '-', 'X' → NaN
    return d


def detect_dims(d: pd.DataFrame) -> dict[str, str]:
    """분류열(C2_NM, C3_NM …) 가운데 어느 열이 어떤 종류(industry/size/sex/age)인지 이름으로 알아본다."""
    out = {}
    for col in [c for c in d.columns if re.fullmatch(r"C[2-8]_NM", c)]:
        names = d[col].dropna().astype(str).unique()
        for kind, pat in DIM_HINTS.items():
            if kind not in out and any(re.search(pat, n) for n in names):
                out[kind] = col
                break
    return out


def pick_dims(d: pd.DataFrame, m: Measure) -> pd.DataFrame:
    """select 로 한 행을 고르고 sum_over 로 여러 행을 합산해 (region_code, region, item, period, value)만 남긴다.
    select 의 분류가 표에 없으면(예: 성별이 항목에 들어 있는 표) 그 조건은 건너뛴다. sum_over 의 분류는 있어야 한다."""
    dims = detect_dims(d)
    x = d
    for kind, pat in m.select.items():
        col = dims.get(kind)
        if col is None:
            continue
        hit = x[col].astype(str).str.strip().str.match(pat)
        if not hit.any():
            raise ValueError(
                f"{m.name}: 분류 '{kind}' 에 '{pat}' 와 맞는 이름이 없습니다. 예: {sorted(x[col].astype(str).unique())[:12]}"
            )
        x = x[hit]
    for kind, pat in m.sum_over.items():
        col = dims.get(kind)
        if col is None:
            raise ValueError(f"{m.name}: 분류 '{kind}' 열을 찾지 못했습니다. 있는 분류열: {dims}")
        hit = x[col].astype(str).str.strip().str.contains(pat, regex=True)
        if not hit.any():
            raise ValueError(
                f"{m.name}: 분류 '{kind}' 에 '{pat}' 와 맞는 이름이 없습니다. 예: {sorted(x[col].astype(str).unique())[:12]}"
            )
        x = x[hit]
    # 고르지 않은 분류가 남아 있으면 (예: 성별 열이 없는 표) 그대로 두고, 합산 대상 분류만 더한다
    keys = ["region_code", "region", "item", "period"]
    other = [dims[k] for k in dims if k not in m.select and k not in m.sum_over]
    if other:  # 손대지 않은 분류가 둘 이상의 값을 가지면 이중 계산이므로 멈춘다
        for col in other:
            if x[col].nunique() > 1:
                raise ValueError(
                    f"{m.name}: 분류 '{col}' 가 {x[col].nunique()}개 값이라 합산 기준이 모호합니다: {sorted(x[col].unique())[:8]}"
                )
    return x.groupby(keys, as_index=False)["value"].sum(min_count=1)


def pick_item(d: pd.DataFrame, pattern: str, exclude: str | None = None) -> pd.DataFrame:
    """항목 이름이 pattern 과 맞는 행. 후보가 여럿이면 이름이 가장 짧은 항목 하나."""
    items = [i for i in d["item"].astype(str).unique() if re.search(pattern, i)]
    if exclude:
        items = [i for i in items if exclude not in i] or items
    if not items:
        raise ValueError(
            f"'{pattern}' 항목이 없습니다. 있는 항목: {sorted(d['item'].astype(str).unique())}"
        )
    chosen = min(items, key=len)
    return d[d["item"] == chosen].copy()


def city_name(s: str) -> str:
    """'경남 창원시'·'전라남도 목포시'·'통합 창원시' → 마지막 어절, '통합창원시' → NAME_FIX."""
    s = str(s).strip()
    s = NAME_FIX.get(s, s)
    return s.split()[-1] if s else s


def city_rows(long: pd.DataFrame) -> pd.DataFrame:
    """통합 전 3개 시와 대조군 시 행만 남긴다. 지역 코드 체계가 표마다 달라(48120 / 38110 / 3811 / 15118ZONE_07383801 …) 코드가
    아니라 이름(마지막 어절)으로 맞춘다 — 일반구(의창구)·시도(경상남도)는 이름이 달라 빠진다. 값 0 은 결측(폐지 코드 채움)."""
    d = long.copy()
    d["region"] = d["region"].map(city_name)
    d = d.loc[d["region"].isin(PRE_MERGER) | d["region"].isin(DONOR_CITIES)].copy()
    d["year"] = pd.to_numeric(d["period"].astype(str).str[:4], errors="coerce")
    d = d.dropna(subset=["year"])
    d["year"] = d["year"].astype(int)
    d["value"] = pd.to_numeric(d["value"], errors="coerce")
    d.loc[d["value"] == 0, "value"] = np.nan
    cols = ["region", "year", "value"] + ([c for c in ("item",) if c in d.columns])
    return d[cols]


def reconstruct(
    d: pd.DataFrame, how: str = "sum", weights: pd.DataFrame | None = None
) -> pd.DataFrame:
    """region×year×value → 통합 경계 재구성 (region, year, value). 통합 전 마산·창원·진해를 합산(sum) 또는
    인구 가중 평균(wmean). MERGE_YEAR 제외. 통합 후 마산·진해 값이 남아 있으면 오류. 대조군은 DONOR_CITIES 만."""
    x = d[["region", "year", "value"]].copy()
    x = x[x["region"].isin(PRE_MERGER) | x["region"].isin(DONOR_CITIES)]
    x = x[x["year"] != MERGE_YEAR].dropna(subset=["value"])
    dup = x[x.duplicated(["region", "year"], keep=False)]
    if len(dup):
        ex = dup[["region", "year"]].drop_duplicates().head(6).to_dict("records")
        raise ValueError(
            f"같은 시·연도에 값이 둘 이상입니다(지역코드가 둘인 시?): {ex}. 합산하지 않고 멈춥니다."
        )
    pre = x["year"] < MERGE_YEAR
    old = x[pre & x["region"].isin(PRE_MERGER)]
    for y in sorted(x.loc[pre, "year"].unique()):
        have = set(old.loc[old["year"] == y, "region"])
        if have != set(PRE_MERGER):
            raise ValueError(
                f"{y}년 통합 전 3개 시 자료가 빠졌습니다 (없음: {sorted(set(PRE_MERGER) - have)}). 부분 합계로 대체하지 않습니다."
            )
    late = x[~pre & x["region"].isin(("마산시", "진해시"))]
    if len(late):
        raise ValueError(
            f"통합 후에도 마산시·진해시 값이 있습니다: {sorted(late['year'].unique())}"
        )
    if how == "sum":
        agg = old.groupby("year", as_index=False)["value"].sum()
    elif how == "wmean":
        if weights is None:
            raise ValueError("how='wmean' 은 weights(인구표)가 필요합니다")
        w = weights[["region", "year", "value"]].rename(columns={"value": "w"}).dropna(subset=["w"])
        mm = old.merge(w, on=["region", "year"], how="left")
        if mm["w"].isna().any():
            raise ValueError("가중 평균용 인구가 없는 연도·시가 있습니다")
        agg = (
            mm.assign(vw=mm["value"] * mm["w"])
            .groupby("year")
            .apply(lambda g: g["vw"].sum() / g["w"].sum(), include_groups=False)
            .rename("value")
            .reset_index()
        )
    else:
        raise ValueError(f"알 수 없는 how={how}")
    agg["region"] = MERGED
    rest = x[~(pre & x["region"].isin(PRE_MERGER)) & ~x["region"].isin(("마산시", "진해시"))]
    return (
        pd.concat([rest, agg[["region", "year", "value"]]], ignore_index=True)
        .sort_values(["region", "year"])
        .reset_index(drop=True)
    )


def city_measure(m: Measure, raw: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """통계표 응답(raw[table_key] = tidy 롱포맷)들 → 경계 재구성 전의 시 단위 (region, year, value)."""
    parts = []
    for key in m.tables:
        if key not in raw or raw[key] is None or len(raw[key]) == 0:
            continue
        d = pick_item(raw[key], m.item, m.item_exclude)
        if m.select or m.sum_over:
            d = pick_dims(d, m)
        parts.append(city_rows(d))
    if not parts:
        raise ValueError(f"{m.name}: 쓸 수 있는 통계표 응답이 없습니다 ({m.tables})")
    long = pd.concat(parts, ignore_index=True)
    if long.duplicated(
        ["region", "year"]
    ).any():  # 표 두 개의 연도가 겹치면 뒤 표(최신 조사)를 쓴다
        long = long.drop_duplicates(["region", "year"], keep="last")
    return long[["region", "year", "value"]]


def build_measure(
    m: Measure, raw: dict[str, pd.DataFrame], population: pd.DataFrame | None = None
) -> pd.DataFrame:
    """city_measure → reconstruct. population 은 가중 평균용 **재구성 전** 시 단위 인구표(마산·창원·진해 행이 있어야 함)."""
    return reconstruct(city_measure(m, raw), m.how, weights=population)


def finalize_core(parts: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """핵심 측정치 5개(region, year, value) → plan.yaml 의 패널. 결측은 채우지 않고 멈춘다."""
    panel = None
    for col, part in parts.items():
        part = part.rename(columns={"value": col})
        panel = part if panel is None else panel.merge(part, on=["region", "year"], how="outer")
    d = panel[panel["region"].isin(UNITS) & panel["year"].isin(YEARS)].copy()
    need = list(CORE_MEASURES)
    miss = d[d[need].isna().any(axis=1)]
    if len(miss):
        ex = miss[["region", "year"]].head(8).to_dict("records")
        raise ValueError(f"결측 {len(miss)}행 — 0 으로 채우지 않습니다. 예: {ex}")
    expected = pd.MultiIndex.from_product([UNITS, YEARS], names=["region", "year"])
    gap = expected.difference(pd.MultiIndex.from_frame(d[["region", "year"]]))
    if len(gap):
        raise ValueError(
            f"{len(UNITS)}개 시 × {len(YEARS)}년 균형 패널이 아닙니다. 빠진 예: {list(gap[:8])}. 이름이 다르면 DONOR_CITIES 와 KOSIS 지역명을 맞추세요."
        )
    if d.duplicated(["region", "year"]).any():
        raise ValueError("시×연도 중복 행이 있습니다")
    if (d[["employees", "establishments", "population"]] <= 0).any().any():
        raise ValueError("종사자·사업체·인구가 0 이하인 행이 있어 로그를 계산할 수 없습니다")
    d["region_id"] = d["region"]
    d["treated"] = (d["region"] == MERGED).astype(int)
    d["log_employees"] = np.log(d["employees"])
    d["log_establishments"] = np.log(d["establishments"])
    d["manufacturing_emp_share"] = d["employees_mfg"] / d["employees"] * 100
    cols = ["region_id", "region", "year", "treated", "population", "employees", "establishments", "employees_mfg",
            "log_employees", "log_establishments", "manufacturing_emp_share", "fiscal_independence"]  # fmt: skip
    return d[cols].sort_values(["region_id", "year"]).reset_index(drop=True)


def finalize_extended(parts: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """확장 측정치 → indicators.yaml 의 열. 지표마다 기간이 달라 결측을 허용한다(scorecard 가 지표별로 자른다)."""
    panel = None
    for col, part in parts.items():
        part = part.rename(columns={"value": col})
        panel = part if panel is None else panel.merge(part, on=["region", "year"], how="outer")
    d = panel[panel["region"].isin(UNITS) & panel["year"].isin(YEARS)].copy()
    d["region_id"] = d["region"]
    d["treated"] = (d["region"] == MERGED).astype(int)
    if {"pop_youth", "pop_age_total"} <= set(d.columns):
        d["youth_share"] = d["pop_youth"] / d["pop_age_total"] * 100
    if {"pop_under65", "pop_age_total"} <= set(d.columns):
        d["elderly_share"] = (d["pop_age_total"] - d["pop_under65"]) / d["pop_age_total"] * 100
    if {"mig_youth_in", "mig_youth_out", "pop_youth"} <= set(d.columns):
        d["youth_net_migration_rate"] = (
            (d["mig_youth_in"] - d["mig_youth_out"]) / d["pop_youth"] * 1000
        )
    if {"employees_hvs", "employees_from2007"} <= set(d.columns):
        d["high_value_service_share"] = d["employees_hvs"] / d["employees_from2007"] * 100
    if {"civil_servants", "population"} <= set(d.columns):
        d["residents_per_civil_servant"] = d["population"] / d["civil_servants"]
    keep = ["region_id", "region", "year", "treated"] + [
        c for c in ("youth_share", "elderly_share", "youth_net_migration_rate", "fiscal_autonomy", "employment_rate",
                    "unemployment_rate", "high_value_service_share", "residents_per_civil_servant") if c in d.columns
    ]  # fmt: skip
    return d[keep].sort_values(["region_id", "year"]).reset_index(drop=True)


# ── 합성 패널 (키 없이 파이프라인 점검용) ───────────────────────────────────────────────────────
def simulate(
    seed: int = 20100701,
    effect_log_emp: float = 0.03,
    effect_mfg: float = -1.5,
    effect_fis: float = 2.0,
):
    """실데이터 아님. 단위 고정효과 + 공통 연도 충격 + 완만한 단위별 추세 + 임의로 심은 효과.
    반환: (핵심 패널, 확장 패널). 효과 크기는 파이프라인이 심은 값을 되찾는지 보기 위한 임의 값."""
    rng = np.random.default_rng(seed)
    n = len(UNITS)
    base = rng.normal(np.log(60_000), 0.7, n)
    base[0] = np.log(400_000)
    slope = rng.normal(0.01, 0.008, n)
    common = np.cumsum(rng.normal(0.015, 0.01, len(YEARS)))
    est_ratio = rng.uniform(0.18, 0.32, n)
    mfg = np.clip(rng.normal(22, 9, n), 3, 60)
    mfg[0] = 40
    fis_base = np.clip(rng.normal(38, 12, n), 10, 80)
    fis_common = np.cumsum(rng.normal(-0.6, 0.5, len(YEARS)))
    youth = np.clip(rng.normal(21, 2.5, n), 12, 30)
    elderly = np.clip(rng.normal(12, 3, n), 5, 30)
    core_rows, ext_rows = [], []
    for i, u in enumerate(UNITS):
        shock = 0.0
        for j, y in enumerate(YEARS):
            d = int(i == 0 and y >= TREAT_TIME)
            shock = 0.6 * shock + rng.normal(0, 0.008)
            le = base[i] + slope[i] * (y - START) + common[j] + shock + effect_log_emp * d
            emp = float(np.exp(le))
            pop = emp * rng.uniform(2.2, 2.8)
            est = emp * est_ratio[i]
            m = float(np.clip(mfg[i] + rng.normal(0, 1.0) + effect_mfg * d, 1, 90))
            fis = float(
                np.clip(fis_base[i] + fis_common[j] + rng.normal(0, 1.5) + effect_fis * d, 3, 95)
            )
            core_rows.append((u, u, y, int(i == 0), round(pop), round(emp), round(est), round(emp * m / 100),
                              le, float(np.log(est)), m, fis))  # fmt: skip
            if y >= 2008:
                ys = float(np.clip(youth[i] - 0.25 * (y - 2008) + rng.normal(0, 0.3), 5, 40))
                es = float(np.clip(elderly[i] + 0.5 * (y - 2008) + rng.normal(0, 0.3), 3, 50))
                nm = float(rng.normal(-8, 6))
                er = float(np.clip(58 + rng.normal(0, 1.5) + 0.1 * (y - 2008), 40, 75))
                ur = float(np.clip(3 + rng.normal(0, 0.6), 0.5, 10))
                hv = float(np.clip(6 + rng.normal(0, 0.8), 1, 30))
                rc = float(np.clip(180 + rng.normal(0, 15), 60, 400))
                ext_rows.append(
                    (u, u, y, int(i == 0), ys, es, nm, fis + rng.normal(10, 2), er, ur, hv, rc)
                )
    core_cols = ["region_id", "region", "year", "treated", "population", "employees", "establishments", "employees_mfg",
                 "log_employees", "log_establishments", "manufacturing_emp_share", "fiscal_independence"]  # fmt: skip
    ext_cols = ["region_id", "region", "year", "treated", "youth_share", "elderly_share", "youth_net_migration_rate",
                "fiscal_autonomy", "employment_rate", "unemployment_rate", "high_value_service_share",
                "residents_per_civil_servant"]  # fmt: skip
    return pd.DataFrame(core_rows, columns=core_cols), pd.DataFrame(ext_rows, columns=ext_cols)


# ── KOSIS 호출 ─────────────────────────────────────────────────────────────────────────────────
def _redact(msg: str) -> str:
    """오류 메시지에 URL 이 섞여 들어와도 API 키는 남기지 않는다 (probe.json·source.json·콘솔에 기록되므로)."""
    return re.sub(r"apiKey=[^&\s]+", "apiKey=***", msg)


def _get(params: dict, timeout: int = 60, url: str = KOSIS_URL) -> list | dict:
    try:
        r = requests.get(
            url, params={k: v for k, v in params.items() if v is not None}, timeout=timeout
        )
        r.raise_for_status()
        return r.json()
    except requests.RequestException as err:
        raise RuntimeError(f"KOSIS 요청 실패: {_redact(str(err))}") from None


def _base(t: Table, api_key: str) -> dict:
    """표의 분류 개수(levels)만큼 objL1~objLn 을 ALL 로 둔다 — 더 보내면 err 21, 덜 보내면 err 20."""
    if not t.levels:
        raise ValueError(f"{t.key}: levels 가 없습니다 — table_meta() 로 먼저 알아내세요")
    p = {"method": "getList", "apiKey": api_key, "format": "json", "jsonVD": "Y", "orgId": t.org_id, "tblId": t.tbl_id,
         "itmId": t.itm_id, "prdSe": t.prd_se}  # fmt: skip
    for i in range(1, t.levels + 1):
        p[f"objL{i}"] = "ALL"
    return p


PRD_SE_KO = {"Y": "년", "H": "반기", "Q": "분기", "M": "월"}


def table_meta(t: Table, api_key: str) -> dict:
    """getMeta(type=ITM, PRD): 항목 이름, 분류(objL1~n)별 코드·이름, 수록 기간. 자료를 받지 않고 구조를 알 수 있다."""
    base = {"method": "getMeta", "apiKey": api_key, "format": "json", "jsonVD": "Y", "orgId": t.org_id, "tblId": t.tbl_id}
    itm = _get({**base, "type": "ITM"}, url=META_URL)
    if isinstance(itm, dict):
        raise RuntimeError(f"{t.key}({t.tbl_id}): 메타정보 없음 — KOSIS 오류 {itm.get('err')}: {itm.get('errMsg')}")
    items, dims = [], {}
    for x in itm:
        if x.get("OBJ_ID") == "ITEM":
            items.append(str(x.get("ITM_NM")))
        else:
            dims.setdefault((x.get("OBJ_ID"), x.get("OBJ_NM")), []).append((str(x.get("ITM_ID")), str(x.get("ITM_NM"))))
    prd = _get({**base, "type": "PRD"}, url=META_URL)
    period = None
    if isinstance(prd, list):
        want = PRD_SE_KO.get(t.prd_se, "년")
        hit = [p for p in prd if p.get("PRD_SE") == want] or prd
        period = (str(hit[0].get("STRT_PRD_DE")), str(hit[0].get("END_PRD_DE")))
    return {
        "items": items,
        "dims": [{"obj_id": k[0], "obj_nm": k[1], "codes": v} for k, v in dims.items()],
        "period": period,
    }


def sample_from_meta(meta: dict) -> pd.DataFrame:
    """메타정보 → tidy() 결과와 같은 열 이름의 '표본' (분류 1 = 지역, 분류 2~n = C2/C2_NM …; 행마다 한 분류만 채움).
    detect_dims·codes_for 는 열별 고유값만 보므로 이렇게 모아도 된다."""
    frames = [pd.DataFrame({"item": meta["items"]})]
    for i, dim in enumerate(meta["dims"], start=1):
        codes = pd.DataFrame(dim["codes"], columns=["code", "name"])
        if i == 1:
            frames.append(codes.rename(columns={"code": "region_code", "name": "region"}))
        else:
            frames.append(codes.rename(columns={"code": f"C{i}", "name": f"C{i}_NM"}))
    s = pd.concat(frames, ignore_index=True)
    for c in ("region_code", "region", "item", "period", "value"):
        if c not in s.columns:
            s[c] = np.nan
    return s


def _period_bounds(t: Table, a: int, b: int) -> tuple[str, str]:
    """연도 구간 → KOSIS startPrdDe/endPrdDe (반기 'YYYY01'~'YYYY02', 분기 'YYYY01'~'YYYY04')."""
    if t.prd_se == "H":
        return f"{a}01", f"{b}02"
    if t.prd_se == "Q":
        return f"{a}01", f"{b}04"
    return str(a), str(b)


def _year_chunks(start: int, end: int, size: int):
    y = start
    while y <= end:
        yield y, min(y + size - 1, end)
        y += size


def fetch_table(t: Table, api_key: str, codes: dict[str, list[str]] | None = None) -> pd.DataFrame:
    """통계표 전체 기간을 chunk 연도씩 받아 tidy 롱포맷으로 합친다. codes 가 있으면 그 분류 코드만 받는다
    (예: {'objL2': ['A', 'C']} → 산업 전체·제조업만) — 큰 표의 셀 수 제한을 피한다. period_keep 이 있으면 그 시점만 남긴다."""
    frames = []
    combos = [{}]
    for obj, lst in (codes or {}).items():
        combos = [{**c, obj: code} for c in combos for code in lst]
    for a, b in _year_chunks(t.years[0], t.years[1], t.chunk):
        sa, sb = _period_bounds(t, a, b)
        for extra in combos:
            data = _get({**_base(t, api_key), **extra, "startPrdDe": sa, "endPrdDe": sb})
            if isinstance(data, dict):
                if str(data.get("err")) in (
                    "30",
                    "20",
                ):  # 자료 없음 / 기간 없음 — 그 구간만 건너뛴다
                    continue
                raise RuntimeError(
                    f"{t.key}({t.tbl_id}) {sa}~{sb}: KOSIS 오류 {data.get('err')}: {data.get('errMsg')}"
                )
            frames.append(pd.DataFrame(data))
    if not frames:
        raise RuntimeError(f"{t.key}({t.tbl_id}): {t.years[0]}~{t.years[1]} 에 자료가 없습니다")
    d = tidy(pd.concat(frames, ignore_index=True))
    if t.period_keep:
        d = d[d["period"].astype(str).str.contains(t.period_keep, regex=True)].copy()
    return d


def codes_for(sample: pd.DataFrame, m: Measure) -> dict[str, list[str]]:
    """표본(메타)에서 Measure 가 필요로 하는 분류 코드를 고른다 (호출 범위를 줄이기 위한 것 — 뒤에서 이름으로 다시 거른다)."""
    dims = detect_dims(sample)
    out: dict[str, list[str]] = {}
    for kind, pat in {**m.select, **m.sum_over}.items():
        col = dims.get(kind)
        if col is None:
            continue
        code_col = col.replace("_NM", "")
        names = sample[[code_col, col]].dropna().drop_duplicates()
        if kind in m.select:
            hit = names[names[col].astype(str).str.strip().str.match(pat)]
        else:
            hit = names[names[col].astype(str).str.strip().str.contains(pat, regex=True)]
        if len(hit):
            idx = int(code_col[1:])  # C2 → objL2
            out[f"objL{idx}"] = sorted(hit[code_col].astype(str).unique())
    return out


def fetch_real(only: str = "all") -> tuple[pd.DataFrame, pd.DataFrame | None, dict]:
    api_key = KosisAdapter().api_key()
    plan = yaml.safe_load((HERE / "plan.yaml").read_text(encoding="utf-8"))
    plan_tbls = {d["query"]["tblId"] for d in plan["data_sources"] if d.get("adapter") == "kosis"}
    for key in CORE_TABLES:
        if TABLES[key].tbl_id not in plan_tbls:
            raise ValueError(f"plan.yaml data_sources 에 {TABLES[key].tbl_id}({key}) 가 없습니다")
    RAW.mkdir(parents=True, exist_ok=True)
    raw: dict[str, pd.DataFrame] = {}
    prov: dict[str, dict] = {}
    wanted = CORE_TABLES if only == "core" else tuple(TABLES)
    for key in wanted:
        t = TABLES[key]
        if t.status == "unavailable":
            prov[key] = {"tblId": t.tbl_id, "name": t.name, "ok": False, "status": t.status, "error": t.note}
            print(f"[fetch] {key:16s} {t.tbl_id:14s} 건너뜀: {t.note[:120]}")
            continue
        try:
            meta = table_meta(t, api_key)
            t.levels = t.levels or len(meta["dims"])
            sample = sample_from_meta(meta)
            need = [m for m in MEASURES.values() if key in m.tables]
            codes: dict[str, set] = {}
            for m in need:
                for obj, lst in codes_for(sample, m).items():
                    codes.setdefault(obj, set()).update(lst)
            df = fetch_table(t, api_key, {k: sorted(v) for k, v in codes.items()} or None)
            df.to_csv(RAW / f"{t.tbl_id}.csv", index=False)
            raw[key] = df
            prov[key] = {"tblId": t.tbl_id, "orgId": t.org_id, "name": t.name, "rows": int(len(df)), "status": t.status, "ok": True,
                         "levels": t.levels, "period_available": meta["period"], "dims": detect_dims(sample),
                         "items": meta["items"][:12], "codes_requested": {k: sorted(v) for k, v in codes.items()}}  # fmt: skip
            print(f"[fetch] {key:16s} {t.tbl_id:14s} {len(df):7d}행  분류={prov[key]['dims']}")
        except Exception as err:  # noqa: BLE001 — 후보 표는 실패해도 핵심이 아니면 계속
            prov[key] = {"tblId": t.tbl_id, "name": t.name, "ok": False, "error": _redact(str(err))[:300]}
            print(f"[fetch] {key:16s} {t.tbl_id:14s} 실패: {_redact(str(err))[:160]}", file=sys.stderr)
            if key in CORE_TABLES:
                raise RuntimeError(
                    f"핵심 통계표 {key}({t.tbl_id}) 수집 실패: {_redact(str(err))}\n→ python fetch.py --probe 로 구조를 보고, "
                    "python fetch.py --discover <키워드> 로 ID 후보를 찾아 TABLES 와 plan.yaml 을 고치세요"
                ) from err
    pop_city = city_measure(MEASURES["population"], raw)  # 재구성 전 — 가중 평균의 가중치
    pop = reconstruct(pop_city, "sum")
    core = {}
    for name in CORE_MEASURES:
        core[name] = (
            pop if name == "population" else build_measure(MEASURES[name], raw, population=pop_city)
        )
    panel = finalize_core(core)
    ext_parts, ext_err = {}, {}
    if only != "core":
        for name, m in MEASURES.items():
            if name in CORE_MEASURES:
                continue
            missing = [k for k in m.tables if k not in raw]
            if missing:
                why = "; ".join(
                    f"{k}: {TABLES[k].note or TABLES[k].tbl_id + ' 수집 실패'}" if TABLES[k].status == "unavailable"
                    else f"{k}({TABLES[k].tbl_id}) 수집 실패: {prov.get(k, {}).get('error', '')}"
                    for k in missing
                )  # fmt: skip
                ext_err[name] = f"통계표 없음 — {why}"[:400]
                continue
            try:
                ext_parts[name] = build_measure(m, raw, population=pop_city)
            except Exception as err:  # noqa: BLE001
                ext_err[name] = _redact(str(err))[:300]
                print(f"[fetch] 확장 지표 {name} 실패: {_redact(str(err))[:160]}", file=sys.stderr)
        if "civil_servants" in ext_parts:
            ext_parts["population"] = pop
    extended = finalize_extended(ext_parts) if ext_parts else None
    indicator_errors = {
        col: " / ".join(f"{m}: {ext_err[m]}" for m in needs if m in ext_err)
        for col, needs in INDICATOR_NEEDS.items()
        if any(m in ext_err for m in needs)
    }
    meta = {
        "synthetic_data": False,
        "tables": prov,
        "extended_errors": ext_err,
        "indicator_errors": indicator_errors,
        "aggregation": "통합 전(≤2009) 마산·창원·진해 합산(비율은 합산 뒤 재계산, 표의 비율 지표는 인구 가중 평균), 2010 제외",
        "donor_cities": list(DONOR_CITIES),
    }
    return panel, extended, meta


def discover(keyword: str, n: int = 100) -> list[dict]:
    """KOSIS 통계표 검색 API 로 후보 통계표를 보여준다 (키 필요)."""
    data = _get(
        {"method": "getList", "apiKey": KosisAdapter().api_key(), "format": "json", "jsonVD": "Y",
         "searchNm": keyword, "resultCount": str(n), "startCount": "1"},
        timeout=30, url="https://kosis.kr/openapi/statisticsSearch.do",
    )  # fmt: skip
    if isinstance(data, dict):
        raise RuntimeError(f"KOSIS 오류 {data.get('err')}: {data.get('errMsg')}")
    rows = [{k: x.get(k) for k in ("ORG_ID", "TBL_ID", "TBL_NM", "STAT_NM")} for x in data]
    for x in rows:
        print(f"{x['ORG_ID']}\t{x['TBL_ID']}\t{x['TBL_NM']}\t({x['STAT_NM']})")
    return rows


def probe() -> dict:
    """TABLES 의 각 통계표: 메타정보로 있는지, 분류(objL 개수)·항목·수록 기간이 무엇인지, 쓰려는 연도를 덮는지 확인해 찍는다
    (키 필요, 자료 호출 없음)."""
    api_key = KosisAdapter().api_key()
    out = {}
    for key, t in TABLES.items():
        if t.status == "unavailable":
            out[key] = {"ok": False, "status": t.status, "error": t.note}
            print(f"[probe] {key:16s} {t.tbl_id:14s} 쓰지 않음: {t.note[:150]}")
            continue
        try:
            meta = table_meta(t, api_key)
            s = sample_from_meta(meta)
            dims = detect_dims(s)
            n_levels = len(meta["dims"])
            period = meta["period"]
            covers = bool(period) and int(period[0][:4]) <= t.years[0] and int(period[1][:4]) >= t.years[1]
            info = {"ok": True, "levels": n_levels, "levels_in_table": t.levels, "period_available": period, "dims": dims,
                    "items": meta["items"][:10], "covers_years": covers, "n_regions": len(meta["dims"][0]["codes"]) if meta["dims"] else 0}  # fmt: skip
            samples = {c: sorted(s[c].dropna().astype(str).unique())[:8] for c in dims.values()}
            flag = "" if (t.levels in (None, n_levels)) else f"  ⚠ levels={t.levels} 인데 표는 {n_levels}"
            print(
                f"[probe] {key:16s} {t.tbl_id:14s} OK  분류 {n_levels}개  수록={period}  {t.years[0]}~{t.years[1]} 덮음={'예' if covers else '아니오'}  항목={info['items'][:4]}{flag}"
            )
            for c, v in samples.items():
                print(f"        {c}: {v}")
        except Exception as err:  # noqa: BLE001
            info = {"ok": False, "error": _redact(str(err))[:300]}
            print(f"[probe] {key:16s} {t.tbl_id:14s} 실패: {_redact(str(err))[:200]}")
        out[key] = info
    (HERE / "data").mkdir(exist_ok=True)
    (HERE / "data" / "probe.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), "utf-8"
    )
    return out


def write(panel: pd.DataFrame, extended: pd.DataFrame | None, meta: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(OUT, index=False)
    meta = {
        **meta,
        "rows": int(len(panel)),
        "units": int(panel["region_id"].nunique()),
        "years": [int(panel["year"].min()), int(panel["year"].max())],
        "excluded_year": MERGE_YEAR,
        "extended_columns": []
        if extended is None
        else [c for c in extended.columns if c not in ("region_id", "region", "year", "treated")],
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    OUT.with_suffix(".source.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), "utf-8"
    )
    flag = " (합성 — 실데이터 아님)" if meta.get("synthetic_data") else ""
    print(f"[fetch] 핵심 {len(panel)}행, {meta['units']}개 시 → {OUT.relative_to(HERE)}{flag}")
    if extended is not None:
        extended.to_csv(EXT, index=False)
        print(
            f"[fetch] 확장 {len(extended)}행, 지표 {meta['extended_columns']} → {EXT.relative_to(HERE)}{flag}"
        )
    elif EXT.exists():
        EXT.unlink()


def main(argv=None) -> None:
    for stream in (sys.stdout, sys.stderr):  # Windows cp949 콘솔에서 한글·기호 출력으로 멈추지 않게
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--simulate", action="store_true", help="키 없이 합성 패널 생성(실데이터 아님)")
    ap.add_argument("--discover", metavar="키워드", help="KOSIS 통계표 검색으로 ID 후보 보기")
    ap.add_argument("--probe", action="store_true", help="TABLES 의 통계표 구조·기간 확인(메타정보)")
    ap.add_argument(
        "--only", choices=["all", "core"], default="all", help="core: 핵심 4지표만 수집"
    )
    a = ap.parse_args(argv)
    if a.discover:
        discover(a.discover)
        return
    if a.probe:
        probe()
        return
    if a.simulate:
        core, ext = simulate()
        write(core, ext, {"synthetic_data": True, "license": "synthetic",
                          "note": "fetch.py --simulate 로 만든 합성 패널. 파이프라인 점검용이며 결과를 해석하지 않는다"})  # fmt: skip
        return
    try:
        panel, extended, meta = fetch_real(a.only)
    except MissingAPIKey as e:
        sys.exit(
            f"{e}\nKOSIS 공유서비스(https://kosis.kr/openapi)에서 무료 발급 후 .env 의 KOSIS_API_KEY 에 넣으세요. "
            "키 없이 파이프라인만 점검하려면: python fetch.py --simulate (합성 데이터, 결과 해석 금지)"
        )
    write(panel, extended, meta)


if __name__ == "__main__":
    main()
