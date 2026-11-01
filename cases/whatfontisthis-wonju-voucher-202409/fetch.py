"""② 수집: 원주 + 비교 시군 × 월(모바일 상품권 결제금액) → data/panel.csv

공공데이터포털 한국조폐공사 두 API를 씁니다. 키는 .env 의 DATA_GO_KR_API_KEY(Decoding 키)이며 커밋하지 않습니다.
- 판매정책정보 /B190001/salesPolicy/cardMobile : 지역·일별 할인율과 월 구매한도 (카드·모바일 합본, 조폐공사 운영 지역만)
- 결제정보 /B190001/localGiftsPaymentV3/paymentsV3 : 지역·월·성별·연령대·읍면동별 결제 (월 단위뿐이고 일·주 조회는 없음)

비교 시군은 결과를 보지 않고 아래 세 규칙만으로 고릅니다.
  R1 정책 안정: 2024-06-01~09-30에 할인율·월 구매한도가 한 가지뿐(0%인 날은 월말 기록 공백이라 제외)
  R2 자료 충분: 2024-01~10 모든 달 모바일 결제금액이 있고 매달 1억 원 이상
  R3 급변 없음: 2024-01~10 인접한 달 사이 로그 변화가 0.5 이하
고른 결과와 탈락 이유는 data/selection.csv 에 남깁니다.

산출물 (모두 data/ 아래, git에 올라가지 않음)
  panel.csv           분석 표: 2024-06~09, 한 행 = 시군 × 월
  panel_extended.csv  참고 표: 2024-01~10 (추가 점검용)
  selection.csv       82개 지역의 규칙 통과 여부
  policy_history.csv  선택된 지역의 6~9월 일별 정책 기록

    python cases/whatfontisthis-wonju-voucher-202409/fetch.py     (처음에는 약 5~10분, 이후에는 data/raw 의 저장본을 씁니다)
"""

from __future__ import annotations

import json
import math
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
RAW = HERE / "data" / "raw"
OUT = HERE / "data"

POLICY_URL = "https://apis.data.go.kr/B190001/salesPolicy/cardMobile"
PAY_URL = "https://apis.data.go.kr/B190001/localGiftsPaymentV3/paymentsV3"

TREATED = "51130"  # 원주시
POLICY_FROM, POLICY_TO = "20240501", "20241031"
PRE_START, POST_END = "20240601", "20240930"
MONTHS_EXT = [f"2024{m:02d}" for m in range(1, 11)]
MONTHS_MAIN = ["202406", "202407", "202408", "202409"]
MIN_MONTHLY_WON = 1e8
MAX_ABS_LOG_JUMP = 0.5


def _key() -> str:
    key = os.environ.get("DATA_GO_KR_API_KEY", "").strip()
    if not key:
        env = HERE.parents[1] / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("DATA_GO_KR_API_KEY="):
                    key = line.split("=", 1)[1].strip()
    if not key:
        raise SystemExit(
            "DATA_GO_KR_API_KEY 가 없습니다. .env 에 공공데이터포털 Decoding 인증키를 넣어 주세요."
        )
    return urllib.parse.unquote(key) if "%" in key else key


def _call(url: str, params: dict) -> dict:
    q = {**params, "serviceKey": _key(), "returnType": "JSON"}
    last: Exception | None = None
    for _ in range(4):
        try:
            with urllib.request.urlopen(url + "?" + urllib.parse.urlencode(q), timeout=60) as r:
                return json.load(r)
        except Exception as e:  # 일시 오류는 다시 시도
            last = e
            time.sleep(2)
    raise RuntimeError(f"API 호출 실패: {last}")


def _cached(name: str, loader):
    path = RAW / name
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    data = loader()
    RAW.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def _paged(url: str, params: dict, size_key: str, page_key: str) -> list[dict]:
    rows, page = [], 1
    while True:
        d = _call(url, {**params, page_key: page, size_key: 1000})
        rows += d["data"]
        if not d["data"] or len(rows) >= d["matchCount"]:
            return rows
        page += 1


def policy_for(region: str) -> list[dict]:
    def load():
        rows = _paged(POLICY_URL, {"cond[usage_rgn_cd::EQ]": region}, "perPage", "page")
        return [r for r in rows if POLICY_FROM <= r["crtr_ymd"] <= POLICY_TO]

    return _cached(f"policy_{region}.json", load)


def payments_for(region: str) -> list[dict]:
    def load():
        p = {
            "cond[usage_rgn_cd::EQ]": region,
            "cond[crtr_ym::GTE]": "202401",
            "cond[crtr_ym::LTE]": "202412",
        }
        return _paged(PAY_URL, p, "perPage", "page")

    return _cached(f"pay_{region}.json", load)


def list_regions() -> list[str]:
    """조폐공사가 정책을 기록한 지역 목록(2024-07-15 하루치로 확인)."""

    def load():
        d = _call(POLICY_URL, {"cond[crtr_ymd::EQ]": "20240715", "page": 1, "perPage": 500})
        return sorted({r["usage_rgn_cd"] for r in d["data"]})

    return _cached("regions.json", load)


