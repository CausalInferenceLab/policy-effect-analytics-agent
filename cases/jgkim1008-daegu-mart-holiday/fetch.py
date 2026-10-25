"""② 수집: 6개 광역시 × 분기(2019Q1 ~ 2023Q4) 판매액지수 패널 → data/panel.csv

- KOSIS DT_1K41018 '시도별 소매판매액지수(2020=100)', 불변지수(T2), 업종 A2·A4·A5.
- 2023Q1(quarter_idx 16)은 전환이 분기 중간이라 모든 지역에서 뺀다. 재번호하지 않는다.
- 원자료는 받은 날짜를 붙여 data/raw/ 에 남긴다(커밋하지 않음). 이 통계표는 과거 값이 재송부될 수 있다.
- 반박 검정용으로 울산을 뺀 패널(data/panel_no_ulsan.csv)도 만든다. 공통 실행기가 drop_unit 을
  아직 실행하지 않으므로 이 파일로 한 번 더 돌려 discussion.md 에 함께 보고한다.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from core.adapters.kosis import URL, KosisAdapter  # noqa: E402

ORG_ID, TBL_ID, ITEM = "101", "DT_1K41018", "T2"
START, END = "201901", "202304"  # KOSIS 분기 표기: YYYY0Q
REGIONS = {"21": "부산", "22": "대구", "23": "인천", "24": "광주", "25": "대전", "26": "울산"}
TREATED = {"22"}
INDUSTRIES = {"A4": "super_idx", "A2": "mart_idx", "A5": "auto_fuel_idx"}
TRANSITION = 16  # 2023Q1
N_QUARTERS = 20  # 0 = 2019Q1 ... 19 = 2023Q4


def download() -> pd.DataFrame:
    """업종마다 따로 요청한다(objL1 = 행정구역, objL2 = 업종). 오류도 200으로 오므로 err 를 확인한다."""
    key = KosisAdapter().api_key()
    frames = []
    for code in INDUSTRIES:
        params = {
            "method": "getList",
            "apiKey": key,
            "format": "json",
            "jsonVD": "Y",
            "orgId": ORG_ID,
            "tblId": TBL_ID,
            "itmId": ITEM,
            "objL1": "+".join(REGIONS),
            "objL2": code,
            "prdSe": "Q",
            "startPrdDe": START,
            "endPrdDe": END,
        }
        r = requests.get(URL, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and "err" in data:
            raise RuntimeError(f"KOSIS 오류 {data.get('err')}: {data.get('errMsg')} (업종 {code})")
        frames.append(pd.DataFrame(data))
    return pd.concat(frames, ignore_index=True)


def save_raw(raw: pd.DataFrame) -> None:
    folder = HERE / "data" / "raw"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = date.today().isoformat()
    raw.to_csv(folder / f"kosis_{TBL_ID}_{stamp}.csv", index=False)
    meta = {
        "orgId": ORG_ID,
        "tblId": TBL_ID,
        "itmId": ITEM,
        "period": [START, END],
        "fetched": stamp,
    }
    (folder / f"kosis_{TBL_ID}_{stamp}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2)
    )


def build_panel(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.rename(
        columns={"C1": "region_id", "C2": "industry", "PRD_DE": "period", "DT": "value"}
    )
    df = df[df["industry"].isin(INDUSTRIES)].copy()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    year = df["period"].str[:4].astype(int)
    quarter = df["period"].str[-1].astype(int)
    df["quarter_idx"] = (year - 2019) * 4 + (quarter - 1)

    panel = (
        df.pivot_table(index=["region_id", "quarter_idx"], columns="industry", values="value")
        .rename(columns=INDUSTRIES)
        .reset_index()
    )
    panel.columns.name = None

    # 받은 그대로가 계획과 맞는지 확인한 뒤에 가공한다.
    expected = {(r, q) for r in REGIONS for q in range(N_QUARTERS)}
    got = set(zip(panel["region_id"], panel["quarter_idx"], strict=True))
    if got != expected:
        raise ValueError(
            f"지역×분기 불일치: 빠짐 {sorted(expected - got)[:5]}, 남음 {sorted(got - expected)[:5]}"
        )
    cols = list(INDUSTRIES.values())
    if panel[cols].isna().any().any() or (panel[cols] <= 0).any().any():
        raise ValueError("판매액지수에 결측 또는 0 이하 값이 있어 로그를 취할 수 없습니다")

    panel[cols] = np.log(panel[cols])
    panel["treated"] = panel["region_id"].isin(TREATED).astype(int)
    panel["region"] = panel["region_id"].map(REGIONS)

    # 2023Q1 전환 분기 제외 (계획서 time 주석). 재번호하지 않는다.
    panel = panel[panel["quarter_idx"] != TRANSITION].reset_index(drop=True)
    assert TRANSITION not in set(panel["quarter_idx"])
    assert len(panel) == len(REGIONS) * (N_QUARTERS - 1)
    return panel[["region_id", "region", "quarter_idx", "treated", *cols]]


def main() -> None:
    raw = download()
    save_raw(raw)
    panel = build_panel(raw)
    out = HERE / "data" / "panel.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(out, index=False)
    panel[panel["region_id"] != "26"].to_csv(HERE / "data" / "panel_no_ulsan.csv", index=False)
    print(f"[fetch] {len(panel)}행 → data/panel.csv (울산 제외본: data/panel_no_ulsan.csv)")


if __name__ == "__main__":
    main()
