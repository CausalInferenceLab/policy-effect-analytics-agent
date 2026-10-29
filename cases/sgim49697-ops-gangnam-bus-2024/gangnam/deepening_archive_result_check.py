"""저장된 월별 모형 예측에서 공개 성능과 주별 짝 비교를 독립 계산한다."""

import json

import numpy as np
import pandas as pd

from .common import CASE, sha256, utcnow, write_json
from .deepening_archive_data import OUT, checked, verify

KEY = ["link_id", "target_start", "origin"]
QUANTILES = ["q10", "q50", "q90"]


def loss_table(frame):
    """기존 손실·평가 함수를 호출하지 않고 행별 값을 계산한다."""
    observed = frame[["speed_kmh", *QUANTILES]].to_numpy(dtype=float)
    if not np.isfinite(observed).all():
        raise ValueError("독립 성능 대조에는 유한한 관측·예측만 허용합니다")
    if np.any(np.diff(observed[:, 1:], axis=1) < 0):
        raise ValueError("정렬되지 않은 분위수 예측")
    y, lower, middle, upper = observed.T
    losses = {}
    for column, level in zip(QUANTILES, [.1, .5, .9], strict=True):
        residual = y - frame[column].to_numpy()
        losses["pinball_" + column] = np.where(residual >= 0, level * residual, (level - 1) * residual)
    losses["mean_pinball"] = sum(losses.values()) / 3
    losses["median_mae"] = np.abs(y - middle)
    losses["coverage"] = ((lower <= y) & (y <= upper)).astype(float)
    losses["width"] = upper - lower
    losses["crossing_fraction"] = np.zeros(len(y))
    losses["interval_score_alpha_0.2"] = np.where(y < lower, upper - lower + 10 * (lower - y),
        np.where(y > upper, upper - lower + 10 * (y - upper), upper - lower))
    return pd.DataFrame(losses, index=frame.index)


def subset(frame, scope):
    if scope == "primary_all_hours":
        return frame
    if scope == "primary_evening_17_19":
        return frame[frame.target_start.dt.hour.between(17, 19)]
    if scope.startswith("link_"):
        return frame[frame.link_id.eq(scope.removeprefix("link_"))]
    if scope.startswith("month_"):
        return frame[frame.target_start.dt.strftime("%Y-%m").eq(scope.removeprefix("month_"))]
    raise ValueError("알 수 없는 성능 대조 범위")


def metric_values(frame):
    valid = frame[frame[["speed_kmh", *QUANTILES]].notna().all(axis=1)]
    return dict(expected_rows=len(frame), observed_target_rows=int(frame.speed_kmh.notna().sum()),
        scored_rows=len(valid), missing_target_rows=int(frame.speed_kmh.isna().sum()),
        missing_prediction_rows=int(frame[QUANTILES].isna().any(axis=1).sum()),
        raw_crossing_fraction=float(frame.raw_crossing.mean()), **loss_table(valid).mean().to_dict())


def independent_pair(left, right, cfg):
    a = left.dropna(subset=["speed_kmh"]).set_index(KEY).sort_index()
    b = right.dropna(subset=["speed_kmh"]).set_index(KEY).sort_index()
    if not a.index.equals(b.index) or a.index.has_duplicates:
        raise ValueError("독립 짝 비교의 시간·링크 표본 불일치")
    np.testing.assert_array_equal(a.speed_kmh, b.speed_kmh)
    delta = loss_table(a) - loss_table(b)
    times = a.index.get_level_values("target_start").tz_localize(None)
    monday = times.normalize() - pd.to_timedelta(times.dayofweek, unit="D")
    grouped = delta.groupby(monday).agg(["sum", "count"]).sort_index()
    weeks = len(grouped)
    weights = np.random.default_rng(cfg["week_bootstrap_seed"]).multinomial(
        weeks, np.ones(weeks) / weeks, size=cfg["week_bootstrap_draws"])
    result = {}
    for metric in cfg["metrics"]:
        summaries = grouped[metric]
        samples = np.average(np.broadcast_to((summaries["sum"] / summaries["count"]).to_numpy(), weights.shape),
            axis=1, weights=weights * summaries["count"].to_numpy())
        result[metric] = dict(difference=float(delta[metric].mean()), low=float(np.percentile(samples, 2.5)),
            high=float(np.percentile(samples, 97.5)), weeks=weeks, rows=len(a), draws=len(weights),
            quality_pass=weeks >= cfg["minimum_weeks_for_interval"])
    return result


def compare(actual, row, fields):
    for name in fields:
        np.testing.assert_allclose(actual[name], row[name], rtol=1e-10, atol=1e-10, equal_nan=True,
            err_msg="월별 결과 독립 대조: " + name)


