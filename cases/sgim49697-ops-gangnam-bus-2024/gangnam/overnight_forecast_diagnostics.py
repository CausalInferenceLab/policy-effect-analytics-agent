"""고정 시험 예측의 사건 집중·보정·모델 간 주 단위 차이를 사후 진단한다."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .overnight_forecast_data import OUT, allowed_months
from .overnight_forecast_metrics import week_structure, weighted_probability_metrics

KEY = ["link_id", "target_start"]
PROBABILITY_BINS = [0, .001, .005, .01, .02, .05, .1, .2, .4, .6, .8, 1]


def align_predictions(left, right):
    """행 순서와 무관하게 같은 시각·링크·관측값의 예측만 비교한다."""
    if left.duplicated(KEY).any() or right.duplicated(KEY).any():
        raise ValueError("예측 키가 중복되어 짝 비교를 할 수 없습니다")
    merged = left.merge(right, on=KEY, how="outer", suffixes=("_left", "_right"), indicator=True, validate="one_to_one")
    if not merged._merge.eq("both").all() or not merged.label_left.eq(merged.label_right).all():
        raise ValueError("비교 예측의 표본 또는 목표 라벨이 다릅니다")
    if not np.array_equal(merged.speed_kmh_left, merged.speed_kmh_right):
        raise ValueError("같은 키의 관측 속도가 다릅니다")
    return merged.sort_values(KEY).reset_index(drop=True)


def paired_comparison(left, right, left_threshold, right_threshold, draws=1000, seed=17):
    """같은 주 가중치를 양쪽에 적용한다. 차이는 항상 왼쪽 빼기 오른쪽이다."""
    frame = align_predictions(left, right)
    if frame.empty:
        raise ValueError("짝 비교 표본이 없습니다")
    codes, names, days = week_structure(frame.target_start)
    if len(names) < 2:
        raise ValueError("주 단위 짝 비교에는 최소 두 주가 필요합니다")
    y = frame.label_left.to_numpy()
    scores = [frame.probability_left.to_numpy(), frame.probability_right.to_numpy()]
    thresholds = [left_threshold, right_threshold]
    points = [weighted_probability_metrics(y, p, np.ones(len(y)), threshold, days.sum())
              for p, threshold in zip(scores, thresholds, strict=True)]
    rng = np.random.default_rng(seed)
    multiplicity = rng.multinomial(len(names), np.full(len(names), 1 / len(names)), size=draws)
    metrics = ["average_precision", "brier", "precision", "recall", "false_positive_rate", "alerts_per_day"]
    samples = {key: [] for key in metrics}
    for start in range(0, draws, 100):
        sample = multiplicity[start:start + 100]
        values = [weighted_probability_metrics(y, p, sample[:, codes], threshold, sample @ days)
                  for p, threshold in zip(scores, thresholds, strict=True)]
        for key in metrics:
            samples[key].append(values[0][key] - values[1][key])
    result = []
    for key in metrics:
        values = np.concatenate(samples[key])
        valid = values[np.isfinite(values)]
        result.append({"metric": key, "difference": float(points[0][key][0] - points[1][key][0]),
                       "low": float(np.quantile(valid, .025)) if len(valid) else np.nan,
                       "high": float(np.quantile(valid, .975)) if len(valid) else np.nan,
                       "valid_draws": len(valid), "invalid_draws": draws - len(valid),
                       "weeks": len(names), "rows": len(frame), "positives": int(y.sum())})
    return result


def reliability(frame, column="probability"):
    probability = frame[column]
    if not probability.between(0, 1).all() or probability.isna().any():
        raise ValueError("보정 진단 확률 범위 오류")
    bins = pd.cut(probability, PROBABILITY_BINS, include_lowest=True, right=True)
    grouped = frame.assign(probability_bin=bins).groupby("probability_bin", observed=False)
    table = grouped.agg(rows=("label", "size"), events=("label", "sum"), mean_probability=(column, "mean"), observed_rate=("label", "mean")).reset_index()
    table["probability_bin"] = table.probability_bin.astype(str)
    return table


def positive_episodes(frame):
    """연속된 실제 한 시간 저속 관측을 묶되 관측 공백을 건너 연결하지 않는다."""
    if frame.duplicated(KEY).any():
        raise ValueError("사건 집계의 시각·링크가 중복됩니다")
    positive = frame[frame.label.eq(1)].sort_values(KEY).copy()
    if positive.empty:
        return pd.DataFrame(columns=["link_id", "start", "last_start", "observed_hours", "minimum_speed"])
    new = positive.link_id.ne(positive.link_id.shift()) | positive.target_start.diff().dt.total_seconds().ne(3600)
    positive["episode"] = new.cumsum()
    return positive.groupby("episode").agg(link_id=("link_id", "first"), start=("target_start", "min"),
        last_start=("target_start", "max"), observed_hours=("label", "size"), minimum_speed=("speed_kmh", "min")).reset_index(drop=True)


def run():
    cfg = read_yaml("overnight_forecast_config.yaml")
    allowed_months("test", cfg)
    audit = json.loads((OUT / "test_evaluation_audit.json").read_text())
    selection = json.loads((OUT / "selected_models_development.json").read_text())
    files = {x["candidate"]: x for x in audit["predictions"]}
    cache = {}

    def load(item):
        name = item["candidate"]
        if name not in cache:
            info = files[name]
            path = CASE / info["path"]
            if sha256(path) != info["sha256"]:
                raise ValueError("시험 예측 해시 불일치")
            frame = pd.read_parquet(path)
            cache[name] = frame[frame.link_id.isin(cfg["primary_links"])].copy()
        return cache[name]

    comparisons, calibration, confusion, support = [], [], [], []
    for horizon in [1, 3]:
        items = [x for x in selection if x["horizon"] == horizon and x["family"] != "quantile"]
        primary = next(x for x in items if x["role"] == "primary_selected")
        for baseline in items:
            if baseline["label"] != "label_10" or baseline["candidate"] == primary["candidate"]:
                continue
            rows = paired_comparison(load(primary), load(baseline), primary["decision"]["threshold"], baseline["decision"]["threshold"])
            comparisons.extend({"horizon": horizon, "left": primary["candidate"], "right": baseline["candidate"], **row} for row in rows)
        for item in items:
            frame = load(item)
            for column in ["raw_probability", "probability"]:
                calibration.append(reliability(frame, column).assign(candidate=item["candidate"], horizon=horizon, label=item["label"], score=column))
            y, alerts = frame.label.eq(1), frame.alert
            confusion.append({"candidate": item["candidate"], "horizon": horizon, "label": item["label"],
                "true_alerts": int((y & alerts).sum()), "false_alerts": int((~y & alerts).sum()),
                "missed_events": int((y & ~alerts).sum()), "true_negatives": int((~y & ~alerts).sum()),
                "event_days": frame.loc[y, "target_start"].dt.date.nunique(),
                "alert_days": frame.loc[alerts, "target_start"].dt.date.nunique()})
        frame = load(primary)
        episodes = positive_episodes(frame)
        episodes.to_csv(OUT / f"test_primary_episodes_h{horizon}.csv", index=False)
        for link, group in frame.groupby("link_id"):
            expected = pd.date_range("2025-05-01", "2025-08-31 23:00", freq="h", tz="Asia/Seoul")
            missing = expected.difference(group.target_start)
            positive = group[group.label.eq(1)]
            support.append({"horizon": horizon, "link_id": link, "observed_hours": len(group), "expected_hours": len(expected),
                "positive_hours": len(positive), "positive_days": positive.target_start.dt.date.nunique(),
                "positive_weeks": positive.target_start.dt.tz_localize(None).dt.to_period("W-SUN").nunique(),
                "episodes": int(episodes.link_id.eq(link).sum()), "missing_hours": len(missing),
                "missing_timestamps_kst": "|".join(x.isoformat() for x in missing)})
    tables = {"test_paired_differences.csv": pd.DataFrame(comparisons), "test_reliability_bins.csv": pd.concat(calibration, ignore_index=True),
              "test_confusion_counts.csv": pd.DataFrame(confusion), "test_event_support.csv": pd.DataFrame(support)}
    for name, table in tables.items():
        table.to_csv(OUT / name, index=False)
    write_json(OUT / "test_diagnostics_audit.json", {"completed_at": utcnow(), "code_sha256": sha256(Path(__file__)),
        "test_evaluation_sha256": sha256(OUT / "test_evaluation_audit.json"), "selection_manifest_sha256": sha256(OUT / "selection_manifest.json"),
        "outputs": {name: sha256(OUT / name) for name in [*tables, "test_primary_episodes_h1.csv", "test_primary_episodes_h3.csv"]},
        "scope": "시험을 본 뒤 추가한 실패 진단. 선택 모델·보정기·임계값은 변경하지 않음. 짝 재표집 구간은 다중 비교 보정 없는 기술 구간이며 인과 효과나 새 우승자 선정 근거가 아님.",
        "bootstrap": {"unit": "같은 달력 주를 모든 링크·시간·두 모델에 함께 적용", "draws": 1000, "seed": 17},
        "probability_bins": PROBABILITY_BINS})
