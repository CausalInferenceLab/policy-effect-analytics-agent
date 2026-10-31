"""공개된 월별 과거 속도와 달력의 CPU 분위수 예측을 같은 표본에서 비교한다."""

import argparse
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
from _shared import CASE, checked, config, load_json, new_run, reference, verify_inputs, write_json

CALENDAR = ["link_id", "hour", "weekday", "month", "weekend", "korean_public_holiday"]
CATEGORICAL = ["link_id", "hour", "weekday", "month"]
PROFILE_STATS = ["mean", "std", "q10", "q50", "q90", "count", "expected"]
QUANTILES = [0.1, 0.5, 0.9]
QCOLS = ["q10", "q50", "q90"]
KEY = ["link_id", "target_start"]
PREDICTION_KEY = ["link_id", "target_start", "origin", "speed_kmh"]


def publication_clock(targets, horizon, releases, windows):
    origins = targets - pd.Timedelta(hours=horizon - 1)
    ordered = releases.sort_values()
    if ordered.index.duplicated().any() or ordered.isna().any():
        raise ValueError("공개 시계의 중복·누락 월")
    position = np.searchsorted(pd.DatetimeIndex(ordered).asi8, origins.asi8, side="right")
    clock = pd.DataFrame(
        dict(target_start=targets, origin=origins, publication_cursor=position), index=targets
    )
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
            records.append(
                dict(
                    cursor=int(cursor),
                    window=window,
                    source_months=";".join(months),
                    latest_required_release=latest_release,
                    first_origin=earliest_origin,
                    origins=int((position == cursor).sum()),
                )
            )
    return clock, choices, records


def month_profile(matrix, months):
    if not months:
        index = pd.MultiIndex.from_arrays([[], [], []], names=["link_id", "weekday", "hour"])
        return pd.DataFrame(index=index, columns=PROFILE_STATS, dtype=float)
    selected = matrix[matrix.index.strftime("%Y-%m").isin(months)]
    if not len(selected):
        raise ValueError("공개됐다고 지정한 프로필 월의 시간 격자가 없습니다")
    data = (
        selected.rename_axis("source_hour")
        .melt(ignore_index=False, var_name="link_id", value_name="speed")
        .reset_index()
    )
    data["weekday"], data["hour"] = data.source_hour.dt.dayofweek, data.source_hour.dt.hour
    groups = data.groupby(["link_id", "weekday", "hour"], observed=True).speed
    result = groups.agg(mean="mean", std="std", count="count", expected="size")
    quantiles = groups.quantile([0.1, 0.5, 0.9], interpolation="linear").unstack(-1)
    quantiles.columns = ["q10", "q50", "q90"]
    return result.join(quantiles)[PROFILE_STATS]


def lag_values(series, targets, horizon, lag, releases):
    origins = targets - pd.Timedelta(hours=horizon - 1)
    source = targets - pd.Timedelta(hours=lag)
    if not (source + pd.Timedelta(hours=1) <= origins).all():
        raise ValueError("발행 시각 뒤에 끝나는 지연 특징")
    month = source.strftime("%Y-%m")
    publication = releases.reindex(month)
    available = np.array(
        [
            not pd.isna(stamp) and stamp <= origin
            for stamp, origin in zip(publication, origins, strict=True)
        ]
    )
    values = series.reindex(source).to_numpy(dtype=float)
    values[~available] = np.nan
    return values, available.astype("int8")


