"""추가 점검: 공용 흐름(make flow)이 자동으로 하지 않는 확인을 직접 계산해 data/extra_checks.csv 와 화면에 남깁니다.

  1. 비교 지역 하나씩 빼기
  2. 10월(7%로 복귀한 달)
  3. 가짜 시점(처치가 없던 달을 사후로 놓기)
  4. 도시를 바꿔치기한 순열(원주 대신 다른 지역을 처치로 놓고 같은 값을 계산)
  5. 비교 지역을 시(市)로만 줄이기
  6. 사전 기간 원주와 비교 지역의 차이 추이

먼저 fetch.py 를 실행해 data/panel_extended.csv 를 만들어야 합니다. 결과는 월 단위 2x2 이중차분의 평균 차이이며
공용 did 의 TWFE 추정과 같은 값을 줍니다(사전 3개월 · 사후 1개월, 균형 패널).

    python cases/whatfontisthis-wonju-voucher-202409/extra_checks.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
TREATED = "51130"
PRE = ["202406", "202407", "202408"]
POST = ["202409"]
Y = "log_mbl_use_amt"


def load() -> pd.DataFrame:
    df = pd.read_csv(HERE / "data" / "panel_extended.csv", dtype={"region_code": str})
    df["ym"] = pd.to_datetime(df.month_start).dt.strftime("%Y%m")
    return df


def wide(df: pd.DataFrame, col: str = Y) -> pd.DataFrame:
    return df.pivot(index="region_code", columns="ym", values=col)


def did(w: pd.DataFrame, treat: str, controls: list[str], pre: list[str], post: list[str]) -> float:
    d = w[post].mean(axis=1) - w[pre].mean(axis=1)
    return float(d[treat] - d[controls].mean())


def main() -> None:
    df = load()
    w = wide(df)
    names = df.drop_duplicates("region_code").set_index("region_code").region_name.to_dict()
    ctrl = [c for c in w.index if c != TREATED]
    rows: list[dict] = []

    def add(group: str, label: str, value: float, note: str = "", pct: bool = True) -> None:
        pct_val = round(float(np.expm1(value)) * 100, 1) if pct else None
        rows.append(
            {
                "점검": group,
                "내용": label,
                "값(로그차)": round(value, 4),
                "대략 %": pct_val,
                "메모": note,
            }
        )

    base = did(w, TREATED, ctrl, PRE, POST)
    add("기본", f"원주 vs 비교 {len(ctrl)}곳, 사전 6~8월, 사후 9월", base)
    add(
        "기본",
        "금액 대신 모바일 이용자 수(칸 합)",
        did(wide(df, "log_mbl_user_cnt"), TREATED, ctrl, PRE, POST),
    )

    for c in ctrl:
        add(
            "한 곳 빼기",
            f"{names[c]} 제외",
            did(w, TREATED, [x for x in ctrl if x != c], PRE, POST),
        )

    add(
        "10월(복귀)",
        "사후를 10월로 (원주는 7%로 복귀)",
        did(w, TREATED, ctrl, PRE, ["202410"]),
        "복귀 뒤 평균 차이도 0 근처인지 본다",
    )

    for post, pre in [("202408", ["202406", "202407"]), ("202407", ["202406"])]:
        add(
            "가짜 시점",
            f"사후={post}, 사전={'·'.join(pre)}",
            did(w, TREATED, ctrl, pre, [post]),
            "처치 없는 달",
        )

    perm = {t: did(w, t, [c for c in w.index if c != t], PRE, POST) for t in w.index}
    for t, v in perm.items():
        add("바꿔치기", f"{names[t]}를 처치로 놓음", v)
    p = float(np.mean([abs(v) >= abs(perm[TREATED]) for v in perm.values()]))
    add(
        "바꿔치기",
        f"원주보다 절댓값이 크거나 같은 비율(양측, {len(perm)}곳 중)",
        p,
        "작은 표본이라 최소 1/8",
        pct=False,
    )

    cities = [c for c in ctrl if names[c].endswith("시")]
    add(
        "시만",
        f"비교를 시 {len(cities)}곳으로 줄임 ({', '.join(names[c].split()[-1] for c in cities)})",
        did(w, TREATED, cities, PRE, POST),
    )

    gap = (w.loc[TREATED] - w.loc[ctrl].mean()).round(3)
    for ym, v in gap.items():
        add(
            "격차 추이",
            f"{ym} 원주 - 비교 평균",
            float(v),
            "1~5월은 원주 정책이 달마다 바뀐 기간",
            pct=False,
        )

    out = pd.DataFrame(rows)
    (HERE / "data").mkdir(exist_ok=True)
    out.to_csv(HERE / "data" / "extra_checks.csv", index=False)
    with pd.option_context("display.max_colwidth", 80, "display.width", 200):
        print(out.to_string(index=False))


if __name__ == "__main__":
    main()
