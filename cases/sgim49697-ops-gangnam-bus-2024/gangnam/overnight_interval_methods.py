"""예측 원점 이전에 이용 가능한 잔차만 사용해 고정·이동 창의 분위수 구간을 확장한다."""

import numpy as np
import pandas as pd

KEYS = ["link_id", "target_start", "origin"]
VALUES = ["speed_kmh", "q10", "q50", "q90"]


def scores(frame):
    if frame.empty or frame.duplicated(KEYS).any() or not np.isfinite(frame[VALUES].to_numpy()).all():
        raise ValueError("구간 보정 입력은 비어 있지 않고 중복·비유한 값이 없어야 합니다")
    if (frame.q10 > frame.q50).any() or (frame.q50 > frame.q90).any():
        raise ValueError("교차한 분위수를 보정으로 숨기지 않습니다")
    for name in ["target_start", "origin"]:
        if (not pd.api.types.is_datetime64_any_dtype(frame[name]) or frame[name].isna().any()
                or str(frame[name].dt.tz) not in {"None", "Asia/Seoul"}):
            raise ValueError("구간 보정 시각은 결측 없는 KST 지역 시각이어야 합니다")
    if str(frame.origin.dt.tz) != str(frame.target_start.dt.tz):
        raise ValueError("목표·원점 시간대가 다릅니다")
    if (frame.origin > frame.target_start).any():
        raise ValueError("예측 원점이 목표 구간 시작보다 늦습니다")
    return np.maximum(frame.q10.to_numpy() - frame.speed_kmh.to_numpy(), frame.speed_kmh.to_numpy() - frame.q90.to_numpy())


def local_times(values):
    """명시된 서울 시간대는 유지한 채 내부 순위 검색에만 지역 시각 배열을 쓴다."""
    local = values.dt.tz_localize(None) if values.dt.tz is not None else values
    return local.to_numpy(dtype="datetime64[ns]")


def expansion(values, coverage):
    values = np.asarray(values, dtype=float)
    if not 0 < coverage < 1 or not len(values) or not np.isfinite(values).all():
        raise ValueError("보정 점수 또는 목표 포함률이 잘못됐습니다")
    rank = int(np.ceil((len(values) + 1) * coverage))
    if rank > len(values):
        raise ValueError("유한한 보정 순위를 만들기에 점수가 부족합니다")
    return max(0., float(np.partition(values, rank - 1)[rank - 1]))


def adjust(targets, static, warmup, cfg, variant):
    """이미 본 시험의 순차 재생이며 미래 점수가 앞선 구간을 바꾸지 않도록 시간 관문을 적용한다."""
    scores(targets)
    static_scores = scores(static)
    scores(warmup)
    if len({str(frame.target_start.dt.tz) for frame in [targets, static, warmup]}) != 1:
        raise ValueError("보정 입력 사이의 시간대가 다릅니다")
    minimum, coverage = cfg["minimum_group_scores"], cfg["target_coverage"]
    delay = variant["delay_hours"]
    if delay < 2 or minimum < 4 or cfg["rolling_days"] <= 0:
        raise ValueError("보정 지연·최소 표본·이동 창 설정 오류")
    if variant["mode"] not in {"raw", "static", "rolling"} or variant["grouping"] not in {"global", "link_band"}:
        raise ValueError("알 수 없는 보정 방식·집단")
    delta_time = np.timedelta64(delay, "h")
    origins = local_times(targets.origin)
    stime = local_times(static.target_start)
    if len(static) < minimum or stime.max() + delta_time > origins.min():
        raise ValueError("고정 보정 점수가 부족하거나 예측 원점에 아직 공개되지 않았습니다")
    output = targets.copy()
    n = len(targets)
    changes = np.zeros(n)
    counts = np.zeros(n, dtype=int)
    latest = np.full(n, np.datetime64("NaT", "ns"), dtype="datetime64[ns]")
    sources = np.full(n, "raw", dtype=object)
    if variant["mode"] != "raw":
        global_static = (expansion(static_scores, coverage), len(static_scores), stime.max() + delta_time)
        links = targets.link_id.to_numpy()
        evening = targets.target_start.dt.hour.isin([17, 18, 19]).to_numpy()
        slinks = static.link_id.to_numpy()
        sevening = static.target_start.dt.hour.isin([17, 18, 19]).to_numpy()
        static_groups = {}
        for link in np.unique(links):
            for band in [False, True]:
                mask = (slinks == link) & (sevening == band)
                if mask.sum() >= minimum:
                    static_groups[(link, band)] = (expansion(static_scores[mask], coverage), int(mask.sum()), stime[mask].max() + delta_time)
        pool = pd.concat([warmup, targets], ignore_index=True).sort_values("target_start", kind="stable")
        pscore = scores(pool)
        ptime = local_times(pool.target_start)
        plinks = pool.link_id.to_numpy()
        pevening = pool.target_start.dt.hour.isin([17, 18, 19]).to_numpy()
        lookback = np.timedelta64(cfg["rolling_days"], "D")
        for index, origin in enumerate(origins):
            chosen, source = global_static, "static_global"
            if variant["mode"] == "static":
                if variant["grouping"] == "link_band" and (links[index], evening[index]) in static_groups:
                    chosen, source = static_groups[(links[index], evening[index])], "static_link_band"
            else:
                start = np.searchsorted(ptime, origin - lookback, side="left")
                end = np.searchsorted(ptime, origin - delta_time, side="right")
                values, times = pscore[start:end], ptime[start:end]
                if len(values) >= minimum:
                    source = "rolling_global"
                    if variant["grouping"] == "link_band":
                        mask = (plinks[start:end] == links[index]) & (pevening[start:end] == evening[index])
                        if mask.sum() >= minimum:
                            values, times, source = values[mask], times[mask], "rolling_link_band"
                    chosen = (expansion(values, coverage), len(values), times.max() + delta_time)
            changes[index], counts[index], latest[index] = chosen
            sources[index] = source
        if np.any(latest > origins):
            raise ValueError("보정 점수에 예측 원점 이후 공개된 실제값이 섞였습니다")
    output["q10"] = output.q10 - changes
    output["q90"] = output.q90 + changes
    output["expansion"] = changes
    output["calibration_scores"] = counts
    output["calibration_source"] = sources
    output["latest_label_available_at"] = pd.DatetimeIndex(latest).tz_localize(targets.origin.dt.tz)
    return output