def build_features(matrix, releases, horizon, cfg, holidays):
    expected = pd.date_range(matrix.index[0], matrix.index[-1], freq="h", tz=cfg["timezone"])
    if not matrix.index.equals(expected) or matrix.index.year.max() >= cfg["locked_year"]:
        raise ValueError("연속 시간 격자 또는 잠금 연도 오류")
    clock, choices, records = publication_clock(
        matrix.index, horizon, releases, cfg["profile_last_published_months"]
    )
    profiles = {months: month_profile(matrix, months) for months in set(choices.values())}
    parts, quality = [], []
    for link in matrix:
        frame = pd.DataFrame(index=matrix.index)
        frame["link_id"] = link
        frame["hour"], frame["weekday"], frame["month"] = (
            frame.index.hour,
            frame.index.dayofweek,
            frame.index.month,
        )
        frame["weekend"] = frame.weekday.ge(5).astype("int8")
        frame["korean_public_holiday"] = (
            frame.index.strftime("%Y-%m-%d").isin(holidays).astype("int8")
        )
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
                index = pd.MultiIndex.from_arrays(
                    [
                        np.repeat(link, positions.sum()),
                        frame.loc[positions, "weekday"],
                        frame.loc[positions, "hour"],
                    ],
                    names=["link_id", "weekday", "hour"],
                )
                values = profiles[months].reindex(index)
                for statistic in PROFILE_STATS:
                    frame.loc[positions, f"archive_profile_{window}_{statistic}"] = values[
                        statistic
                    ].to_numpy()
                frame.loc[positions, f"archive_profile_{window}_months"] = len(months)
                if months:
                    end = (
                        (pd.Period(months[-1], freq="M") + 1)
                        .to_timestamp()
                        .tz_localize(cfg["timezone"])
                    )
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
            quality.append(
                dict(
                    horizon=horizon,
                    link_id=link,
                    split=split,
                    expected=len(data),
                    observed=int(data.speed_kmh.notna().sum()),
                    profile1_present=int(data.archive_profile_1_q50.notna().sum()),
                    profile3_present=int(data.archive_profile_3_q50.notna().sum()),
                    **{
                        f"lag{lag}_present": int(data[f"archive_lag_{lag}"].notna().sum())
                        for lag in cfg["target_relative_lags_hours"]
                    },
                )
            )
        parts.append(frame.reset_index(drop=True))
    return pd.concat(parts, ignore_index=True), pd.DataFrame(quality), pd.DataFrame(records)


def feature_sets(frame):
    return {
        "calendar_only": CALENDAR,
        "published_archive": CALENDAR + [c for c in frame if c.startswith("archive_")],
    }


def fit_schema(train, columns):
    categorical = [c for c in CATEGORICAL if c in columns]
    numeric = [c for c in columns if c not in categorical]
    medians = train[numeric].median()
    # 학습기 전체 결측 열은 상수 0과 결측 표시를 함께 사용하고 예외를 기록한다.
    return {
        "columns": columns,
        "categorical": categorical,
        "numeric": numeric,
        "medians": medians.fillna(0.0).to_dict(),
        "all_missing_training_columns": medians[medians.isna()].index.tolist(),
    }


def transform(frame, schema):
    result = frame[schema["columns"]].copy()
    for column in schema["categorical"]:
        if result[column].isna().any():
            raise ValueError("달력·링크 범주에 결측이 있습니다")
        result[column] = result[column].astype(str)
    for column in schema["numeric"]:
        result[column + "__missing"] = result[column].isna().astype("int8")
        result[column] = result[column].fillna(schema["medians"][column]).astype("float64")
    if not np.isfinite(result.select_dtypes("number").to_numpy()).all():
        raise ValueError("학습 특징에 유한하지 않은 값이 있습니다")
    return result


def uniform_sample(train, maximum, seed):
    rng = np.random.default_rng(seed)
    positions = []
    for _, part in train.groupby("link_id", sort=True, observed=True):
        positions.extend(
            rng.choice(part.index.to_numpy(), size=min(maximum, len(part)), replace=False)
        )
    return train.loc[sorted(positions)].copy()


def fit_quantile(depth, train, tuning, columns, cfg, seed):
    from catboost import CatBoostRegressor

    options = cfg["models"]["catboost_quantile"]
    schema = fit_schema(train, columns)
    sample = uniform_sample(train, cfg["training"]["maximum_rows_per_link"], seed)
    loss = "MultiQuantile:alpha=" + ",".join(str(q) for q in options["quantiles"])
    estimator = CatBoostRegressor(
        depth=depth,
        iterations=options["iterations"],
        learning_rate=options["learning_rate"],
        loss_function=loss,
        random_seed=seed,
        task_type="CPU",
        thread_count=options["thread_count"],
        cat_features=schema["categorical"],
        allow_writing_files=False,
        verbose=False,
    )
    estimator.fit(
        transform(sample, schema),
        sample.speed_kmh,
        eval_set=(transform(tuning, schema), tuning.speed_kmh),
        early_stopping_rounds=options["early_stopping_rounds"],
        use_best_model=True,
    )
    return {
        "family": "quantile",
        "estimator": estimator,
        "schema": schema,
        "parameter": depth,
        "iterations": int(estimator.tree_count_),
        "training_rows": len(sample),
        "seed": seed,
        "quantiles": options["quantiles"],
    }


