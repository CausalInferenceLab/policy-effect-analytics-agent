"""② 수집: 성남 처치 역 + 용인·수원 대조 역 × 주(평일 하루 평균 승하차) → data/panel.csv

- 서울 열린데이터광장 OA-12914 월별 파일을 core/adapters/seoul_subway.py 로 받습니다(키 불필요).
  받은 원자료는 레포 루트 data/raw/subway/ 에 남아 다음 실행과 scripts/explore_climate_card.py 가 재사용합니다.
- 역 처치표: catalog/lineage/data/climate-card-stations.csv (데이터 계보의 결과물 파일)
- 평일 = 월~금 중 공휴일(holidays 패키지) 제외. 평일이 3일 미만인 주와, 분석 창 전체에 관측되지 않는 역은 뺍니다.
- 적용일(2025-05-03 토)이 걸친 주(t=121)는 전환 주로 뺍니다.

    pip install -e ".[analysis]"   # holidays
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from core.adapters.seoul_subway import SeoulSubwayDailyAdapter  # noqa: E402
from core.adapters.synthetic import SyntheticAdapter  # noqa: E402

W0 = pd.Timestamp("2023-01-02")  # t = 0 인 주(월요일)
START_T, END_T, TRANSITION = 96, 147, 121
TREATED_CITY, CONTROL_CITIES = "성남", ["용인", "수원"]
STATIONS = ROOT / "catalog" / "lineage" / "data" / "climate-card-stations.csv"


def weekday_panel(daily: pd.DataFrame, stations: pd.DataFrame) -> pd.DataFrame:
    import holidays

    kr = holidays.KR(years=range(2023, 2027))
    d = daily.merge(stations, on=["line", "station"])
    d = d[(d.date.dt.weekday < 5) & (~d.date.dt.date.isin(kr))]
    d["week"] = d.date.dt.to_period("W-SUN").dt.start_time
    p = (
        d.groupby(["line", "station", "city", "week"])
        .agg(on=("on", "mean"), off=("off", "mean"), n=("date", "nunique"))
        .reset_index()
    )
    p = p[p.n >= 3]
    p["t"] = ((p.week - W0).dt.days // 7).astype(int)
    p = p[(p.t >= START_T) & (p.t <= END_T) & (p.t != TRANSITION)]
    full = p.groupby(["line", "station"]).t.nunique()
    keep = full[full == full.max()].index
    p = p.set_index(["line", "station"]).loc[keep].reset_index()
    p["sid"] = p.line + "|" + p.station
    p["treated"] = (p.city == TREATED_CITY).astype(int)
    p["log_on"] = np.log(p.on.clip(lower=1))
    p["log_off"] = np.log(p.off.clip(lower=1))
    p["week"] = p.week.dt.strftime("%Y-%m-%d")
    return p.sort_values(["sid", "t"])[
        ["sid", "line", "station", "city", "treated", "week", "t", "on", "off", "log_on", "log_off"]
    ]


def main():
    st = pd.read_csv(STATIONS, dtype=str)
    st = st[st.city.isin([TREATED_CITY, *CONTROL_CITIES])][["line", "station", "city"]]
    ad = SeoulSubwayDailyAdapter()
    daily = ad.fetch("2024-11", "2025-11", cache_dir=ROOT / "data" / "raw" / "subway")
    panel = weekday_panel(daily, st)
    out = SyntheticAdapter()
    out.meta = ad.meta
    path = out.save(
        panel.reset_index(drop=True),
        HERE / "data" / "panel.csv",
        {"start": "2024-11", "end": "2025-11", "stations": str(STATIONS.relative_to(ROOT))},
    )
    n_t = panel[panel.treated == 1].sid.nunique()
    n_c = panel[panel.treated == 0].sid.nunique()
    print(f"패널 저장: {path.relative_to(HERE)} ({len(panel)}행, 처치 {n_t}역 · 대조 {n_c}역)")


if __name__ == "__main__":
    main()
