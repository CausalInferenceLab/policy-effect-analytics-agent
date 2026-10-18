"""기후동행카드 탐색 분석 — docs/strategy/climate-card.md 6절의 숫자를 다시 만듭니다.

    pip install -e ".[analysis]"                      # 공휴일 달력(holidays)
    python scripts/explore_climate_card.py            # 2023-01 ~ 2026-09 역×일 자료를 data/raw/subway/ 에 받아 분석
    python scripts/explore_climate_card.py --offline  # 이미 받은 파일만 사용

주의: 결과를 보고 만든 탐색 분석입니다(사전 등록 아님). 확인용 분석은 cases/<내ID>-<주제>/ 에
plan.yaml 을 먼저 커밋하고 돌리세요. 받은 원자료(data/raw/)는 커밋되지 않습니다.
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")

from core.adapters.seoul_subway import SeoulSubwayDailyAdapter  # noqa: E402
from core.estimators import did, event_study  # noqa: E402

W0 = pd.Timestamp("2023-01-02")
# 역 처치표(노선·역·시군·첫 처치일)는 계보의 결과물 파일 하나에서 읽습니다 — 케이스 fetch.py 와 같은 원천.
# 대조는 분석 창(~2025-12)에 편입되지 않은 경기 출퇴근 노선 역. 군포·의정부·인천·구리·남양주·부천은
# 적용일 미확인이라 제외, 양평·가평·여주(나들이 노선)도 제외. 근거: catalog/lineage/climate-card-expansion.yaml
STATIONS_CSV = ROOT / "catalog" / "lineage" / "data" / "climate-card-stations.csv"
SAME_LINE = {
    "고양": ["파주", "양주·동두천"],
    "과천": ["안양"],
    "성남": ["용인", "수원"],
    "하남": None,
}


def station_table() -> pd.DataFrame:
    t = pd.read_csv(STATIONS_CSV, dtype=str)
    t["first_treat"] = t["first_treat"].where(t["group"] == "treated")
    return t[["line", "station", "city", "first_treat"]]


def weekday_panel(daily: pd.DataFrame) -> pd.DataFrame:
    """역 × 주: 평일(공휴일 제외) 하루 평균 승차."""
    import holidays

    kr = holidays.KR(years=range(2023, 2027))
    d = daily.merge(station_table(), on=["line", "station"])
    d = d[(d.date.dt.weekday < 5) & (~d.date.dt.date.isin(kr))]
    d["sid"] = d.line + "|" + d.station
    d["week"] = d.date.dt.to_period("W-SUN").dt.start_time
    p = (
        d.groupby(["sid", "city", "first_treat", "week"], dropna=False)
        .agg(on=("on", "mean"), n=("date", "nunique"))
        .reset_index()
    )
    p = p[p.n >= 3]
    p["t"] = ((p.week - W0).dt.days // 7).astype(int)
    p["log_on"] = np.log(p.on.clip(lower=1))
    return p


def cohort(p: pd.DataFrame, city: str, date: str, controls: list[str] | None) -> dict:
    k = int((pd.Timestamp(date).to_period("W-SUN").start_time - W0).days // 7)
    tt = k + 1  # 토요일 시작 → 그 주는 전환 주로 빼고 다음 주부터 처치
    ctrl = p[p.first_treat.isna()] if controls is None else p[p.city.isin(controls)]
    x = pd.concat([p[p.city == city], ctrl])
    x = x[(x.t >= tt - 26) & (x.t <= tt + 25) & (x.t != k)].copy()
    cnt = x.groupby("sid").t.nunique()
    x = x[x.sid.isin(cnt[cnt == cnt.max()].index)]
    x["treated"] = (x.city == city).astype(int)
    es = event_study(
        x,
        "log_on",
        "sid",
        "t",
        "treated",
        treat_time=tt,
        cluster="sid",
        ref_period=-2,
        window=(-12, 12),
    )
    dd = did(x, "log_on", "sid", "t", "treated", treat_time=tt, cluster="sid")
    return {
        "처치역": x[x.treated == 1].sid.nunique(),
        "대조역": x[x.treated == 0].sid.nunique(),
        "DiD": dd.estimate,
        "CI": (dd.ci_low, dd.ci_high),
        "사전추세p": es.assumptions_checked["parallel_pretrends"]["p_value"],
    }


def pct(v: float) -> str:
    return f"{(np.exp(v) - 1) * 100:+.1f}%"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--cache", default=str(ROOT / "data" / "raw" / "subway"))
    a = ap.parse_args()
    ad = SeoulSubwayDailyAdapter()
    if a.offline:
        ad.file_list = lambda: {}  # 받지 않고 캐시만
    daily = ad.fetch("2023-01", "2026-09", cache_dir=a.cache)
    print(f"역×일 {len(daily):,}행, {daily.date.min():%Y-%m-%d} ~ {daily.date.max():%Y-%m-%d}")
    p = weekday_panel(daily)
    for city, date in [
        ("고양", "2024-11-30"),
        ("과천", "2024-11-30"),
        ("성남", "2025-05-03"),
        ("하남", "2025-08-09"),
    ]:
        r = cohort(p, city, date, SAME_LINE[city])
        print(
            f"{city} ({date}) 처치 {r['처치역']}역 vs 대조 {r['대조역']}역: DiD {pct(r['DiD'])} "
            f"[{pct(r['CI'][0])}, {pct(r['CI'][1])}] · 사전추세 p={r['사전추세p']:.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
