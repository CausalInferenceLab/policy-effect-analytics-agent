"""사후 기준 모델 비교에 필요한 경험 분위수·경보 예산·보정 폭과 구간 손실을 계산한다."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .overnight_forecast_diagnostics import align_predictions
from .overnight_forecast_metrics import quantile_losses, week_structure

QUANTILES = [.1, .5, .9]
QCOLS = ["q10", "q50", "q90"]


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
    return {"family": "calendar_empirical", "tables": tables, "global": np.quantile(train.speed_kmh, QUANTILES, method="linear"),
            "minimum_group_rows": minimum, "training_rows": len(train)}


def empirical_prediction(model, frame):
    result = np.full((len(frame), 3), np.nan)
    level = np.full(len(frame), 3, dtype=int)
    for i, table in enumerate(model["tables"]):
        columns = table["columns"]
        index = pd.MultiIndex.from_frame(frame[columns]) if len(columns) > 1 else pd.Index(frame[columns[0]])
        values = table["values"].reindex(index).to_numpy()
        use = np.isnan(result).all(axis=1) & np.isfinite(values).all(axis=1)
        result[use], level[use] = values[use], i
    fallback = np.isnan(result).all(axis=1)
    result[fallback] = model["global"]
    if not np.isfinite(result).all():
        raise ValueError("경험 분위수 예측이 유한하지 않습니다")
    return result, level


def weekly_prediction(model, frame, columns, minimum=3):
    fallback, _ = empirical_prediction(model, frame)
    values = frame[columns].to_numpy(dtype=float)
    valid = np.isfinite(values).sum(axis=1) >= minimum
    if np.isinf(values).any() or (values[np.isfinite(values)] < 0).any():
        raise ValueError("주간 속도 지연값이 음수·무한대입니다")
    if valid.any():
        fallback[valid] = np.nanquantile(values[valid], QUANTILES, axis=1, method="linear").T
    return fallback, ~valid


def budget_threshold(labels, probability, days, maximum_alerts=2., maximum_fpr=.1):
    y, p = np.asarray(labels), np.asarray(probability, dtype=float)
    if (not len(y) or len(y) != len(p) or days <= 0 or maximum_alerts < 0 or not 0 <= maximum_fpr <= 1
            or not np.isin(y, [0, 1]).all() or not np.isfinite(p).all() or np.any((p < 0) | (p > 1))):
        raise ValueError("경보 예산 선택의 입력 범위 오류")
    positives, negatives = int(y.sum()), int(len(y) - y.sum())
    if not positives or not negatives:
        raise ValueError("경보 예산 선택 기간에 양성·음성이 모두 필요합니다")
    order = np.argsort(-p, kind="stable")
    ends = np.r_[np.flatnonzero(np.diff(p[order]) != 0), len(p) - 1]
    alerts = np.r_[0, ends + 1]
    tp = np.r_[0, np.cumsum(y[order])[ends]]
    thresholds = np.r_[np.nextafter(1., np.inf), p[order][ends]]
    fpr, recall = (alerts - tp) / negatives, tp / positives
    eligible = np.flatnonzero((alerts / days <= maximum_alerts + 1e-12) & (fpr <= maximum_fpr + 1e-12))
    best = eligible[np.isclose(recall[eligible], recall[eligible].max(), rtol=0, atol=1e-12)]
    i = best[np.argmax(thresholds[best])]
    return {"threshold": float(thresholds[i]), "decision_recall": float(recall[i]), "decision_fpr": float(fpr[i]),
            "decision_alerts": int(alerts[i]), "decision_calendar_days": int(days), "decision_alerts_per_day": float(alerts[i] / days)}


def calibration_expansion(target, prediction, coverage=.8):
    y, q = np.asarray(target), np.asarray(prediction)
    if q.shape != (len(y), 3) or not len(y) or not np.isfinite(y).all() or not np.isfinite(q).all() or not 0 < coverage < 1:
        raise ValueError("구간 보정 입력이 유한하지 않거나 크기가 다릅니다")
    rank = int(np.ceil((len(y) + 1) * coverage))
    if rank > len(y):
        raise ValueError("유한 구간 보정에 필요한 표본 수가 부족합니다")
    scores = np.maximum(q[:, 0] - y, y - q[:, 2])
    raw = float(np.sort(scores)[rank - 1])
    return {"rows": len(y), "rank": rank, "raw_score_quantile": raw, "expansion": max(0., raw),
            "nominal_coverage": coverage, "raw_crossing_fraction": float((np.diff(q, axis=1) < 0).any(axis=1).mean())}


def expand_quantiles(prediction, expansion):
    if not np.isfinite(expansion) or expansion < 0:
        raise ValueError("구간 확장 폭은 유한한 0 이상이어야 합니다")
    result = np.asarray(prediction).copy()
    result[:, 0] -= expansion
    result[:, 2] += expansion
    return result


def interval_losses(frame, alpha=.2):
    if not 0 < alpha < 1:
        raise ValueError("구간 점수의 alpha 범위 오류")
    target, lower, upper = frame.speed_kmh.to_numpy(), frame.q10.to_numpy(), frame.q90.to_numpy()
    if not np.isfinite(frame[["speed_kmh", *QCOLS]].to_numpy()).all() or np.any(lower > upper):
        raise ValueError("구간 점수에는 유한하며 하한이 상한 이하인 구간이 필요합니다")
    return {**quantile_losses(frame), "interval_score_alpha_0.2": upper - lower
            + (2 / alpha) * np.maximum(lower - target, 0) + (2 / alpha) * np.maximum(target - upper, 0)}


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
        result.append({"metric": metric, "difference": float(delta.mean()), "low": float(np.quantile(samples, .025)),
                       "high": float(np.quantile(samples, .975)), "weeks": len(names), "rows": len(aligned), "draws": draws})
    return result
