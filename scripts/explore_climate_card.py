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
# (노선, 역들, 시군, 첫 처치일 또는 None=대조). 대조는 분석 창(~2025-12)에 편입되지 않은 경기 출퇴근 노선 역.
# 군포·의정부·인천·구리·남양주·부천은 적용일 미확인이라 제외. 양평·가평·여주(나들이 노선)도 대조에서 제외.
STATIONS = [
    ("일산선", "대곡 대화 마두 백석 삼송 원당 원흥 정발산 주엽 화정", "고양", "2024-11-30"),
    ("3호선", "지축", "고양", "2024-11-30"),
    ("경의선", "행신 강매 화전 능곡 곡산 백마 풍산 일산 탄현", "고양", "2024-11-30"),
    ("과천선", "선바위 경마공원 대공원 과천 정부과천청사", "과천", "2024-11-30"),
    ("분당선", "야탑 이매 서현 수내 정자 미금 오리 모란 태평 가천대", "성남", "2025-05-03"),
    ("경강선", "판교 이매", "성남", "2025-05-03"),
    ("5호선", "미사 하남풍산 하남시청(덕풍·신장) 하남검단산", "하남", "2025-08-09"),
    ("과천선", "인덕원 평촌 범계", "안양", None),
    ("경부선", "안양 명학 석수 관악", "안양", None),
    ("경부선", "의왕 성균관대", "의왕", None),
    ("경부선", "화서 수원 세류", "수원", None),
    ("경부선", "병점 세마 서동탄", "화성", None),
    ("경부선", "오산대 오산 진위", "오산", None),
    ("경부선", "송탄 서정리 평택지제 평택", "평택", None),
    ("분당선", "죽전 보정 구성 신갈 기흥 상갈 청명", "용인", None),
    ("분당선", "영통 망포 매탄권선 수원시청 매교 수원", "수원", None),
    ("경강선", "삼동 경기광주 초월 곤지암", "광주", None),
    ("경강선", "신둔도예촌 이천 부발", "이천", None),
    ("경의선", "야당 운정 금릉 금촌 월롱 파주 문산", "파주", None),
    ("경원선", "양주 덕계 덕정 지행 동두천중앙 보산 동두천 소요산", "양주·동두천", None),
    ("안산선", "반월 상록수 한대앞 중앙 고잔 초지 안산 신길온천 정왕 오이도", "안산·시흥", None),
    ("수인선", "월곶 달월 사리 야목 어천 오목천 고색", "시흥·화성·수원", None),
]
SAME_LINE = {
    "고양": ["파주", "양주·동두천"],
    "과천": ["안양"],
    "성남": ["용인", "수원"],
    "하남": None,
}


def station_table() -> pd.DataFrame:
    rows = [(line, s, city, ft) for line, sts, city, ft in STATIONS for s in sts.split()]
    return pd.DataFrame(rows, columns=["line", "station", "city", "first_treat"])


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