def empirical_model(train, minimum=30):
    if train.empty or train.speed_kmh.isna().any() or not np.isfinite(train.speed_kmh).all():
        raise ValueError("경험 분위수의 학습 목표는 비어 있지 않은 유한 값이어야 합니다")
    if "split" in train and not train.split.eq("train").all():
        raise ValueError("경험 분위수에 학습 기간 밖 자료가 포함됐습니다")
    tables = []
    for columns in [["link_id", "weekday", "hour"], ["link_id", "hour"], ["link_id"]]:
        groups = train.groupby(columns, observed=True).speed_kmh
        counts = groups.count()
        values = groups.quantile(QUANTILES, interpolation="linear").unstack(-1)
        values = values.loc[counts.ge(minimum)]
        values.columns = QCOLS
        tables.append({"columns": columns, "values": values})
    return {
        "family": "calendar_empirical",
        "tables": tables,
        "global": np.quantile(train.speed_kmh, QUANTILES, method="linear"),
        "minimum_group_rows": minimum,
        "training_rows": len(train),
    }


def empirical_prediction(model, frame):
    result = np.full((len(frame), 3), np.nan)
    level = np.full(len(frame), 3, dtype=int)
    for i, table in enumerate(model["tables"]):
        columns = table["columns"]
        index = (
            pd.MultiIndex.from_frame(frame[columns])
            if len(columns) > 1
            else pd.Index(frame[columns[0]])
        )
        values = table["values"].reindex(index).to_numpy()
        use = np.isnan(result).all(axis=1) & np.isfinite(values).all(axis=1)
        result[use], level[use] = values[use], i
    fallback = np.isnan(result).all(axis=1)
    result[fallback] = model["global"]
    if not np.isfinite(result).all():
        raise ValueError("경험 분위수 예측이 유한하지 않습니다")
    return result, level


def interval_losses(frame, alpha=0.2):
    if not 0 < alpha < 1:
        raise ValueError("구간 점수의 alpha 범위 오류")
    target, lower, upper = frame.speed_kmh.to_numpy(), frame.q10.to_numpy(), frame.q90.to_numpy()
    if not np.isfinite(frame[["speed_kmh", *QCOLS]].to_numpy()).all() or np.any(lower > upper):
        raise ValueError("구간 점수에는 유한하며 하한이 상한 이하인 구간이 필요합니다")
    return {
        **quantile_losses(frame),
        "interval_score_alpha_0.2": upper
        - lower
        + (2 / alpha) * np.maximum(lower - target, 0)
        + (2 / alpha) * np.maximum(target - upper, 0),
    }


def paired_intervals(left, right, draws=1000, seed=17):
    aligned = align_predictions(left.assign(label=0), right.assign(label=0))
    codes, names, _ = week_structure(aligned.target_start)
    if len(names) < 2:
        raise ValueError("구간 짝 비교에는 두 주 이상이 필요합니다")
    losses = []
    for suffix in ["left", "right"]:
        frame = pd.DataFrame({c: aligned[c + "_" + suffix] for c in ["speed_kmh", *QCOLS]})
        losses.append(interval_losses(frame))
    rng = np.random.default_rng(seed)
    multiplicity = rng.multinomial(len(names), np.full(len(names), 1 / len(names)), size=draws)
    counts = np.bincount(codes, minlength=len(names))
    result = []
    for metric in losses[0]:
        delta = losses[0][metric] - losses[1][metric]
        sums = np.bincount(codes, weights=delta, minlength=len(names))
        samples = (multiplicity @ sums) / (multiplicity @ counts)
        result.append(
            {
                "metric": metric,
                "difference": float(delta.mean()),
                "low": float(np.quantile(samples, 0.025)),
                "high": float(np.quantile(samples, 0.975)),
                "weeks": len(names),
                "rows": len(aligned),
                "draws": draws,
            }
        )
    return result


def week_structure(timestamps):
    date = pd.to_datetime(timestamps).dt.tz_localize(None)
    week = date.dt.to_period("W-SUN").astype(str)
    codes, names = pd.factorize(week, sort=True)
    days = (
        pd.DataFrame({"week": week, "date": date.dt.date})
        .drop_duplicates()
        .groupby("week")
        .size()
        .reindex(names)
    )
    return codes, names, days.to_numpy()


