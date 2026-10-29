"""발행 시점에 공개된 월만 사용해 지연값·요일 시간 프로필을 만든다."""

import numpy as np
import pandas as pd

from .common import CASE, holiday_dates, sha256, utcnow, write_json
from .deepening_archive_data import MANIFEST, OUT, RAW, read_matrix, reference, verify

CALENDAR = ["link_id", "hour", "weekday", "month", "weekend", "korean_public_holiday"]
PROFILE_STATS = ["mean", "std", "q10", "q50", "q90", "count", "expected"]


def publication_clock(targets, horizon, releases, windows):
    origins = targets - pd.Timedelta(hours=horizon - 1)
    ordered = releases.sort_values()
    if ordered.index.duplicated().any() or ordered.isna().any():
        raise ValueError("공개 시계의 중복·누락 월")
    position = np.searchsorted(pd.DatetimeIndex(ordered).asi8, origins.asi8, side="right")
    clock = pd.DataFrame(dict(target_start=targets, origin=origins, publication_cursor=position), index=targets)
    choices, records = {}, []
    for cursor in sorted(set(position)):
        eligible = sorted(ordered.index[:cursor])
        for window in windows:
            months = tuple(eligible[-window:])
            choices[(cursor, window)] = months
            latest_release = releases.loc[list(months)].max() if months else pd.NaT
            earliest_origin = origins[position == cursor][0]
            if months and latest_release > earliest_origin:
                raise ValueError("아직 공개되지 않은 월을 프로필에 사용했습니다")
            records.append(dict(cursor=int(cursor), window=window, source_months=";".join(months),
                latest_required_release=latest_release, first_origin=earliest_origin,
                origins=int((position == cursor).sum())))
    return clock, choices, records


def month_profile(matrix, months):
    if not months:
        index = pd.MultiIndex.from_arrays([[], [], []], names=["link_id", "weekday", "hour"])
        return pd.DataFrame(index=index, columns=PROFILE_STATS, dtype=float)
    selected = matrix[matrix.index.strftime("%Y-%m").isin(months)]
    if not len(selected):
        raise ValueError("공개됐다고 지정한 프로필 월의 시간 격자가 없습니다")
    data = selected.rename_axis("source_hour").melt(ignore_index=False, var_name="link_id", value_name="speed").reset_index()
    data["weekday"], data["hour"] = data.source_hour.dt.dayofweek, data.source_hour.dt.hour
    groups = data.groupby(["link_id", "weekday", "hour"], observed=True).speed
    result = groups.agg(mean="mean", std="std", count="count", expected="size")
    quantiles = groups.quantile([.1, .5, .9], interpolation="linear").unstack(-1)
    quantiles.columns = ["q10", "q50", "q90"]
    return result.join(quantiles)[PROFILE_STATS]


def lag_values(series, targets, horizon, lag, releases):
    origins = targets - pd.Timedelta(hours=horizon - 1)
    source = targets - pd.Timedelta(hours=lag)
    if not (source + pd.Timedelta(hours=1) <= origins).all():
        raise ValueError("발행 시각 뒤에 끝나는 지연 특징")
    month = source.strftime("%Y-%m")
    publication = releases.reindex(month)
    available = np.array([not pd.isna(stamp) and stamp <= origin for stamp, origin in zip(publication, origins, strict=True)])
    values = series.reindex(source).to_numpy(dtype=float)
    values[~available] = np.nan
    return values, available.astype("int8")