def run():
    cfg, _ = verify()
    audit_path = OUT / "evaluation_audit.json"
    audit = json.loads(audit_path.read_text())
    for name, value in audit["outputs"].items():
        checked(dict(path=str((OUT / name).relative_to(CASE)), sha256=value))
    predictions = {}
    for entry in audit["predictions"]:
        frame = pd.read_parquet(checked(entry))
        frame["link_id"] = frame.link_id.astype(str)
        if len(frame) != entry["rows"] or frame.duplicated(KEY).any():
            raise ValueError("저장된 예측의 행 수·키 중복 오류")
        if frame.target_start.dt.year.ge(cfg["locked_year"]).any():
            raise ValueError("잠금 연도의 평가 금지")
        if not frame.origin.ge(pd.Timestamp(cfg["evaluation_origin_not_before"])).all():
            raise ValueError("준비 시점 이전 발행 예측")
        if not frame.target_start.sub(frame.origin).eq(pd.Timedelta(hours=entry["horizon"] - 1)).all():
            raise ValueError("예측 발행 시계 불일치")
        start, end = cfg["splits"][entry["period"]]
        clock = pd.date_range(start, end + " 23:00", freq="h", tz=cfg["timezone"])
        earliest = pd.Timestamp(cfg["evaluation_origin_not_before"]) + pd.Timedelta(hours=entry["horizon"] - 1)
        expected = pd.MultiIndex.from_product([cfg["primary_links"], clock[clock >= earliest]], names=KEY[:2]).sort_values()
        if not frame.set_index(KEY[:2]).index.sort_values().equals(expected):
            raise ValueError("예측 파일의 전체 시간 격자 누락·추가")
        present = frame[QUANTILES].notna().all(axis=1)
        if int(present.sum()) != entry["finite_prediction_rows"]:
            raise ValueError("저장된 예측의 가용 행 수 불일치")
        if entry["name"] != "reference_recent_assumption" and not present.all():
            raise ValueError("새 모형에서 전체 시간 예측이 누락됨")
        loss_table(frame[frame.speed_kmh.notna() & present])
        predictions[(entry["period"], entry["horizon"], entry["name"], entry["seed"])] = frame
    if len(predictions) != 24:
        raise ValueError("고정 예측 조합 수 불일치")
    for period in ["summer", "autumn"]:
        for horizon in cfg["horizons"]:
            truth = predictions[(period, horizon, "calendar_only", cfg["training"]["primary_seed"])].set_index(KEY).speed_kmh.sort_index()
            for (name_period, name_horizon, _, _), frame in predictions.items():
                if (name_period, name_horizon) == (period, horizon):
                    np.testing.assert_allclose(frame.set_index(KEY).speed_kmh.sort_index(), truth,
                        rtol=0, atol=0, equal_nan=True, err_msg="모형별 정답·미관측 상태 불일치")
    metrics = pd.read_csv(OUT / "metrics.csv")
    metric_numbers = 0
    for _, row in metrics.iterrows():
        frame = predictions[(row.period, row.horizon, row["name"], row.seed)]
        actual = metric_values(subset(frame, row.scope))
        compare(actual, row, actual)
        metric_numbers += len(actual)
    pairs = pd.read_csv(OUT / "paired_comparisons.csv")
    pair_numbers = 0
    for (period, horizon, seed, comparison, scope), group in pairs.groupby(["period", "horizon", "seed", "comparison", "scope"]):
        names = {"archive_minus_calendar": [("published_archive", seed), ("calendar_only", seed)],
                 "archive_minus_profile": [("published_archive", seed), ("published_three_month_profile", 0)],
                 "profile_minus_calendar": [("published_three_month_profile", 0), ("calendar_only", seed)]}[comparison]
        left, right = [subset(predictions[(period, horizon, name, value)], scope) for name, value in names]
        actual = independent_pair(left, right, cfg["evaluation"])
        if len(group) != len(actual) or set(group.metric) != set(actual):
            raise ValueError("짝 비교 지표의 누락·중복")
        for _, row in group.iterrows():
            compare(actual[row.metric], row, actual[row.metric])
            pair_numbers += len(actual[row.metric])
    expected_metrics = 24 * 9
    expected_pairs = 2 * 2 * 2 * 3 * 2 * len(cfg["evaluation"]["metrics"])
    if len(metrics) != expected_metrics or len(pairs) != expected_pairs:
        raise ValueError("공개 성능·짝 비교의 전체 조합 수 불일치")
    write_json(OUT / "result_validation.json", dict(completed_at=utcnow(), code_sha256=sha256(__file__),
        evaluation_audit_sha256=sha256(audit_path), prediction_files=len(predictions), metric_rows=len(metrics),
        metric_values_checked=metric_numbers, paired_rows=len(pairs), paired_values_checked=pair_numbers,
        mismatches=0, tolerance=dict(rtol=1e-10, atol=1e-10),
        scope="저장된 예측·시간 격자·성능 및 동일 주 재표집의 독립 계산; 모델 재학습·원본 XLSX 전수 재추출은 아님"))
    print(f"월별 예측 {len(predictions)}개·성능 {len(metrics)}행·짝 비교 {len(pairs)}행 독립 대조 일치", flush=True)
