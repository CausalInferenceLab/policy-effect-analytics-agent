"""고정 날짜의 일반도로 전환 주간·추세·기상 조건을 원래 공간 표본에서 기술한다."""

import json
import subprocess

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .deepening_road import select_fixed_cells, validate_scope
from .overnight_persistence import periods
from .overnight_road_context import speed_daily
from .overnight_road_persistence import read_speed

CONFIG = "deepening_transition_config.yaml"
OUT = CASE / "results/deepening/transition"
MANIFEST = OUT / "input_manifest.json"


def validate(cfg):
    if cfg["years"] != [2023, 2024, 2025] or cfg["locked_year"] != 2026:
        raise ValueError("전환 분석의 잠금·연도 범위 변경")
    if (cfg["start_month_day"], cfg["event_month_day"], cfg["end_month_day"]) != ("05-20", "06-29", "08-16"):
        raise ValueError("고정 전환 날짜·창 변경")


def prepare():
    cfg = read_yaml(CONFIG)
    validate(cfg)
    parent = read_yaml(cfg["parent_config"])
    validate_scope(parent)
    paths = [CONFIG, cfg["parent_config"], "results/deepening/road_context/audit.json",
        "results/deepening/road_context/daily_indices.csv", parent["event_sources"], parent["original_selection"],
        parent["original_selection_audit"], *parent["speed_manifests"], "directional_config.yaml", "data_contract.yaml",
        "gangnam/directional.py", "gangnam/overnight_persistence.py", "gangnam/overnight_road_context.py",
        "gangnam/overnight_road_persistence.py", "gangnam/deepening_road.py"]
    for item in cfg["weather"]["sources"]:
        audit = json.loads((CASE / item["audit"]).read_text())
        expected = audit[item["hash_field"]]
        if isinstance(expected, dict):
            expected = expected[(CASE / item["path"]).name]
        if sha256(CASE / item["path"]) != expected:
            raise ValueError("기존 기상 일별 집계 해시 불일치")
        paths.extend([item["path"], item["audit"]])
    inputs = {name: sha256(CASE / name) for name in paths}
    if MANIFEST.exists():
        old = json.loads(MANIFEST.read_text())
        if old["inputs"] != inputs or old["configuration"] != cfg:
            raise ValueError("기존 전환 분석 명세 변경")
        return
    write_json(MANIFEST, dict(prepared_at=utcnow(), configuration=cfg, inputs=inputs,
        interpretation="기존 관측의 후속 분석; 전환 날짜를 검색하지 않고 사전에 고정한 세 모형을 모두 보고"))


def verify():
    cfg = read_yaml(CONFIG)
    validate(cfg)
    audit = json.loads(MANIFEST.read_text())
    if cfg != audit["configuration"]:
        raise ValueError("전환 분석 설정 변경")
    for name, expected in audit["inputs"].items():
        if sha256(CASE / name) != expected:
            raise ValueError("전환 분석 입력 해시 변경: " + name)
    relative = str(MANIFEST.relative_to(CASE.parents[1]))
    content = subprocess.run(["git", "show", "HEAD:" + relative], cwd=CASE, capture_output=True, check=True).stdout
    if content != MANIFEST.read_bytes():
        raise ValueError("전환 분석 전에 입력 명세를 커밋해야 합니다")
    return cfg, read_yaml(cfg["parent_config"])


def design(frame, event, specification, with_weather=False):
    dates = pd.to_datetime(frame.date)
    days = (dates - pd.Timestamp(event)).dt.days.to_numpy(dtype=float)
    x = pd.DataFrame({"intercept": np.ones(len(frame)), "post": (days >= 0).astype(float)}, index=frame.index)
    for weekday in range(1, 5):
        x[f"weekday_{weekday}"] = (dates.dt.dayofweek == weekday).to_numpy(dtype=float)
    if specification != "weekday_level":
        x["days"] = days
    if specification == "weekday_trend_level_slope":
        x["post_days"] = np.maximum(days, 0)
    if with_weather:
        if frame.precipitation_mm.lt(0).any():
            raise ValueError("음수 강수량의 회귀 입력 금지")
        x["log1p_precipitation_mm"] = np.log1p(frame.precipitation_mm)
        x["temperature_c"] = frame.temperature_c
    return x


