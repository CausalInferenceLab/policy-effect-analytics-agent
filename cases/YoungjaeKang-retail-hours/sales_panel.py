"""검증된 구×분기×업종 합계에서 패널을 만드는 순수 변환 함수.

다운로드·상권 선택·공간 연결·정책 적격성 확인은 호출자의 선행 작업이다.
build_panels는 완전한 업종합계용, build_observed_panels는 승인된 관측 행 탐색 지표용이다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

INDUSTRIES = ("CS300007", "CS300008", "CS300009", "CS300010")
QUARTERS = tuple(range(16))
ESTIMATION_QUARTERS = tuple(q for q in QUARTERS if q != 12)


def build_panels(
    industry_totals: pd.DataFrame, *, treated_code: str, control_codes: list[str]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """전체 16분기 집계와 2024Q1을 제외한 추정 입력을 반환한다.

    입력은 골목상권만의 구×분기×업종 합계이며 금액 단위는 원이다.
    코드는 호출자가 같은 체계로 정규화한 문자열이어야 한다.
    명단은 명시적으로 전달하며 자료 값에서 비교군을 고르지 않는다.
    이 함수의 통과는 정책 이력·상권 누락·공간 버전 검증을 뜻하지 않는다.
    """
    codes = [treated_code, *control_codes]
    if (
        not control_codes
        or any(not isinstance(code, str) or not code.strip() for code in codes)
        or len(set(codes)) != len(codes)
    ):
        raise ValueError("처치 1개와 중복 없는 비교구 문자열 코드가 필요합니다")
    keys = ["gu_code", "quarter_idx", "industry_code"]
    columns = [*keys, "sales_krw"]
    if missing := set(columns) - set(industry_totals.columns):
        raise ValueError(f"필수 열 누락: {sorted(missing)}")
    frame = industry_totals[columns].copy()
    if frame.isna().any().any():
        raise ValueError("입력 결측: 누락을 0으로 대체하지 않습니다")
    if not frame["gu_code"].map(lambda x: isinstance(x, str)).all():
        raise ValueError("구 코드는 같은 체계의 문자열이어야 합니다")
    if set(frame["gu_code"]) != set(codes):
        raise ValueError("입력 지역과 명시한 명단이 다릅니다")
    for column in ("quarter_idx", "sales_krw"):
        values = frame[column]
        if (
            not pd.api.types.is_numeric_dtype(values)
            or pd.api.types.is_bool_dtype(values)
            or not np.isfinite(values).all()
        ):
            raise ValueError(f"{column}: 유한한 숫자가 필요합니다")
    if not frame["quarter_idx"].isin(QUARTERS).all():
        raise ValueError("quarter_idx는 2021Q1=0부터 2024Q4=15까지 정수입니다")
    if (frame["sales_krw"] < 0).any():
        raise ValueError("음수 매출")
    if frame.duplicated(keys).any():
        raise ValueError("구×분기×업종 중복")
    expected = pd.MultiIndex.from_product([codes, QUARTERS, INDUSTRIES], names=keys)
    actual = pd.MultiIndex.from_frame(frame[keys])
    if len(expected.difference(actual)) or len(actual.difference(expected)):
        raise ValueError("구별 16분기×4업종이 필요합니다: 누락·추가 업종 확인")
    frame["quarter_idx"] = frame["quarter_idx"].astype(int)
    # 부동소수 변환 뒤 합산해 int64 합계 overflow를 피한다.
    frame["sales_krw"] = frame["sales_krw"].astype(float)
    full = frame.groupby(["gu_code", "quarter_idx"], as_index=False)["sales_krw"].sum()
    if not np.isfinite(full["sales_krw"]).all():
        raise ValueError("합계가 유한하지 않습니다")
    full["treated"] = (full["gu_code"] == treated_code).astype(int)
    full = full[["gu_code", "quarter_idx", "treated", "sales_krw"]]
    panel = full.loc[full["quarter_idx"] != 12].copy()
    if (panel["sales_krw"] <= 0).any():
        raise ValueError("추정 분기 합계가 0 이하라 로그를 계산할 수 없습니다")
    panel["log_sales"] = np.log(panel["sales_krw"])
    return full.reset_index(drop=True), panel.reset_index(drop=True)


def build_observed_panels(rows: pd.DataFrame, names: list[str]):
    """관측 행만 집계. 미관측 금액을 채우지 않고 고정한 모든 구·분기를 요구한다."""
    keys = ["gu_name", "quarter_idx", "area_code", "industry_code"]
    frame = rows[[*keys, "sales_krw"]].copy()
    if len(names) != 21 or len(set(names)) != 21 or names[0] != "동대문구":
        raise ValueError("고정 처치1/비교20 명단 필요")
    if frame.isna().any().any() or frame.duplicated(keys).any():
        raise ValueError("관측 행 결측 또는 키 중복")
    if set(frame.gu_name) != set(names) or not frame.industry_code.isin(INDUSTRIES).all():
        raise ValueError("관측 지역·업종 범위 불일치")
    if not frame.quarter_idx.isin(QUARTERS).all():
        raise ValueError("분기 범위 불일치")
    values = frame.sales_krw
    if (
        not pd.api.types.is_numeric_dtype(values)
        or pd.api.types.is_bool_dtype(values)
        or not np.isfinite(values).all()
        or values.lt(0).any()
    ):
        raise ValueError("비정상 관측 금액")
    frame["sales_krw"] = values.astype(float)
    full = frame.groupby(["gu_name", "quarter_idx"], as_index=False).agg(
        observed_sales_krw=("sales_krw", "sum"),
        observed_rows=("area_code", "size"),
        observed_industries=("industry_code", "nunique"),
    )
    expected = pd.MultiIndex.from_product([names, QUARTERS])
    actual = pd.MultiIndex.from_frame(full[["gu_name", "quarter_idx"]])
    if len(expected.difference(actual)):
        raise ValueError("구×분기 전체 미관측: 0 보충·지역 제외 금지")
    if not np.isfinite(full.observed_sales_krw).all() or full.observed_sales_krw.le(0).any():
        raise ValueError("관측 합계가 유한한 양수가 아님")
    full = full.rename(columns={"gu_name": "gu_code"})
    full["quarter_idx"] = full.quarter_idx.astype(int)
    full["treated"] = full.gu_code.eq(names[0]).astype(int)
    panel = full.loc[full.quarter_idx.ne(12)].copy()
    panel["log_observed_sales"] = np.log(panel.observed_sales_krw)
    return full.reset_index(drop=True), panel.reset_index(drop=True)