def quantile_losses(frame):
    target = frame.speed_kmh.to_numpy()
    prediction = frame[["q10", "q50", "q90"]].to_numpy()
    residual = target[:, None] - prediction
    alpha = np.array([0.1, 0.5, 0.9])
    pinball = np.maximum(alpha * residual, (alpha - 1) * residual)
    return {
        "pinball_q10": pinball[:, 0],
        "pinball_q50": pinball[:, 1],
        "pinball_q90": pinball[:, 2],
        "mean_pinball": pinball.mean(axis=1),
        "coverage": ((target >= prediction[:, 0]) & (target <= prediction[:, 2])).astype(float),
        "width": prediction[:, 2] - prediction[:, 0],
        "crossing_fraction": (np.diff(prediction, axis=1) < 0).any(axis=1).astype(float),
        "median_mae": np.abs(target - prediction[:, 1]),
    }


def align_predictions(left, right):
    """행 순서와 무관하게 같은 시각·링크·관측값의 예측만 비교한다."""
    if left.duplicated(KEY).any() or right.duplicated(KEY).any():
        raise ValueError("예측 키가 중복되어 짝 비교를 할 수 없습니다")
    merged = left.merge(
        right,
        on=KEY,
        how="outer",
        suffixes=("_left", "_right"),
        indicator=True,
        validate="one_to_one",
    )
    if not merged._merge.eq("both").all() or not merged.label_left.eq(merged.label_right).all():
        raise ValueError("비교 예측의 표본 또는 목표 라벨이 다릅니다")
    if not np.array_equal(merged.speed_kmh_left, merged.speed_kmh_right):
        raise ValueError("같은 키의 관측 속도가 다릅니다")
    return merged.sort_values(KEY).reset_index(drop=True)


def predict_quantiles(model, frame, threads):
    return model["estimator"].predict(
        transform(frame, model["schema"]), thread_count=threads, task_type="CPU"
    )


def development_parts(frame, cfg):
    train = frame[frame.split.eq("train") & frame.speed_kmh.notna()].copy()
    tuning = frame[
        frame.split.eq("tuning")
        & frame.link_id.isin(cfg["primary_links"])
        & frame.speed_kmh.notna()
    ].copy()
    for name, part in [("train", train), ("tuning", tuning)]:
        start, end = cfg["splits"][name]
        if not len(part) or not part.target_start.dt.strftime("%Y-%m-%d").between(start, end).all():
            raise ValueError("월별 모형 개발 분할·날짜 불일치")
        if not np.isfinite(part.speed_kmh).all():
            raise ValueError("월별 모형 개발 목표의 비유한 값")
    return train, tuning


def sampled_key_hash(train, cfg, seed):
    sample = uniform_sample(train, cfg["training"]["maximum_rows_per_link"], seed)
    values = pd.util.hash_pandas_object(
        sample[["link_id", "target_start", "speed_kmh"]], index=False
    ).to_numpy()
    return hashlib.sha256(values.tobytes()).hexdigest(), len(sample)


def ordered_predictions(prediction):
    q = np.asarray(prediction)
    if q.ndim != 2 or q.shape[1] != 3 or not np.isfinite(q).all():
        raise ValueError("유한한 세 분위수 예측이 필요합니다")
    crossing = (np.diff(q, axis=1) < 0).any(axis=1)
    return np.sort(q, axis=1), crossing


def archive_profile_prediction(model, frame, minimum):
    result, _ = empirical_prediction(model, frame)
    profile = frame[
        ["archive_profile_3_q10", "archive_profile_3_q50", "archive_profile_3_q90"]
    ].to_numpy()
    valid = frame.archive_profile_3_count.ge(minimum).to_numpy() & np.isfinite(profile).all(axis=1)
    result[valid] = profile[valid]
    return ordered_predictions(result)[0], ~valid


def evaluation_rows(frame, cfg, period, horizon):
    start, end = cfg["splits"][period]
    use = frame.link_id.isin(cfg["primary_links"]) & frame.target_start.dt.strftime(
        "%Y-%m-%d"
    ).between(start, end)
    use &= frame.origin.ge(pd.Timestamp(cfg["evaluation_origin_not_before"]))
    result = frame[use].copy().sort_values(["link_id", "target_start"]).reset_index(drop=True)
    targets = pd.date_range(start, end + " 23:00", freq="h", tz=cfg["timezone"])
    origins = targets - pd.Timedelta(hours=horizon - 1)
    expected = int((origins >= pd.Timestamp(cfg["evaluation_origin_not_before"])).sum()) * len(
        cfg["primary_links"]
    )
    if len(result) != expected or result.duplicated(["link_id", "target_start"]).any():
        raise ValueError("월별 모형 평가의 전체 시간 격자·키 오류")
    return result


