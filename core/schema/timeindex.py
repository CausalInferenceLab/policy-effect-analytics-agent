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


_H24 = r"\s24(?::00){0,2}$"  # '... 24', '... 24:00', '... 24:00:00' (분·초가 24인 경우는 해당 없음)


def to_timestamp(values) -> pd.Series:
    """날짜·시각 문자열 → Timestamp. 에어코리아처럼 'YYYYMMDDHH'(10자리)·'24시' 표기는 다음 날 0시로 읽고,
    읽지 못한 값은 NaT 로 둡니다."""
    s = pd.Series(values).astype("string").str.strip()
    ten = s.str.fullmatch(r"\d{10}").fillna(False)
    s = s.where(~ten, s.str[:8] + " " + s.str[8:10] + ":00")
    is24 = s.str.contains(_H24, regex=True).fillna(False)
    s = s.str.replace(_H24, " 00:00", regex=True)
    ts = pd.to_datetime(s, errors="coerce", format="mixed")
    return ts.where(~is24, ts + pd.Timedelta(days=1))


def period_index(values, freq: str, origin) -> pd.Series:
    """날짜·시각 → origin 기준 정수 시점 (origin 이 속한 기간 = 0). 읽을 수 없는 값이 있으면 오류."""
    f = _freq(freq)
    ts = to_timestamp(values)
    if ts.isna().any():
        bad = pd.Series(values)[ts.isna().values].astype(str).head(3).tolist()
        raise ValueError(f"날짜로 읽을 수 없는 값 {int(ts.isna().sum())}개 (예: {bad})")
    o = pd.Timestamp(origin).to_period(f)
    return ts.dt.to_period(f).map(lambda p: (p - o).n).astype("int64")


def index_of(when, freq: str, origin) -> int:
    """정책 시작일 같은 한 시점 → 정수 시점 (treat_time 에 그대로 씁니다)."""
    f = _freq(freq)
    ts = to_timestamp([when]).iloc[0]
    return int((ts.to_period(f) - pd.Timestamp(origin).to_period(f)).n)


def hour_of_day(values) -> pd.Series:
    """날짜·시각 → 하루 중 시각(0~23). '24시' 표기는 다음 날 0시. 읽지 못하면 <NA>."""
    return to_timestamp(values).dt.hour.astype("Int64")


def hours_numeric(values) -> pd.Series:
    """시각 컬럼을 숫자로 (문자열 '06' 등 허용). 읽을 수 없으면 NaN."""
    return pd.to_numeric(pd.Series(values), errors="coerce")


def in_window(hours, window: tuple[int, int]) -> pd.Series:
    """active_hours=[시작, 끝) 안에 드는 행. 시작 > 끝이면 자정을 넘는 시간대(예: [22, 6] = 22시~05시).
    시각이 비어 있는 행은 False."""
    h = hours_numeric(hours)
    a, b = window
    inside = (h >= a) & (h < b) if a < b else (h >= a) | (h < b)
    return inside & h.notna()