def fit_description(frame, event, specification, cfg, with_weather=False, denominator=None):
    if specification not in cfg["specifications"] or frame.date.duplicated().any():
        raise ValueError("알 수 없는 회귀식 또는 날짜 중복")
    variables = ["index", "precipitation_mm", "temperature_c"] if with_weather else ["index"]
    valid = frame.dropna(subset=variables).sort_values("date").copy()
    denominator = frame[frame["index"].notna()] if denominator is None else denominator
    before, after = valid.date.lt(event), valid.date.ge(event)
    n_before, n_after = int(before.sum()), int(after.sum())
    all_before, all_after = int(denominator.date.lt(event).sum()), int(denominator.date.ge(event).sum())
    retained_before = n_before / all_before if all_before else 0.
    retained_after = n_after / all_after if all_after else 0.
    record = dict(rows=len(valid), before_rows=n_before, after_rows=n_after,
        denominator_before=all_before, denominator_after=all_after, retained_before=retained_before, retained_after=retained_after)
    if not len(valid):
        return dict(**record, quality_pass=False, reason="no_observed_rows"), pd.DataFrame()
    x = design(valid, event, specification, with_weather)
    y = valid["index"].to_numpy(dtype=float)
    if not np.isfinite(x.to_numpy()).all() or not np.isfinite(y).all():
        raise ValueError("회귀 입력의 비유한 값")
    beta, _, rank, _ = np.linalg.lstsq(x.to_numpy(), y, rcond=None)
    fitted = x.to_numpy() @ beta
    residual = y - fitted
    params = dict(zip(x.columns, beta, strict=True))
    quality = min(n_before, n_after) >= cfg["minimum_observed_days_each_side"] and min(retained_before, retained_after) >= cfg["minimum_observed_fraction"] and rank == x.shape[1]
    record.update(quality_pass=bool(quality), reason="ok" if quality else "support_or_rank_failed", rank=int(rank), columns=x.shape[1],
        level_kmh=float(params["post"]), pre_slope_kmh_per_day=float(params.get("days", 0.)),
        slope_change_kmh_per_day=float(params.get("post_days", 0.)), day30_shift_kmh=float(params["post"] + 30 * params.get("post_days", 0.)),
        rmse_kmh=float(np.sqrt(np.mean(residual**2))), residual_consecutive_observation_correlation=float(pd.Series(residual).autocorr()) if len(valid) > 2 and np.std(residual) > 1e-10 else np.nan,
        precipitation_coefficient=float(params.get("log1p_precipitation_mm", np.nan)), temperature_coefficient=float(params.get("temperature_c", np.nan)),
        condition_number=float(np.linalg.cond(x.to_numpy())))
    output = valid[["date", "index"]].copy()
    output["fitted"], output["residual"] = fitted, residual
    return record, output