def slices(frame, primary):
    yield "primary_all_hours", frame
    yield "primary_evening_17_19", frame[frame.target_start.dt.hour.isin([17, 18, 19])]
    for link in primary:
        yield "link_" + link, frame[frame.link_id.eq(link)]
    for month, group in frame.groupby(frame.target_start.dt.strftime("%Y-%m")):
        yield "month_" + month, group


def metrics(frame):
    valid = frame[frame.speed_kmh.notna() & frame[QCOLS].notna().all(axis=1)]
    if not len(valid):
        raise ValueError("평가 가능한 속도·예측 행이 없습니다")
    values = {name: float(loss.mean()) for name, loss in interval_losses(valid).items()}
    return dict(
        expected_rows=len(frame),
        observed_target_rows=int(frame.speed_kmh.notna().sum()),
        scored_rows=len(valid),
        missing_target_rows=int(frame.speed_kmh.isna().sum()),
        missing_prediction_rows=int(frame[QCOLS].isna().any(axis=1).sum()),
        raw_crossing_fraction=float(frame.raw_crossing.mean()),
        **values,
    )


def read_matrix(inputs, cfg):
    entries = [entry for entry in inputs["files"] if entry["kind"] == "road_speed"]
    if (
        sorted(e["month"] for e in entries)
        != pd.period_range(*cfg["months"], freq="M").astype(str).tolist()
    ):
        raise ValueError("도로 36개월 입력의 누락·중복")
    frames = []
    for entry in entries:
        frame = pd.read_parquet(
            checked(entry), columns=["link_id", "interval_start_kst", "speed_kmh", "is_valid"]
        )
        if not frame.interval_start_kst.dt.strftime("%Y-%m").eq(entry["month"]).all():
            raise ValueError("요청 월 밖의 도로 시각")
        if (frame.speed_kmh.notna() & ~frame.is_valid).any() or np.isinf(frame.speed_kmh).any():
            raise ValueError("무효 속도값이 남아 있습니다")
        frames.append(frame[frame.link_id.isin(cfg["selected_links"])])
    frame = pd.concat(frames, ignore_index=True)
    if frame.duplicated(["link_id", "interval_start_kst"]).any():
        raise ValueError("링크·시간 중복")
    index = pd.date_range(
        cfg["months"][0] + "-01", "2025-12-31 23:00", freq="h", tz=cfg["timezone"]
    )
    matrix = frame.pivot(index="interval_start_kst", columns="link_id", values="speed_kmh").reindex(
        index=index, columns=sorted(cfg["selected_links"])
    )
    for entry in entries:
        if not set(entry["masked_links"]).issubset(cfg["selected_links"]):
            raise ValueError("고정 링크 밖의 속성 제외 목록")
        matrix.loc[matrix.index.strftime("%Y-%m") == entry["month"], entry["masked_links"]] = np.nan
    train = matrix.loc[slice(*cfg["splits"]["train"])]
    for link, spec in cfg["selected_links"].items():
        if not np.isclose(
            train[link].notna().mean(), spec["training_coverage"], rtol=0, atol=1e-12
        ):
            raise ValueError(f"고정 학습 링크의 관측률 변경: {link}")
    return matrix