def build_features(matrix, releases, horizon, cfg, holidays):
    expected = pd.date_range(matrix.index[0], matrix.index[-1], freq="h", tz=cfg["timezone"])
    if not matrix.index.equals(expected) or matrix.index.year.max() >= cfg["locked_year"]:
        raise ValueError("연속 시간 격자 또는 잠금 연도 오류")
    clock, choices, records = publication_clock(matrix.index, horizon, releases, cfg["profile_last_published_months"])
    profiles = {months: month_profile(matrix, months) for months in set(choices.values())}
    parts, quality = [], []
    for link in matrix:
        frame = pd.DataFrame(index=matrix.index)
        frame["link_id"] = link
        frame["hour"], frame["weekday"], frame["month"] = frame.index.hour, frame.index.dayofweek, frame.index.month
        frame["weekend"] = frame.weekday.ge(5).astype("int8")
        frame["korean_public_holiday"] = frame.index.strftime("%Y-%m-%d").isin(holidays).astype("int8")
        for lag in cfg["target_relative_lags_hours"]:
            values, available = lag_values(matrix[link], matrix.index, horizon, lag, releases)
            frame[f"archive_lag_{lag}"] = values
            frame[f"archive_available_{lag}"] = available
            if np.any(np.isfinite(values) & ~available.astype(bool)):
                raise ValueError("미공개 지연 특징에 값이 남았습니다")
        for window in cfg["profile_last_published_months"]:
            for statistic in PROFILE_STATS:
                frame[f"archive_profile_{window}_{statistic}"] = np.nan
            frame[f"archive_profile_{window}_months"] = 0
            frame[f"archive_profile_{window}_age_days"] = np.nan
            for cursor in sorted(clock.publication_cursor.unique()):
                positions = clock.publication_cursor.eq(cursor)
                months = choices[(cursor, window)]
                index = pd.MultiIndex.from_arrays([np.repeat(link, positions.sum()), frame.loc[positions, "weekday"],
                    frame.loc[positions, "hour"]], names=["link_id", "weekday", "hour"])
                values = profiles[months].reindex(index)
                for statistic in PROFILE_STATS:
                    frame.loc[positions, f"archive_profile_{window}_{statistic}"] = values[statistic].to_numpy()
                frame.loc[positions, f"archive_profile_{window}_months"] = len(months)
                if months:
                    end = (pd.Period(months[-1], freq="M") + 1).to_timestamp().tz_localize(cfg["timezone"])
                    age = (clock.loc[positions, "origin"] - end).dt.total_seconds() / 86400
                    frame.loc[positions, f"archive_profile_{window}_age_days"] = age
        frame["speed_kmh"] = matrix[link]
        frame["target_start"], frame["origin"] = frame.index, clock.origin
        frame["publication_cursor"] = clock.publication_cursor
        frame["split"] = "outside"
        for name, (start, end) in cfg["splits"].items():
            frame.loc[start:end, "split"] = name
        for col in frame.select_dtypes("float64"):
            frame[col] = frame[col].astype("float32")
        for split, data in frame.groupby("split", sort=True):
            quality.append(dict(horizon=horizon, link_id=link, split=split, expected=len(data), observed=int(data.speed_kmh.notna().sum()),
                profile1_present=int(data.archive_profile_1_q50.notna().sum()), profile3_present=int(data.archive_profile_3_q50.notna().sum()),
                **{f"lag{lag}_present": int(data[f"archive_lag_{lag}"].notna().sum()) for lag in cfg["target_relative_lags_hours"]}))
        parts.append(frame.reset_index(drop=True))
    return pd.concat(parts, ignore_index=True), pd.DataFrame(quality), pd.DataFrame(records)


def feature_sets(frame):
    return {"calendar_only": CALENDAR, "published_archive": CALENDAR + [c for c in frame if c.startswith("archive_")]}


def run():
    cfg, manifest = verify()
    if (OUT / "training_manifest.json").exists():
        raise ValueError("학습 시작 후 특징을 덮어쓸 수 없습니다")
    RAW.mkdir(parents=True, exist_ok=True)
    matrix, selected, exclusions = read_matrix(cfg, manifest)
    release = pd.read_csv(CASE / cfg["release_table"]).set_index("month")[cfg["release_scenario"]]
    releases = pd.to_datetime(release, utc=True).dt.tz_convert(cfg["timezone"])
    holidays = holiday_dates("2023-01-01", "2025-12-31")
    outputs, quality_tables, clocks = [], [], []
    for horizon in cfg["horizons"]:
        frame, quality, clock = build_features(matrix, releases, horizon, cfg, holidays)
        path = RAW / f"features_h{horizon}.parquet"
        frame.to_parquet(path, index=False)
        outputs.append(dict(horizon=horizon, **reference(path), rows=len(frame), feature_sets=feature_sets(frame)))
        quality_tables.append(quality)
        clocks.append(clock.assign(horizon=horizon))
        print(f"월별 공개 특징 h{horizon}: {len(frame):,}행·입력 {len(feature_sets(frame)['published_archive'])}열", flush=True)
    for name, data in [("feature_coverage.csv", pd.concat(quality_tables, ignore_index=True)),
                       ("publication_windows.csv", pd.concat(clocks, ignore_index=True))]:
        data.to_csv(OUT / name, index=False, lineterminator="\n")
    write_json(OUT / "feature_audit.json", dict(completed_at=utcnow(), input_manifest_sha256=sha256(MANIFEST),
        code_sha256=sha256(__file__), data_code_sha256=sha256(CASE / "gangnam/deepening_archive_data.py"),
        selected_links=len(selected), metadata_exclusions=exclusions, outputs=outputs,
        tables={name: sha256(OUT / name) for name in ["feature_coverage.csv", "publication_windows.csv"]},
        scope="current metadata publication proxy; feature values only after month release; not historical vintage proof"))