def weekly_table(daily, cfg, parent):
    rows = []
    for (scope, group, link, band, method, year), frame in daily.groupby(["scope", "group", "link_id", "band", "method", "year"], dropna=False):
        frame = frame.copy()
        dates = pd.to_datetime(frame.date)
        frame["week_start"] = (dates - pd.to_timedelta(dates.dt.dayofweek, unit="D")).dt.strftime("%Y-%m-%d")
        event = pd.Timestamp(f"{year}-" + cfg["event_month_day"])
        anchor = event + pd.Timedelta(days=7 - event.dayofweek)
        pre_start, pre_end = parent["periods"]["pre" + str(year)]
        reference = frame.loc[frame.date.between(pre_start, pre_end), "index"].mean()
        for week, part in frame.groupby("week_start"):
            known = int(part["index"].notna().sum())
            sufficient = known >= cfg["weekly_minimum_observed_days"]
            mean = part["index"].mean()
            rows.append(dict(scope=scope, group=group, link_id=link, band=band, method=method, year=year,
                week_start=week, relative_week=int((pd.Timestamp(week) - anchor).days // 7),
                expected_days=len(part), observed_days=known, quality_pass=sufficient,
                speed_kmh=float(mean) if sufficient else np.nan, pre_mean_kmh=reference,
                change_from_pre_pct=float(100 * (mean / reference - 1)) if sufficient and reference > 0 else np.nan,
                event_within_week=pd.Timestamp(week) <= event < pd.Timestamp(week) + pd.Timedelta(days=7)))
    return pd.DataFrame(rows)


def run():
    cfg, parent = verify()
    calendar_cfg = {**parent, "periods": {str(year): [f"{year}-" + cfg["start_month_day"], f"{year}-" + cfg["end_month_day"]] for year in cfg["years"]}}
    calendar = periods(calendar_cfg)
    dates = sorted(day for values in calendar.values() for day in values)
    speed, original, metadata, sources = read_speed(parent)
    cells = select_fixed_cells(original, parent)
    selected_meta = metadata[metadata.link_id.isin(cells.link_id.unique())]
    if not selected_meta.metadata_pass.all():
        raise ValueError("전환 분석의 원래 고정 링크 메타데이터 불일치")
    parts = []
    for (group, band), chosen in cells.groupby(["group", "band"]):
        for method in cfg["group_methods"]:
            part = speed_daily(speed, chosen, dates, method, cfg["minimum_daily_coverage"])
            parts.append(part.assign(scope="group", group=group, link_id="", band=band, method=method))
        if band == "evening":
            for link, link_cells in chosen.groupby("link_id"):
                part = speed_daily(speed, link_cells, dates, "equal_cells", cfg["minimum_daily_coverage"])
                parts.append(part.assign(scope="link", group=group, link_id=link, band=band, method="equal_cells"))
    daily = pd.concat(parts, ignore_index=True)
    daily["year"] = daily.date.str[:4].astype(int)
    previous = pd.read_csv(CASE / "results/deepening/road_context/daily_indices.csv")
    key = ["date", "group", "band", "method"]
    values = ["index", "coverage", "unit_coverage"]
    matched = previous[key + values].merge(daily[daily.scope.eq("group")][key + values], on=key,
        validate="one_to_one", how="left", suffixes=("_old", "_new"), indicator=True)
    if not matched._merge.eq("both").all():
        raise ValueError("기존 공간 비교 날짜가 전환 분석에 누락됨")
    for name in values:
        np.testing.assert_allclose(matched[name + "_old"], matched[name + "_new"], rtol=1e-10, atol=1e-10, equal_nan=True)
    weekly = weekly_table(daily, cfg, parent)
    measurements, fitted = [], []
    selected = daily[daily.method.eq("fixed_length_arithmetic") | daily.scope.eq("link")]
    for (scope, group, link, band, year), frame in selected.groupby(["scope", "group", "link_id", "band", "year"]):
        event = f"{year}-" + cfg["event_month_day"]
        for specification in cfg["regressions"]["specifications"]:
            result, predictions = fit_description(frame, event, specification, cfg["regressions"], denominator=frame)
            labels = dict(scope=scope, group=group, link_id=link, band=band, year=year, specification=specification)
            measurements.append(dict(**labels, **result))
            fitted.append(predictions.assign(**labels))
    weather = pd.concat([pd.read_csv(CASE / item["path"]) for item in cfg["weather"]["sources"]], ignore_index=True)
    if weather.duplicated(["station", "date", "band", "alignment_offset"]).any():
        raise ValueError("기존 기상 일별 키 중복")
    weather_rows = []
    evening = selected[selected.scope.eq("group") & selected.band.eq("evening")]
    for station in cfg["weather"]["stations"]:
        for offset in cfg["weather"]["alignment_offsets_hours"]:
            part = weather[weather.station.eq(station) & weather.alignment_offset.eq(offset)]
            joined = evening.merge(part, on=["date", "band"], how="left", validate="many_to_one")
            for (group, year), frame in joined.groupby(["group", "year"]):
                complete = frame.dropna(subset=["index", "precipitation_mm", "temperature_c"])
                denominator = frame[frame["index"].notna()]
                for use_weather in [False, True]:
                    result, _ = fit_description(complete, f"{year}-" + cfg["event_month_day"], "weekday_trend_level", cfg["regressions"],
                        with_weather=use_weather, denominator=denominator)
                    weather_rows.append(dict(group=group, year=year, station=station, alignment_offset=offset,
                        with_weather=use_weather, **result))
    tables = {"daily.csv": daily, "weekly.csv": weekly, "fixed_date_regressions.csv": pd.DataFrame(measurements),
        "fitted_descriptions.csv": pd.concat(fitted, ignore_index=True), "weather_regressions.csv": pd.DataFrame(weather_rows)}
    for name, table in tables.items():
        table.to_csv(OUT / name, index=False, lineterminator="\n")
    write_json(OUT / "audit.json", dict(completed_at=utcnow(), code_sha256=sha256(__file__),
        input_manifest_sha256=sha256(MANIFEST), calendar=calendar, sources=sources,
        reproduced_previous_rows=len(matched), reproduced_fields=values, metadata_rows=len(selected_meta),
        daily_rows=len(daily), weekly_rows=len(weekly), fixed_date_regressions=len(measurements), weather_regressions=len(weather_rows),
        outputs={name: sha256(OUT / name) for name in tables},
        interpretation="모든 날짜·모형을 고정한 기술 회귀. 표준오차·유의확률·인과효과를 추정하지 않음; 기존 속도 가공 자료를 재사용"))
    print(f"전환 주간 {len(daily):,}개 일별 값·고정 날짜 회귀 {len(measurements)}개·기상 짝 회귀 {len(weather_rows)}개", flush=True)