def make_features(inputs_path, run_id):
    inputs = verify_inputs(load_json(inputs_path))
    cfg = config()["forecast"]
    out = new_run(run_id)
    matrix = read_matrix(inputs, cfg)
    sources = [
        e for e in load_json(CASE / "source-manifest.json")["files"] if e["kind"] == "road_speed"
    ]
    releases = pd.to_datetime(
        pd.Series({e["month"]: e["available_at_proxy"] for e in sources}), utc=True
    ).dt.tz_convert(cfg["timezone"])
    outputs = []
    for horizon in cfg["horizons"]:
        frame, quality, clock = build_features(
            matrix, releases, horizon, cfg, set(cfg["holidays"]["dates"])
        )
        target = out / f"features_h{horizon}.parquet"
        frame.to_parquet(target, index=False)
        quality.to_csv(out / f"coverage_h{horizon}.csv", index=False)
        clock.to_csv(out / f"publication_h{horizon}.csv", index=False)
        outputs.append(
            dict(
                horizon=horizon,
                rows=len(frame),
                feature_sets=feature_sets(frame),
                **reference(target),
            )
        )
        print(f"특징 완료 h{horizon}: {len(frame):,}행", flush=True)
    write_json(
        out / "features.json",
        dict(inputs=inputs["inputs"], input_manifest=reference(inputs_path), outputs=outputs),
    )
    return out / "features.json"


def read_features(entry):
    frame = pd.read_parquet(checked(entry))
    if (
        len(frame) != entry["rows"]
        or frame.duplicated(KEY).any()
        or frame.target_start.dt.year.ge(2026).any()
    ):
        raise ValueError("특징 행 수·중복·잠금 연도 오류")
    if not frame.origin.eq(frame.target_start - pd.Timedelta(hours=entry["horizon"] - 1)).all():
        raise ValueError("예측 발행 시각 불일치")
    if entry["feature_sets"] != feature_sets(frame):
        raise ValueError("사전 지정 특징 열이 변경됐습니다")
    return frame


def train_models(features_path, run_id):
    import joblib
    from threadpoolctl import threadpool_limits

    features = verify_inputs(load_json(features_path))
    cfg = config()["forecast"]
    out = new_run(run_id)
    state = dict(
        inputs=features["inputs"],
        feature_manifest=reference(features_path),
        entries=[],
        empirical={},
        completed=False,
    )
    for feature in features["outputs"]:
        horizon = feature["horizon"]
        train, tuning = development_parts(read_features(feature), cfg)
        if train.link_id.nunique() != len(cfg["selected_links"]):
            raise ValueError("훈련 링크 수 불일치")
        for seed in cfg["training"]["seeds"]:
            sample_hash, sample_rows = sampled_key_hash(train, cfg, seed)
            for name in cfg["feature_sets"]:
                print(f"CPU 학습 h{horizon} {name} seed{seed}: {sample_rows:,}행", flush=True)
                with threadpool_limits(limits=cfg["resources"]["threads"]):
                    model = fit_quantile(
                        cfg["models"]["catboost_quantile"]["depth"],
                        train,
                        tuning,
                        feature["feature_sets"][name],
                        cfg,
                        seed,
                    )
                if model["training_rows"] != sample_rows:
                    raise ValueError("훈련 표본 수 불일치")
                path = out / f"h{horizon}_{name}_s{seed}.joblib"
                joblib.dump(model, path)
                state["entries"].append(
                    dict(
                        name=name,
                        horizon=horizon,
                        seed=seed,
                        model=reference(path),
                        sample_key_sha256=sample_hash,
                        training_rows=sample_rows,
                        iterations=model["iterations"],
                    )
                )
                write_json(out / "training.json", state)
        path = out / f"h{horizon}_empirical.joblib"
        joblib.dump(
            empirical_model(train, cfg["empirical_baseline"]["minimum_training_group_rows"]), path
        )
        state["empirical"][str(horizon)] = reference(path)
    expected = {
        (h, s, n)
        for h in cfg["horizons"]
        for s in cfg["training"]["seeds"]
        for n in cfg["feature_sets"]
    }
    if {(e["horizon"], e["seed"], e["name"]) for e in state["entries"]} != expected:
        raise ValueError("계획한 8개 모형의 누락·중복")
    state["completed"] = True
    write_json(out / "training.json", state)
    return out / "training.json"


