"""같은 달력 주의 링크·시간을 함께 재표집해 확률·경보·분위수 지표의 불확실성을 계산한다."""

from __future__ import annotations

import numpy as np
import pandas as pd


def divide(numerator, denominator):
    return np.divide(numerator, denominator, out=np.full(np.broadcast_shapes(np.shape(numerator), np.shape(denominator)), np.nan),
                     where=np.asarray(denominator) != 0)


def weighted_probability_metrics(labels, probability, weights, threshold, days):
    """동점 확률을 같은 임계값으로 묶은 가중 average precision을 사용한다."""
    y, p, w = np.asarray(labels), np.asarray(probability), np.asarray(weights)
    if w.ndim == 1:
        w = w[None, :]
    if (len(y) == 0 or w.shape[1] != len(y) or np.any(w < 0) or not np.isfinite(w).all()
            or not np.isin(y, [0, 1]).all() or not np.isfinite(p).all() or np.any((p < 0) | (p > 1))):
        raise ValueError("확률 재표집 입력 크기 또는 가중치 오류")
    total = w.sum(axis=1)
    positive = w @ y
    negative = total - positive
    order = np.argsort(-p, kind="stable")
    boundary = np.r_[np.flatnonzero(np.diff(p[order]) != 0), len(p) - 1]
    tp = np.cumsum(w[:, order] * y[order], axis=1)[:, boundary]
    fp = np.cumsum(w[:, order] * (1 - y[order]), axis=1)[:, boundary]
    delta_tp = np.diff(np.column_stack([np.zeros(len(w)), tp]), axis=1)
    precision = divide(tp, tp + fp)
    ap = divide(np.nansum(precision * delta_tp, axis=1), positive)
    delta_fp = np.diff(np.column_stack([np.zeros(len(w)), fp]), axis=1)
    previous_tp = np.column_stack([np.zeros(len(w)), tp[:, :-1]])
    auc = divide(np.sum(delta_fp * (tp + previous_tp) / 2, axis=1), positive * negative)
    alerts = p >= threshold
    alert_count = w @ alerts
    true_alerts = w @ (alerts & (y == 1))
    false_alerts = w @ (alerts & (y == 0))
    p_clip = np.clip(p, 1e-15, 1 - 1e-15)
    return {"average_precision": ap, "roc_auc": auc, "brier": divide(w @ ((p - y) ** 2), total),
        "log_loss": divide(w @ (-y * np.log(p_clip) - (1 - y) * np.log(1 - p_clip)), total),
        "prevalence": divide(positive, total), "precision": divide(true_alerts, alert_count),
        "recall": divide(true_alerts, positive), "false_positive_rate": divide(false_alerts, negative),
        "alerts_per_day": divide(alert_count, days)}


def week_structure(timestamps):
    date = pd.to_datetime(timestamps).dt.tz_localize(None)
    week = date.dt.to_period("W-SUN").astype(str)
    codes, names = pd.factorize(week, sort=True)
    days = pd.DataFrame({"week": week, "date": date.dt.date}).drop_duplicates().groupby("week").size().reindex(names)
    return codes, names, days.to_numpy()


def probability_bootstrap(frame, threshold, draws=1000, seed=17):
    codes, names, days = week_structure(frame.target_start)
    if len(names) < 2:
        return [], {"weeks": len(names), "draws": 0}
    rng = np.random.default_rng(seed)
    multiplicity = rng.multinomial(len(names), np.full(len(names), 1 / len(names)), size=draws)
    results = {}
    for start in range(0, draws, 100):
        sample = multiplicity[start:start + 100]
        stats = weighted_probability_metrics(frame.label.to_numpy(), frame.probability.to_numpy(), sample[:, codes], threshold, sample @ days)
        for key, values in stats.items():
            results.setdefault(key, []).append(values)
    intervals = []
    for key, chunks in results.items():
        values = np.concatenate(chunks)
        valid = values[np.isfinite(values)]
        intervals.append({"metric": key, "low": float(np.quantile(valid, .025)) if len(valid) else np.nan,
                          "high": float(np.quantile(valid, .975)) if len(valid) else np.nan,
                          "valid_draws": len(valid), "invalid_draws": draws - len(valid)})
    return intervals, {"weeks": len(names), "draws": draws}


def quantile_losses(frame):
    target = frame.speed_kmh.to_numpy()
    prediction = frame[["q10", "q50", "q90"]].to_numpy()
    residual = target[:, None] - prediction
    alpha = np.array([.1, .5, .9])
    pinball = np.maximum(alpha * residual, (alpha - 1) * residual)
    return {"pinball_q10": pinball[:, 0], "pinball_q50": pinball[:, 1], "pinball_q90": pinball[:, 2],
        "mean_pinball": pinball.mean(axis=1), "coverage": ((target >= prediction[:, 0]) & (target <= prediction[:, 2])).astype(float),
        "width": prediction[:, 2] - prediction[:, 0], "crossing_fraction": (np.diff(prediction, axis=1) < 0).any(axis=1).astype(float),
        "median_mae": np.abs(target - prediction[:, 1])}


def quantile_bootstrap(frame, draws=1000, seed=17):
    codes, names, _ = week_structure(frame.target_start)
    if len(names) < 2:
        return [], {"weeks": len(names), "draws": 0}
    rng = np.random.default_rng(seed)
    multiplicity = rng.multinomial(len(names), np.full(len(names), 1 / len(names)), size=draws)
    counts = np.bincount(codes, minlength=len(names))
    total = multiplicity @ counts
    intervals = []
    for key, loss in quantile_losses(frame).items():
        sums = np.bincount(codes, weights=loss, minlength=len(names))
        values = (multiplicity @ sums) / total
        intervals.append({"metric": key, "low": float(np.quantile(values, .025)), "high": float(np.quantile(values, .975)),
                          "valid_draws": len(values), "invalid_draws": 0})
    return intervals, {"weeks": len(names), "draws": draws}
