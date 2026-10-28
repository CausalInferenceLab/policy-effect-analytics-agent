"""학습기만으로 링크·요일·시간별 저속 임계값을 만들고 미래의 결측을 보존해 적용한다."""

import numpy as np
import pandas as pd

LEVELS = {"link_weekday_hour": ["link_id", "weekday", "hour"], "link_hour": ["link_id", "hour"], "link": ["link_id"]}


def keys(frame):
    return pd.DataFrame({"link_id": frame.link_id.to_numpy(), "weekday": frame.target_start.dt.dayofweek.to_numpy(),
                         "hour": frame.target_start.dt.hour.to_numpy()})


def fit_thresholds(train, cfg):
    dates = train.target_start.dt.strftime("%Y-%m-%d")
    if train.empty or not dates.between(*cfg["threshold_training"]).all():
        raise ValueError("저속 임계값은 지정 학습 기간의 자료만 사용합니다")
    if "split" in train and not train.split.eq("train").all():
        raise ValueError("학습 외 분할을 저속 임계값에 사용할 수 없습니다")
    if not np.isfinite(train.speed_kmh).all() or train.speed_kmh.le(0).any():
        raise ValueError("저속 임계값 학습 속도는 유한한 양수여야 합니다")
    if not 0 < cfg["quantile"] < 1 or cfg["minimum_threshold_observations"] < 2:
        raise ValueError("저속 분위수·최소 표본 설정 오류")
    frame = keys(train).assign(speed_kmh=train.speed_kmh.to_numpy())
    tables = []
    for level in cfg["threshold_groups"]:
        grouped = frame.groupby(LEVELS[level], sort=True).speed_kmh
        table = grouped.count().rename("observations").to_frame()
        table["threshold"] = grouped.quantile(cfg["quantile"], interpolation=cfg["quantile_interpolation"])
        table = table.reset_index().assign(level=level)
        for field in ["weekday", "hour"]:
            if field not in table:
                table[field] = -1
        table["eligible"] = table.observations.ge(cfg["minimum_threshold_observations"])
        tables.append(table[["level", "link_id", "weekday", "hour", "observations", "threshold", "eligible"]])
    return pd.concat(tables, ignore_index=True)


def attach(frame, thresholds, cfg):
    lookup_keys = keys(frame)
    cutoffs = np.full(len(frame), np.nan)
    source = np.full(len(frame), "uncovered", dtype=object)
    for level in cfg["threshold_groups"]:
        fields = LEVELS[level]
        selected = thresholds[thresholds.level.eq(level) & thresholds.eligible.eq(True)]
        if selected.duplicated(fields).any():
            raise ValueError("저속 임계값의 학습 집단 키 중복")
        index = (pd.Index(lookup_keys[fields[0]], name=fields[0]) if len(fields) == 1
                 else pd.MultiIndex.from_frame(lookup_keys[fields]))
        candidates = selected.set_index(fields).threshold.reindex(index).to_numpy()
        fill = np.isnan(cutoffs) & np.isfinite(candidates)
        cutoffs[fill], source[fill] = candidates[fill], level
    if not np.isfinite(cutoffs).all() or np.any(cutoffs <= 0):
        raise ValueError("학습 임계값이 없는 링크를 다른 도로로 대체하지 않습니다")
    result = frame.copy()
    result["calendar_q20_threshold"] = cutoffs
    result["calendar_q20_threshold_level"] = source
    result[cfg["target_name"]] = np.where(frame.speed_kmh.notna(), frame.speed_kmh.to_numpy() < cutoffs, np.nan)
    return result