def evaluate_predictions(completed, cfg, period, horizon):
    measurements, comparisons = [], []
    for (name, seed), output in completed.items():
        for scope, group in slices(output, cfg["primary_links"]):
            measurements.append(
                dict(
                    period=period,
                    horizon=horizon,
                    name=name,
                    seed=seed,
                    scope=scope,
                    **metrics(group),
                )
            )
    for seed in cfg["training"]["seeds"]:
        pairs = {
            "archive_minus_calendar": (
                completed[("published_archive", seed)],
                completed[("calendar_only", seed)],
            ),
            "archive_minus_profile": (
                completed[("published_archive", seed)],
                completed[("published_three_month_profile", 0)],
            ),
            "profile_minus_calendar": (
                completed[("published_three_month_profile", 0)],
                completed[("calendar_only", seed)],
            ),
        }
        for comparison, (left, right) in pairs.items():
            for scope in ["primary_all_hours", "primary_evening_17_19"]:
                groups = [
                    data[
                        data.speed_kmh.notna()
                        & (
                            data.target_start.dt.hour.isin([17, 18, 19])
                            if scope.endswith("17_19")
                            else True
                        )
                    ]
                    for data in [left, right]
                ]
                values = paired_intervals(
                    *groups,
                    draws=cfg["evaluation"]["week_bootstrap_draws"],
                    seed=cfg["evaluation"]["week_bootstrap_seed"],
                )
                for result in values:
                    if result["metric"] in cfg["evaluation"]["metrics"]:
                        comparisons.append(
                            dict(
                                period=period,
                                horizon=horizon,
                                seed=seed,
                                comparison=comparison,
                                scope=scope,
                                quality_pass=result["weeks"]
                                >= cfg["evaluation"]["minimum_weeks_for_interval"],
                                **result,
                            )
                        )
    return measurements, comparisons


def evaluate(features_path, training_path, run_id):
    import joblib

    features = verify_inputs(load_json(features_path))
    state = verify_inputs(load_json(training_path))
    if not state["completed"] or state["feature_manifest"] != reference(features_path):
        raise ValueError("동일 특징에서 학습이 완료되지 않았습니다")
    cfg = config()["forecast"]
    out = new_run(run_id)
    measurements, comparisons = [], []
    for feature in features["outputs"]:
        horizon = feature["horizon"]
        full = read_features(feature)
        # joblib은 이 실행에서 만든 로컬 파일만 읽는다. 외부 모델을 내려받지 않는다.
        fallback = joblib.load(checked(state["empirical"][str(horizon)]))
        entries = [e for e in state["entries"] if e["horizon"] == horizon]
        for period in ["summer", "autumn"]:
            frame = evaluation_rows(full, cfg, period, horizon)
            completed = {}
            for entry in entries:
                model = joblib.load(checked(entry["model"]))
                q, crossing = ordered_predictions(
                    predict_quantiles(model, frame, cfg["resources"]["threads"])
                )
                output = frame[PREDICTION_KEY].copy()
                output[QCOLS], output["raw_crossing"] = q, crossing.astype(float)
                completed[(entry["name"], entry["seed"])] = output
            q, fallback_used = archive_profile_prediction(
                fallback, frame, cfg["empirical_baseline"]["minimum_profile_observations"]
            )
            output = frame[PREDICTION_KEY].copy()
            output[QCOLS], output["raw_crossing"], output["profile_fallback"] = (
                q,
                0.0,
                fallback_used,
            )
            completed[("published_three_month_profile", 0)] = output
            for (name, seed), output in completed.items():
                output.to_parquet(out / f"{period}_h{horizon}_{name}_s{seed}.parquet", index=False)
            rows, pairs = evaluate_predictions(completed, cfg, period, horizon)
            measurements.extend(rows)
            comparisons.extend(pairs)
            print(f"평가 완료: {period} h{horizon}", flush=True)
    pd.DataFrame(measurements).to_csv(out / "metrics.csv", index=False)
    pd.DataFrame(comparisons).to_csv(out / "paired_comparisons.csv", index=False)
    write_json(
        out / "result.json",
        dict(
            feature_manifest=reference(features_path),
            training_manifest=reference(training_path),
            outputs={
                name: reference(out / name) for name in ["metrics.csv", "paired_comparisons.csv"]
            },
            scope="이미 본 2025년 결과의 사후 탐색. 새로운 독립 평가 또는 실시간 운용 성능이 아님",
        ),
    )
    return out


def feature_group(column):
    """모형 입력 열을 설명용 네 묶음으로 나눈다. 결측 표시 열은 원래 열의 묶음을 따른다."""
    base = column.removesuffix("__missing")
    if base in CALENDAR:
        return "calendar"
    for prefix, group in [
        ("archive_lag_", "lag"),
        ("archive_available_", "lag"),
        ("archive_profile_1_", "profile_1"),
        ("archive_profile_3_", "profile_3"),
    ]:
        if base.startswith(prefix):
            return group
    raise ValueError("분류되지 않은 특징 열: " + column)


