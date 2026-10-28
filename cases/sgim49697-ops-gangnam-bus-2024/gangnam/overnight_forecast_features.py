"""학습기만으로 링크를 고정하고 실제 시간 간격과 공개 지연을 지키는 예측 특징을 만든다."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, digest, read_yaml, sha256, write_json
from .overnight_forecast_data import BASE, OUT, allowed_months

CALENDAR = ["link_id", "hour", "weekday", "month", "weekend", "korean_public_holiday"]


def metadata_signature(row, fields):
    return {name: float(row[name]) if name == "거리" else str(row[name]) for name in fields}


def read_road(scope):
    cfg = read_yaml("overnight_forecast_config.yaml")
    allowed_months(scope, cfg)
    scopes = ["development"] + (["test"] if scope == "test" else [])
    entries, frames = [], []
    for name in scopes:
        entries.extend(json.loads((OUT / f"extraction_{name}.json").read_text()))
    for entry in entries:
        path = CASE / entry["path"]
        if not path.resolve().is_relative_to(BASE.resolve()) or sha256(path) != entry["sha256"]:
            raise ValueError("예측 개발·시험 가공물 경로 또는 해시 불일치")
        frame = pd.read_parquet(path)
        if frame.interval_start_kst.dt.year.ge(cfg["locked_year"]).any():
            raise ValueError("잠금 연도 접근 금지")
        if ((frame.speed_kmh.notna()) & ~frame.is_valid).any():
            raise ValueError("무효 속도에 값이 남아 있습니다")
        frames.append(frame[["link_id", "interval_start_kst", "speed_kmh"]])
    frame = pd.concat(frames, ignore_index=True)
    if frame.duplicated(["link_id", "interval_start_kst"]).any():
        raise ValueError("예측 링크·시각 중복")
    end = cfg["splits"]["test" if scope == "test" else "decision"][1]
    index = pd.date_range(cfg["splits"]["train"][0], end + " 23:00", freq="h", tz=cfg["timezone"])
    matrix = frame.pivot(index="interval_start_kst", columns="link_id", values="speed_kmh").reindex(index)
    return matrix, entries


def select_links(matrix, entries, cfg):
    train = matrix.loc[cfg["splits"]["train"][0]:cfg["splits"]["train"][1]]
    fields = cfg["link_selection"]["stable_fields"]
    variants, examples = {}, {}
    for entry in entries:
        if not cfg["splits"]["train"][0][:7] <= entry["month"] <= cfg["splits"]["train"][1][:7]:
            continue
        for row in entry["metadata"]:
            link = row["링크아이디"]
            signature = metadata_signature(row, fields)
            variants.setdefault(link, set()).add(digest(signature))
            examples.setdefault(link, signature)
    rows, chosen = [], {}
    for link in matrix.columns:
        coverage = float(train[link].notna().mean())
        stable = len(variants.get(link, set())) == 1
        keep = stable and coverage >= cfg["link_selection"]["training_coverage_minimum"]
        rows.append({"link_id": link, "training_coverage": coverage, "metadata_variants": len(variants.get(link, set())),
                     "selected": keep, "primary_link": link in cfg["primary_links"]})
        if keep:
            chosen[link] = {"metadata": examples[link], "training_coverage": coverage,
                            "relative_q20_kmh": float(train[link].quantile(.2))}
    if not set(cfg["primary_links"]).issubset(chosen):
        raise ValueError("핵심 3개 링크 일부가 사전 학습기 품질 기준을 통과하지 못했습니다")
    return chosen, pd.DataFrame(rows)


def mask_changed_metadata(matrix, entries, chosen, cfg):
    """날짜별 속성 복원을 추측하지 않고 변경이 기록된 월 전체를 보수적으로 제외한다."""
    matrix = matrix.reindex(columns=sorted(chosen)).copy()
    exclusions = []
    for entry in entries:
        for link in chosen:
            rows = [r for r in entry["metadata"] if r["링크아이디"] == link]
            changed = not rows or any(metadata_signature(r, cfg["link_selection"]["stable_fields"]) != chosen[link]["metadata"] for r in rows)
            if changed:
                mask = matrix.index.strftime("%Y-%m") == entry["month"]
                observed = int(matrix.loc[mask, link].notna().sum())
                matrix.loc[mask, link] = np.nan
                exclusions.append({"month": entry["month"], "link_id": link, "masked_observed_hours": observed,
                                   "reason": "metadata_changed_or_absent"})
    return matrix, exclusions


def speed_features(series, horizon, cfg):
    """고정 한 시간 격자에서 지연하며, 결측 행을 제거한 뒤 shift하지 않는다."""
    if horizon not in cfg["horizons"] or not series.index.equals(pd.date_range(series.index[0], series.index[-1], freq="h")):
        raise ValueError("허용된 예측 간격과 연속 한 시간 격자가 필요합니다")
    features = {}
    weekly = cfg["availability"]["weekly_delayed"]["target_relative_lags_hours"]
    for lag in weekly:
        if lag <= horizon:
            raise ValueError("지연 관측이 예측 원점보다 미래입니다")
        features[f"speed_weekly_lag_{lag}"] = series.shift(lag)
    recent = cfg["availability"]["recent_road_assumption"]
    for lag in recent["origin_relative_lags_hours"]:
        if lag < 2:
            raise ValueError("최근 도로 특징의 처리 여유 한 시간이 없습니다")
        features[f"speed_origin_lag_{lag}"] = series.shift(lag + horizon - 1)
    latest = series.shift(horizon + 1)
    for window in recent["rolling_hours"]:
        rolling = latest.rolling(window, min_periods=1)
        features[f"speed_recent_mean_{window}"] = rolling.mean()
        features[f"speed_recent_std_{window}"] = rolling.std(ddof=0)
        features[f"speed_recent_count_{window}"] = rolling.count()
    return pd.DataFrame(features, index=series.index)


def build_frame(matrix, chosen, horizon, cfg, bus=None):
    import holidays

    years = sorted(set(matrix.index.year))
    holiday_dates = set(holidays.KR(years=years))
    parts = []
    for link in matrix:
        frame = speed_features(matrix[link], horizon, cfg)
        frame["link_id"] = link
        frame["hour"] = frame.index.hour.astype("int8")
        frame["weekday"] = frame.index.dayofweek.astype("int8")
        frame["month"] = frame.index.month.astype("int8")
        frame["weekend"] = (frame.index.dayofweek >= 5).astype("int8")
        frame["korean_public_holiday"] = np.array([d in holiday_dates for d in frame.index.date], dtype="int8")
        frame["speed_kmh"] = matrix[link]
        frame["label_10"] = (matrix[link] < 10).astype(float).where(matrix[link].notna())
        frame["label_q20"] = (matrix[link] < chosen[link]["relative_q20_kmh"]).astype(float).where(matrix[link].notna())
        if bus is not None:
            delayed = bus.reindex(matrix.index).shift(cfg["availability"]["delayed_bus_ablation"]["earliest_target_relative_lag_hours"])
            frame = frame.join(delayed, validate="one_to_one")
        frame["target_start"] = frame.index
        frame["origin"] = frame.index - pd.Timedelta(hours=horizon - 1)
        frame["split"] = "outside"
        for name, (start, end) in cfg["splits"].items():
            frame.loc[start:end, "split"] = name
        for column in frame.select_dtypes("float64"):
            frame[column] = frame[column].astype("float32")
        parts.append(frame.reset_index(drop=True))
    return pd.concat(parts, ignore_index=True)


def feature_sets(frame):
    weekly = [c for c in frame if c.startswith("speed_weekly_")]
    recent = [c for c in frame if c.startswith("speed_") and c != "speed_kmh"]
    result = {"calendar_only": CALENDAR, "weekly_delayed": CALENDAR + weekly,
              "recent_road_assumption": CALENDAR + recent}
    bus = [c for c in frame if c.startswith("bus_")]
    if bus:
        result["delayed_bus_ablation"] = CALENDAR + recent + bus
    return result


def prepare(scope="development"):
    cfg = read_yaml("overnight_forecast_config.yaml")
    matrix, entries = read_road(scope)
    selected_path = OUT / "selected_links.json"
    if scope == "development":
        if (OUT / "selection_manifest.json").exists():
            raise ValueError("시험 전 동결 이후에는 개발 특징을 다시 작성하지 않습니다")
        chosen, selection = select_links(matrix, entries, cfg)
        write_json(selected_path, chosen)
        selection.to_csv(OUT / "link_selection_audit.csv", index=False)
    else:
        chosen = json.loads(selected_path.read_text())
    matrix, exclusions = mask_changed_metadata(matrix, entries, chosen, cfg)
    bus_path = BASE / ("bus_hourly_test_features.parquet" if scope == "test" else "bus_hourly_features.parquet")
    bus = None
    if bus_path.exists():
        info = json.loads(bus_path.with_suffix(".json").read_text())
        if info["sha256"] != sha256(bus_path):
            raise ValueError("버스 지연 특징 해시 불일치")
        bus = pd.read_parquet(bus_path).set_index("interval_start_kst")
    outputs, quality = [], []
    for horizon in cfg["horizons"]:
        frame = build_frame(matrix, chosen, horizon, cfg, bus)
        if scope == "test":
            frame = frame[frame.split.eq("test")]
        target = BASE / f"features_{scope}_h{horizon}.parquet"
        frame.to_parquet(target, index=False)
        outputs.append({"horizon": horizon, "path": str(target.relative_to(CASE)), "sha256": sha256(target),
                        "rows": len(frame), "feature_sets": feature_sets(frame)})
        quality.append(frame.groupby(["split", "link_id"]).speed_kmh.agg(["count", "size"]).reset_index().assign(horizon=horizon))
        print(f"예측 특징: {scope} {horizon}시간 {len(frame):,}행, {len(chosen)}개 링크", flush=True)
    pd.concat(quality, ignore_index=True).to_csv(OUT / f"coverage_{scope}.csv", index=False)
    write_json(OUT / f"feature_audit_{scope}.json", {"protocol_sha256": sha256(CASE / "overnight_forecast_config.yaml"),
        "selected_links_sha256": sha256(selected_path), "code_sha256": sha256(Path(__file__)), "outputs": outputs,
        "metadata_exclusions": exclusions, "bus_features_available": bus is not None,
        "inputs": [{"path": e["path"], "sha256": e["sha256"]} for e in entries]})
