"""날짜·시각을 분석용 정수 시점 인덱스로 바꾸는 도우미 — 연·분기·월·주·일·시간 공통.

plan.yaml 의 time.col 은 정수여야 합니다(0, 1, 2 …). fetch.py 에서 이렇게 만듭니다.

    from core.schema.timeindex import period_index, index_of, hour_of_day
    df["t"] = period_index(df["측정일시"], "hour", origin="2019-01-01 00:00")   # 0 = 2019-01-01 00시
    df["hour"] = hour_of_day(df["측정일시"])                                     # 0~23
    index_of("2019-12-01 06:00", "hour", origin="2019-01-01 00:00")              # → treat_time

새 단위를 지원하려면 PANDAS_FREQ 에 한 줄 추가하고 plan.py 의 Freq 에 같은 이름을 넣습니다.
"""

from __future__ import annotations

import pandas as pd

PANDAS_FREQ = {"year": "Y", "quarter": "Q", "month": "M", "week": "W", "day": "D", "hour": "h"}


def _freq(freq: str) -> str:
    if freq not in PANDAS_FREQ:
        raise ValueError(f"지원하지 않는 시간 단위: {freq} (가능: {list(PANDAS_FREQ)})")
    return PANDAS_FREQ[freq]


def period_index(values, freq: str, origin) -> pd.Series:
    """날짜·시각 → origin 기준 정수 시점 (origin 이 속한 기간 = 0)."""
    f = _freq(freq)
    ts = pd.to_datetime(pd.Series(values))
    o = pd.Timestamp(origin).to_period(f)
    return ts.dt.to_period(f).map(lambda p: (p - o).n).astype("int64")


def index_of(when, freq: str, origin) -> int:
    """정책 시작일 같은 한 시점 → 정수 시점 (treat_time 에 그대로 씁니다)."""
    f = _freq(freq)
    return int((pd.Timestamp(when).to_period(f) - pd.Timestamp(origin).to_period(f)).n)


def hour_of_day(values) -> pd.Series:
    """날짜·시각 → 하루 중 시각(0~23). '24시' 표기(에어코리아 등)는 다음 날 0시로 읽습니다."""
    s = pd.Series(values).astype(str)
    fixed = s.str.replace(r"\s?24(?::00)?$", " 00:00", regex=True)
    ts = pd.to_datetime(fixed, errors="coerce")
    bump = s.str.contains(r"\s?24(?::00)?$", regex=True)
    ts = ts.where(~bump, ts + pd.Timedelta(days=1))
    return ts.dt.hour.astype("Int64")


def in_window(hours: pd.Series, window: tuple[int, int]) -> pd.Series:
    """active_hours=[시작, 끝) 안에 드는 행."""
    a, b = window
    return (hours >= a) & (hours < b)