def example_week(cfg, period="autumn"):
    """평가 기간의 첫 온전한 월~일 주를 설정에서 정한다. 결과를 보고 고르지 않는다."""
    start, end = (pd.Timestamp(day, tz=cfg["timezone"]) for day in cfg["splits"][period])
    monday = pd.offsets.Week(weekday=0).rollforward(start)
    if monday + pd.Timedelta("6D") > end:
        raise ValueError("평가 기간 안에 온전한 주가 없습니다")
    return monday, monday + pd.Timedelta("7D")


def explain(models_dir, predictions_dir, run_id):
    """저장된 모형·예측에서 반복 수, 특징 중요도, 예시 주의 예측을 꺼낸다. 학습·평가는 하지 않는다."""
    import joblib

    cfg = config()["forecast"]
    out = new_run(run_id)
    read, models, importance = [], [], []
    for horizon in cfg["horizons"]:
        for name in cfg["feature_sets"]:
            for seed in cfg["training"]["seeds"]:
                path = Path(models_dir) / f"h{horizon}_{name}_s{seed}.joblib"
                read.append(reference(path))
                # joblib은 사용자가 지정한 로컬 파일만 읽는다. 외부 모델을 내려받지 않는다.
                model = joblib.load(path)
                if model["seed"] != seed or model["quantiles"] != QUANTILES:
                    raise ValueError("저장 모형의 시드·분위수가 파일 이름과 다릅니다")
                models.append(
                    dict(
                        name=name,
                        horizon=horizon,
                        seed=seed,
                        depth=model["parameter"],
                        iterations=model["iterations"],
                        training_rows=model["training_rows"],
                        input_columns=len(model["schema"]["columns"]),
                    )
                )
                estimator = model["estimator"]
                values = estimator.get_feature_importance(type="PredictionValuesChange")
                for feature, value in zip(estimator.feature_names_, values, strict=True):
                    importance.append(
                        dict(
                            name=name,
                            horizon=horizon,
                            seed=seed,
                            feature=feature,
                            group=feature_group(feature),
                            importance=float(value),
                        )
                    )
    start, end = example_week(cfg)
    weeks = []
    for name, seed in [
        ("published_archive", cfg["training"]["primary_seed"]),
        ("calendar_only", cfg["training"]["primary_seed"]),
        ("published_three_month_profile", 0),
    ]:
        path = Path(predictions_dir) / f"autumn_h1_{name}_s{seed}.parquet"
        read.append(reference(path))
        frame = pd.read_parquet(path)
        if set(frame.link_id) != set(cfg["primary_links"]):
            raise ValueError("예측 파일의 평가 링크가 설정과 다릅니다")
        frame = frame[frame.target_start.ge(start) & frame.target_start.lt(end)]
        if len(frame) != 7 * 24 * len(cfg["primary_links"]):
            raise ValueError("예시 주의 시간 격자가 비었습니다")
        weeks.append(frame[["link_id", "target_start", "speed_kmh", *QCOLS]].assign(name=name))
    tables = dict(
        models=pd.DataFrame(models),
        importance=pd.DataFrame(importance),
        example_week=pd.concat(weeks, ignore_index=True),
    )
    for table, frame in tables.items():
        frame.to_csv(out / f"{table}.csv", index=False)
    write_json(
        out / "result.json",
        dict(
            read=read,
            example_week=[str(start), str(end)],
            outputs={table: reference(out / f"{table}.csv") for table in tables},
            scope="저장된 모형·예측의 설명용 요약. 새 학습·평가가 아님",
        ),
    )
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    steps = parser.add_subparsers(dest="step", required=True)
    for name, arguments in [
        ("features", ["inputs"]),
        ("train", ["features"]),
        ("evaluate", ["features", "training"]),
        ("explain", ["models", "predictions"]),
    ]:
        sub = steps.add_parser(name)
        sub.add_argument("--run-id", required=True)
        for argument in arguments:
            sub.add_argument("--" + argument, required=True, type=Path)
    args = parser.parse_args()
    if args.step == "features":
        print(make_features(args.inputs, args.run_id))
    elif args.step == "train":
        print(train_models(args.features, args.run_id))
    elif args.step == "evaluate":
        print(evaluate(args.features, args.training, args.run_id))
    else:
        print(explain(args.models, args.predictions, args.run_id))
