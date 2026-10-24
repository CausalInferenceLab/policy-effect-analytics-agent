"""기존 스냅샷으로 금액 정의와 점포/매출 관측 차이를 대조한다. 추정·대체값 생성 없음."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

import pandas as pd
from characteristics_files import archive, inspect_stores, inspect_territory
from fetch import read_sales, selected_districts
from fetch_characteristics import DISTRICTS, digest, dump, verified_bytes

REFERENCE_URL = (
    "https://culture.seoul.go.kr/culture/cmmn/file/fileDown.do?"
    "atchFileId=af365d87d23c4c5b8411d3ba236292f6&bbsId=&fileSn=2&menuNo=200050"
)
# 서울시·서울디자인재단 2026-02-09 보도자료 8쪽. 단위: 억원, 분기 월평균.
REFERENCE = {"20241": 1144.5, "20242": 1279.9, "20243": 1139.6, "20244": 1266.6}


def compare_reference(frame):
    target = frame.loc[frame["상권_코드_명"].eq("동대문패션타운 관광특구")].copy()
    if target.empty or not target["상권_구분_코드"].eq("U").all():
        raise ValueError("공식 대조 대상 관광특구가 없습니다")
    if (
        target["상권_코드"].nunique() != 1
        or target.duplicated(["기준_년분기_코드", "서비스_업종_코드"]).any()
    ):
        raise ValueError("관광특구 코드/업종 키 중복")
    if not target["당월_매출_금액"].str.fullmatch(r"[0-9]+").all():
        raise ValueError("비정상 금액")
    target["amount"] = target["당월_매출_금액"].map(int)
    sums = target.groupby("기준_년분기_코드").amount.sum()
    if set(sums.index) != set(REFERENCE):
        raise ValueError("대조 기간 불일치")
    return [
        {
            "quarter": q,
            "raw_sum_krw": int(sums[q]),
            "published_100m_krw": expected,
            "raw_sum_100m_krw": float(sums[q] / 1e8),
            "matches_published_rounding": bool(round(sums[q] / 1e8, 1) == expected),
        }
        for q, expected in REFERENCE.items()
    ]


def compare_stores(stores, sales, mapping, selected):
    """같은 2022Q4 키로 외부결합. 점포자료의 양수는 영업·공간 호환성 입증이 아니다."""
    left = pd.DataFrame(stores).rename(columns={"area": "area_code", "industry": "industry_code"})
    right = sales.loc[sales.quarter_idx.eq(7), ["area_code", "industry_code", "sales_krw"]]
    keys = ["area_code", "industry_code"]
    joined = left.merge(right, on=keys, how="outer", validate="one_to_one", indicator=True)
    joined["gu_name"] = joined.area_code.map(mapping)
    if joined.gu_name.isna().any():
        raise ValueError("대조 자료의 영역 코드 미연결")
    joined = joined.loc[joined.gu_name.isin(selected)].copy()
    joined["category"] = "both_observed"
    joined.loc[joined._merge.eq("right_only"), "category"] = "sales_only_store_row_absent"
    joined.loc[joined._merge.eq("left_only") & joined.total.gt(0), "category"] = (
        "positive_store_row_sales_absent"
    )
    joined.loc[joined._merge.eq("left_only") & joined.total.eq(0), "category"] = (
        "zero_store_row_sales_absent"
    )
    joined.loc[joined._merge.eq("both") & joined.total.eq(0), "category"] = (
        "sales_observed_zero_store_row"
    )
    return joined.drop(columns="_merge")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sales-snapshot", required=True, type=Path)
    parser.add_argument("--characteristics-snapshot", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    provenance = {}

    def read(root, name):
        folder = root / name
        record = json.loads((folder / "source.json").read_text())
        if record["status"] != "downloaded":
            raise ValueError("완료되지 않은 다운로드")
        verified_bytes(folder, record, "metadata")
        data = verified_bytes(folder, record, "data")
        provenance[str(folder.resolve())] = record
        return data

    raw2024 = read(args.sales_snapshot, "2024")
    with archive(raw2024) as z:
        names = [n for n in z.namelist() if n.endswith(".csv")]
        if len(names) != 1:
            raise ValueError("CSV 개수 불일치")
        all_sales = pd.read_csv(
            io.BytesIO(z.read(names[0])), encoding="cp949", dtype=str, keep_default_na=False
        )
    reference = compare_reference(all_sales)
    stores, _ = inspect_stores(read(args.characteristics_snapshot, "stores"))
    sales, _ = read_sales(read(args.sales_snapshot, "2022"), 2022)
    mapping, _ = inspect_territory(read(args.sales_snapshot, "territory"), DISTRICTS)
    joined = compare_stores(stores, sales, mapping, selected_districts())
    summary = (
        joined.groupby(["gu_name", "industry_code", "category"])
        .size()
        .rename("pairs")
        .reset_index()
    )
    args.output.mkdir(parents=True, exist_ok=True)
    joined.to_csv(args.output / "store-sales-pairs-2022Q4.csv", index=False)
    summary.to_csv(args.output / "store-sales-summary-2022Q4.csv", index=False)
    report = {
        "reference_url": REFERENCE_URL,
        "reference_page": 8,
        "reference_comparison": reference,
        "categories": joined.category.value_counts().to_dict(),
        "sources": provenance,
        "code_sha256": {
            p: digest(Path(__file__).with_name(p).read_bytes())
            for p in [
                "sales_crosscheck.py",
                "fetch.py",
                "characteristics_files.py",
                "fetch_characteristics.py",
            ]
        },
        "interpretation": "대조 결과는 결측의 0 대체·공간 호환성 확인·효과 추정을 허용하지 않는다",
    }
    dump(args.output / "crosscheck.json", report)
    print(
        json.dumps({"reference": reference, "categories": report["categories"]}, ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