def monthly_mobile(rows: list[dict]) -> pd.DataFrame:
    """성별·연령·읍면동 행을 월 단위로 합칩니다. 모바일 금액과 모바일 이용자 수(칸 합)를 씁니다."""
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["crtr_ym", "mbl_use_amt", "mbl_user_cnt"])
    for c in ("mbl_use_amt", "mbl_user_cnt"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.groupby("crtr_ym", as_index=False)[["mbl_use_amt", "mbl_user_cnt"]].sum(min_count=1)


def judge(region: str, policy: list[dict], monthly: pd.DataFrame) -> dict:
    pv = {
        (r["dscnt_rt"], r["mm_prchs_lmt_amt"])
        for r in policy
        if PRE_START <= r["crtr_ymd"] <= POST_END and r["dscnt_rt"] != 0
    }
    amt = monthly.set_index("crtr_ym")["mbl_use_amt"] if len(monthly) else pd.Series(dtype=float)
    vals = [amt.get(m, np.nan) for m in MONTHS_EXT]
    complete = all(v > 0 for v in vals if not np.isnan(v)) and not any(np.isnan(v) for v in vals)
    r1 = len(pv) == 1
    r2 = complete and min(vals) >= MIN_MONTHLY_WON
    jump = (
        max((abs(math.log(b / a)) for a, b in zip(vals, vals[1:], strict=False)), default=np.nan)
        if complete
        else np.nan
    )
    r3 = bool(complete and jump <= MAX_ABS_LOG_JUMP)
    if region == TREATED:
        reason = "처치 도시"
    elif not r1:
        reason = f"R1 정책이 {len(pv)}가지로 바뀜"
    elif not r2:
        reason = "R2 달이 비거나 월 1억 원 미만"
    elif not r3:
        reason = "R3 인접 달 급변"
    else:
        reason = "적격"
    return {
        "region_code": region,
        "n_policy_types_jun_sep": len(pv),
        "min_monthly_mobile_won": None if not complete else min(vals),
        "max_abs_log_jump": jump,
        "R1": r1,
        "R2": bool(r2),
        "R3": r3,
        "result": reason,
    }


def build_panel() -> pd.DataFrame:
    names = pd.read_csv(HERE / "region_codes_komsco.csv", dtype=str).set_index("region_code")
    regions = list_regions()
    sel, monthlies, pol_all = [], {}, {}
    for i, rg in enumerate(regions, 1):
        pol = policy_for(rg)
        mon = monthly_mobile(payments_for(rg))
        monthlies[rg], pol_all[rg] = mon, pol
        row = judge(rg, pol, mon)
        nm = names.loc[rg] if rg in names.index else None
        row["region_name"] = f"{nm.sido} {nm.sigungu}" if nm is not None else ""
        sel.append(row)
        print(f"[fetch] {i}/{len(regions)} {rg} {row['region_name']} → {row['result']}", flush=True)
    selection = pd.DataFrame(sel)
    OUT.mkdir(parents=True, exist_ok=True)
    selection.to_csv(OUT / "selection.csv", index=False)

    keep = [TREATED, *selection.loc[selection.result == "적격", "region_code"].tolist()]
    if len(keep) - 1 < 5:
        raise SystemExit(
            f"적격 비교 지역이 {len(keep) - 1}곳뿐입니다. 5곳 미만이면 이 설계를 실행하지 않습니다."
        )

    hist = [r for rg in keep for r in pol_all[rg] if PRE_START <= r["crtr_ymd"] <= POST_END]
    pd.DataFrame(hist).sort_values(["usage_rgn_cd", "crtr_ymd"]).to_csv(
        OUT / "policy_history.csv", index=False
    )

    frames = []
    for rg in keep:
        m = monthlies[rg][monthlies[rg].crtr_ym.isin(MONTHS_EXT)].copy()
        m["region_code"] = rg
        m["region_name"] = selection.set_index("region_code").loc[rg, "region_name"]
        frames.append(m)
    ext = pd.concat(frames, ignore_index=True)
    ext["month_start"] = pd.to_datetime(ext.crtr_ym + "01").dt.strftime("%Y-%m-%d")
    ext["month_idx"] = (ext.crtr_ym.str[4:].astype(int) - 6).astype(
        int
    )  # 2024-06 = 0, 2024-01 = -5
    ext["treated"] = (ext.region_code == TREATED).astype(int)
    ext["log_mbl_use_amt"] = np.log1p(ext.mbl_use_amt)
    ext["log_mbl_user_cnt"] = np.log1p(ext.mbl_user_cnt)
    cols = [
        "region_code", "region_name", "treated", "month_start", "month_idx",
        "mbl_use_amt", "log_mbl_use_amt", "mbl_user_cnt", "log_mbl_user_cnt",
    ]  # fmt: skip
    ext = ext[cols].sort_values(["region_code", "month_idx"])
    ext.to_csv(OUT / "panel_extended.csv", index=False)
    return ext[ext.month_idx.between(0, 3)].reset_index(drop=True)


def main() -> None:
    panel = build_panel()
    OUT.mkdir(parents=True, exist_ok=True)
    panel.to_csv(OUT / "panel.csv", index=False)
    n = panel.region_code.nunique()
    print(f"[fetch] {len(panel)}행 → data/panel.csv (원주 1 + 비교 {n - 1}곳 × 4개월)")


if __name__ == "__main__":
    main()
