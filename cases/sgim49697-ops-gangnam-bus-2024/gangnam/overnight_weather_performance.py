"""고정 시험 예측을 실제 관측 날씨로 사후 분류해 오류·구간·기준 모델 차이를 계산한다."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .overnight_baseline_methods import interval_losses, paired_intervals
from .overnight_baseline_runner import verify_manifest
from .overnight_forecast_diagnostics import align_predictions
from .overnight_forecast_metrics import week_structure

OUT = CASE / "results/overnight/weather_performance"


def weather_groups(frame, threshold):
    rain, temperature = frame.precipitation_1h_mm, frame.temperature_c
    if np.isinf(rain).any() or np.isinf(temperature).any() or rain.dropna().lt(0).any():
        raise ValueError("날씨 분류에 무한값 또는 음수 강수량이 있습니다")
    result = frame.copy()
    result["rain_group"] = np.select([rain.eq(0), rain.gt(0)], ["dry", "wet"], default="unknown")
    result["heat_group"] = np.select([temperature.lt(threshold), temperature.ge(threshold)], ["below_30", "at_least_30"], default="unknown")
    return result


def join_weather(predictions, weather, station, threshold):
    if str(predictions.target_start.dt.tz) != "Asia/Seoul":
        raise ValueError("예측 시각은 명시적인 Asia/Seoul 시간대여야 합니다")
    met = weather[weather.station.eq(station)][["datetime_local", "temperature_c", "precipitation_1h_mm"]].copy()
    met["weather_time"] = pd.to_datetime(met.datetime_local, errors="raise")
    if met.weather_time.dt.tz is not None or met.weather_time.duplicated().any():
        raise ValueError("관측소 시각의 시간대 또는 중복 오류")
    result = predictions.assign(weather_time=predictions.target_start.dt.tz_localize(None))
    result = result.merge(met.drop(columns="datetime_local"), on="weather_time", how="left", validate="many_to_one")
    if len(result) != len(predictions):
        raise ValueError("기상 연결로 예측 표본 수가 달라졌습니다")
    return weather_groups(result, threshold)


def read_prediction(ref):
    path = CASE / ref["path"]
    if not path.resolve().is_relative_to((CASE / "data").resolve()) or sha256(path) != ref["sha256"]:
        raise ValueError("날씨별 평가 예측 경로·해시 불일치")
    return pd.read_parquet(path)


def run():
    cfg = read_yaml("overnight_weather_performance_config.yaml")
    _, base, _ = verify_manifest()
    if cfg["locked_year"] != 2026 or cfg["horizons"] != base["horizons"] or cfg["alignment_offset_hours"] != 0:
        raise ValueError("날씨별 평가의 잠금 연도·간격·시각 정렬 설정 오류")
    source_path, weather_path = CASE / cfg["forecast_audit"], CASE / cfg["weather_audit"]
    source, weather_audit = [json.loads(p.read_text()) for p in [source_path, weather_path]]
    hourly_path = CASE / weather_audit["hourly_path"]
    if sha256(hourly_path) != weather_audit["hourly_sha256"]:
        raise ValueError("추가 관측 기상의 시간별 캐시 해시 변경")
    weather = pd.read_parquet(hourly_path)
    inputs = {str(p.relative_to(CASE)): sha256(p) for p in [source_path, weather_path, hourly_path,
              CASE / "overnight_weather_performance_config.yaml", CASE / "gangnam/overnight_baseline_methods.py",
              CASE / "gangnam/overnight_forecast_metrics.py", CASE / "gangnam/overnight_forecast_diagnostics.py"]}
    metrics, paired, support, monthly = [], [], [], []
    for horizon in cfg["horizons"]:
        predictions = {}
        for model in cfg["quantile_models"]:
            ref = next(x for x in source["predictions"] if x["name"] == model and x["variant"] == cfg["quantile_variants"][model] and x["horizon"] == horizon)
            predictions[model] = read_prediction(ref)
            inputs[ref["path"]] = ref["sha256"]
        left, right = [predictions[name] for name in cfg["quantile_models"]]
        align_predictions(left.assign(label=0), right.assign(label=0))
        if not left.target_start.dt.strftime("%Y-%m-%d").between(*base["splits"]["test"]).all() or set(left.link_id) != set(base["primary_links"]):
            raise ValueError("날씨별 평가의 고정 핵심 시험 범위가 다릅니다")
        for station in cfg["stations"]:
            joined = {name: join_weather(frame, weather, station, cfg["heat_threshold_c"]) for name, frame in predictions.items()}
            for scope in cfg["slices"]:
                scoped = {name: frame if scope == "all_hours" else frame[frame.target_start.dt.hour.isin([17, 18, 19])]
                          for name, frame in joined.items()}
                for grouping, values in [("rain_group", ["dry", "wet", "unknown"]), ("heat_group", ["below_30", "at_least_30", "unknown"])]:
                    for value in values:
                        pieces = {name: frame[frame[grouping].eq(value)] for name, frame in scoped.items()}
                        a, b = [pieces[name] for name in cfg["quantile_models"]]
                        weeks = len(week_structure(a.target_start)[1]) if len(a) else 0
                        good = len(a) >= cfg["minimum_rows_for_comparison"] and weeks >= cfg["minimum_calendar_weeks_for_comparison"]
                        tags = {"horizon": horizon, "station": station, "slice": scope, "grouping": grouping, "weather_group": value}
                        support.append({**tags, "rows": len(a), "calendar_weeks": weeks, "unique_hours": a.target_start.nunique(),
                                        "quality_pass": good, "known_weather": value != "unknown"})
                        for name, part in pieces.items():
                            row = {**tags, "model": name, "rows": len(part), "calendar_weeks": weeks, "comparison_quality_pass": good}
                            if len(part):
                                row.update({key: float(v.mean()) for key, v in interval_losses(part).items()})
                                row.update(median_bias_kmh=float((part.q50 - part.speed_kmh).mean()),
                                           below_q10_fraction=float(part.speed_kmh.lt(part.q10).mean()),
                                           above_q90_fraction=float(part.speed_kmh.gt(part.q90).mean()),
                                           mean_actual_speed_kmh=float(part.speed_kmh.mean()))
                            metrics.append(row)
                        if good:
                            differences = paired_intervals(a, b, cfg["bootstrap"]["calendar_weeks"], cfg["bootstrap"]["seed"])
                            paired.extend({**tags, "left": cfg["quantile_models"][0], "right": cfg["quantile_models"][1], **row} for row in differences)
                        counts = a.groupby(a.target_start.dt.strftime("%Y-%m")).size()
                        monthly.extend({**tags, "month": month, "rows": int(count)} for month, count in counts.items())
            print(f"날씨별 예측 오류: h{horizon}, 관측소 {station}", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    tables = {"metrics.csv": pd.DataFrame(metrics), "paired_comparisons.csv": pd.DataFrame(paired),
              "support.csv": pd.DataFrame(support), "stratum_months.csv": pd.DataFrame(monthly)}
    for name, frame in tables.items():
        frame.to_csv(OUT / name, index=False)
    write_json(OUT / "audit.json", {"completed_at": utcnow(), "configuration": cfg, "code_sha256": sha256(Path(__file__)),
                                   "inputs": inputs, "metrics": len(metrics), "paired_metrics": len(paired),
                                   "weather_groups": len(support), "groups_passing_comparison": sum(x["quality_pass"] for x in support),
                                   "outputs": {name: sha256(OUT / name) for name in tables}, "interpretation": cfg["interpretation"]})
