"""관측 부재를 0으로 바꾸지 않는 대조와 공식 수치 반올림 검사."""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sales_crosscheck import REFERENCE, compare_reference, compare_stores  # noqa: E402


def reference_frame():
    return pd.DataFrame(
        [
            {
                "상권_코드_명": "동대문패션타운 관광특구",
                "상권_구분_코드": "U",
                "상권_코드": "test",
                "기준_년분기_코드": q,
                "서비스_업종_코드": "test-industry",
                "당월_매출_금액": str(int(value * 1e8)),
            }
            for q, value in REFERENCE.items()
        ]
    )


def test_reference_comparison_is_json_serializable_and_detects_scaling():
    frame = reference_frame()
    result = compare_reference(frame)
    assert all(x["matches_published_rounding"] for x in result)
    json.dumps(result, allow_nan=False)
    frame["당월_매출_금액"] = frame["당월_매출_금액"].map(lambda x: str(int(x) * 3))
    assert not any(x["matches_published_rounding"] for x in compare_reference(frame))


def test_reference_missing_quarter_and_duplicate_are_errors():
    frame = reference_frame()
    with pytest.raises(ValueError, match="기간"):
        compare_reference(frame.iloc[1:])
    with pytest.raises(ValueError, match="중복"):
        compare_reference(pd.concat([frame, frame.iloc[:1]]))


def test_store_presence_does_not_impute_sales_or_zero_store_rows():
    stores = [
        {"area": a, "industry": "i", "total": n}
        for a, n in [("a", 2), ("b", 0), ("c", 2), ("d", 0)]
    ]
    sales = pd.DataFrame(
        [("c", "i", 7, 100), ("d", "i", 7, 100), ("e", "i", 7, 100), ("a", "i", 6, 100)],
        columns=["area_code", "industry_code", "quarter_idx", "sales_krw"],
    )
    mapping = {a: "test-gu" for a in "abcde"}
    result = compare_stores(stores, sales, mapping, ["test-gu"]).set_index("area_code")
    assert result.loc["a", "category"] == "positive_store_row_sales_absent"
    assert result.loc["b", "category"] == "zero_store_row_sales_absent"
    assert result.loc["c", "category"] == "both_observed"
    assert result.loc["d", "category"] == "sales_observed_zero_store_row"
    assert result.loc["e", "category"] == "sales_only_store_row_absent"
    assert pd.isna(result.loc["a", "sales_krw"]) and pd.isna(result.loc["e", "total"])


def test_store_crosscheck_rejects_duplicate_and_unmapped_keys():
    stores = [{"area": "a", "industry": "i", "total": 2}]
    sales = pd.DataFrame(
        [("a", "i", 7, 100)], columns=["area_code", "industry_code", "quarter_idx", "sales_krw"]
    )
    with pytest.raises(pd.errors.MergeError):
        compare_stores(stores * 2, sales, {"a": "test-gu"}, ["test-gu"])
    with pytest.raises(ValueError, match="미연결"):
        compare_stores(stores, sales, {}, ["test-gu"])
