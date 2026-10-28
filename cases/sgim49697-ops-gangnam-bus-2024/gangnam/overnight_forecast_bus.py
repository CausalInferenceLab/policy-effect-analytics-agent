"""학습기에 관측된 고정 버스 셀의 과거 기록을 일반도로 예측의 지연 보조 특징으로 만든다."""

from __future__ import annotations

import gc
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, write_json
from .directional import CELL
from .overnight_bus import make_time_panel
from .overnight_bus_extract import load_wide
from .overnight_forecast_data import BASE, OUT


def group_features(panel, keys, source_days, train_end, value, prefix, nonnegative, selected=None):
    """사전 관측률로만 셀을 고정하고 원본 날짜 부재를 0으로 표시하지 않는다."""
    if selected is None:
        train_days = [d for d in source_days if d <= train_end]
        train = panel[panel.date.le(train_end)]
        recorded = train[value].ge(0) if nonnegative else train[value].gt(0)
        counts = train.loc[recorded].groupby(keys, observed=True).size()
        selected = counts[counts.ge(len(train_days) * .8)].rename("train_count").reset_index()
        selected["training_observation_fraction"] = selected.train_count / len(train_days)
    elif selected.duplicated(keys).any() or selected[keys].isna().any().any():
        raise ValueError("동결된 버스 셀 키 중복 또는 결측")
    if selected.empty:
        raise ValueError("학습기 버스 관측률 80%를 통과하는 고정 셀이 없습니다")
    data = panel.merge(selected[keys], on=keys, how="inner", validate="many_to_one")
    data["valid_value"] = data[value].where(data[value].ge(0) if nonnegative else data[value].gt(0))
    expected = selected.groupby(["group", "hour"], observed=True).size().rename("expected_cells")
    daily = data.groupby(["date", "group", "hour"], observed=True).agg(mean=("valid_value", "mean"), count=("valid_value", "count"))
    daily = daily.join(expected, on=["group", "hour"])
    daily["fraction"] = daily["count"] / daily.expected_cells
    daily.loc[daily.fraction.lt(.8), "mean"] = np.nan
    dates = pd.date_range(min(source_days), max(source_days), freq="D").strftime("%Y-%m-%d")
    grid = pd.DataFrame({"date": dates}).merge(expected.reset_index(), how="cross").set_index(["date", "group", "hour"])
    daily = grid.join(daily[["mean", "fraction"]]).reset_index()
    present = daily.date.isin(source_days)
    daily.loc[present & daily.fraction.isna(), "fraction"] = 0.
    daily.loc[~present, ["mean", "fraction"]] = np.nan
    daily["interval_start_kst"] = pd.to_datetime(daily.date).dt.tz_localize("Asia/Seoul") + pd.to_timedelta(daily.hour, unit="h")
    columns = ["mean"] if nonnegative else ["mean", "fraction"]
    output = daily.pivot(index="interval_start_kst", columns="group", values=columns)
    output.columns = [f"bus_{group}_{prefix}_{stat}" for stat, group in output.columns]
    return output, selected, daily


def prepare():
    if (OUT / "selection_manifest.json").exists():
        raise ValueError("모델 동결 뒤 개발 버스 특징을 바꾸지 않습니다")
    cfg = read_yaml("overnight_multiyear_config.yaml")
    months = [str(x) for x in pd.period_range(*cfg["forecast_development_range"], freq="M")]
    train_end = read_yaml("overnight_forecast_config.yaml")["splits"]["train"][1]
    base = read_yaml("directional_config.yaml")
    base["hours"] = cfg["parse_hours"]
    stations = pd.read_csv(CASE / "results/directional/station_registry.csv", dtype={"stop": str, "ars": str})
    frames, audits = [], {}
    for kind in ["bus_time", "bus_trips"]:
        wide, audit = load_wide("multiyear", kind, months)
        if kind == "bus_time":
            panel, repeated = make_time_panel(wide, stations, base)
            keys, value, prefix = CELL, "raw_value", "recorded_time"
        else:
            repeated_mask = wide.duplicated(["date", "route", "stop"], keep=False)
            repeated = int(repeated_mask.sum())
            wide = wide[~repeated_mask].copy()
            wide["group"] = wide.stop.map(stations.set_index("stop").group)
            wide = wide[wide.group.isin(base["primary_groups"] + base["secondary_groups"])]
            panel = wide.melt(id_vars=["date", "route", "stop", "group"], value_vars=[f"h{h:02}" for h in cfg["parse_hours"]],
                              var_name="hour", value_name="raw_value")
            panel["hour"] = panel.hour.str[1:].astype(int)
            keys, value, prefix = ["group", "route", "stop", "hour"], "raw_value", "recorded_trips"
        del wide
        for column in set(keys) - {"hour"}:
            panel[column] = panel[column].astype("category")
        frame, chosen, daily = group_features(panel, keys, audit["source_available_dates"], train_end, value, prefix, kind == "bus_trips")
        frames.append(frame)
        chosen.to_csv(OUT / f"bus_selected_cells_{kind}.csv", index=False)
        daily.to_csv(OUT / f"bus_feature_coverage_{kind}.csv", index=False)
        audit.update(excluded_revisit_rows=repeated, selected_cells=len(chosen), panel_rows=len(panel))
        audits[kind] = audit
        del panel, daily
        gc.collect()
        print(f"예측 버스 보조 특징 준비: {kind}, 사전 고정 {len(chosen):,}개 셀", flush=True)
    features = pd.concat(frames, axis=1).sort_index()
    grid = pd.date_range(months[0] + "-01", pd.Period(months[-1]).end_time.floor("h"), freq="h", tz="Asia/Seoul")
    features = features.reindex(grid).rename_axis("interval_start_kst").reset_index()
    path = BASE / "bus_hourly_features.parquet"
    features.to_parquet(path, index=False)
    write_json(path.with_suffix(".json"), {"path": str(path.relative_to(CASE)), "sha256": sha256(path),
        "code_sha256": sha256(Path(__file__)), "columns": list(features.columns), "rows": len(features),
        "note": "이 파일은 관측 시각 기준이며 모델 특징 생성 시 168시간 지연. 버스 시각 표기는 원본 시간 라벨로 유지.",
        "selection": "2023~2024 원본이 있는 날짜 중 유효 기록 80% 이상인 셀만 고정. 시간은 양수, 횟수는 비음수.",
        "station_scope": "2023·2024에 확인한 정류장 ID. 2025 물리 위치 이력까지 확인한 것은 아님."})
    write_json(OUT / "bus_feature_audit.json", {"kinds": audits, "feature_sha256": sha256(path), "code_sha256": sha256(Path(__file__))})
