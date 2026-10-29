"""전환 주간 원본과 회귀 계수를 별도 XML·잔차화 계산으로 확인한다."""

import json
import subprocess
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .deepening_road_raw_check import parse_source
from .deepening_transition import OUT, verify

CONFIG = "deepening_transition_check_config.yaml"


def configuration():
    cfg = read_yaml(CONFIG)
    path = CASE / CONFIG
    content = subprocess.run(["git", "show", "HEAD:" + str(path.relative_to(CASE.parents[1]))], cwd=CASE, capture_output=True, check=True).stdout
    if content != path.read_bytes():
        raise ValueError("전환 원본 대조 규칙을 먼저 커밋해야 합니다")
    dates = [str(day.date()) for start, end in cfg["date_windows"] for day in pd.date_range(start, end)]
    if len(dates) != 36 or len(set(dates)) != len(dates) or any(int(day[:4]) >= cfg["locked_year"] for day in dates):
        raise ValueError("전환 원본 대조 날짜·잠금 오류")
    if cfg["workers"] not in [1, 2]:
        raise ValueError("원본 대조 작업자는 최대 2개")
    return cfg, dates


def raw_check():
    cfg, dates = configuration()
    _, parent = verify()
    links = sorted({link for group in parent["groups"].values() for link in group["links"]})
    months = {day[:7] for day in dates}
    all_sources = json.loads((CASE / cfg["source_manifest"]).read_text())["files"]
    sources = [entry for entry in all_sources if entry["month"] in months]
    if len(sources) != len(months) or {entry["month"] for entry in sources} != months:
        raise ValueError("전환 원본의 월 누락·중복")
    jobs = [(entry, [day for day in dates if day.startswith(entry["month"])], links, cfg) for entry in sources]
    with ProcessPoolExecutor(max_workers=cfg["workers"]) as pool:
        parsed = list(pool.map(parse_source, jobs))
    raw = pd.DataFrame([row for records, _ in parsed for row in records])
    cached, seen = [], set()
    for name in cfg["extraction_manifests"]:
        for entry in json.loads((CASE / name).read_text()):
            if entry["month"] not in months:
                continue
            if entry["month"] in seen or sha256(CASE / entry["path"]) != entry["sha256"]:
                raise ValueError("전환 캐시 월 중복·해시 변경")
            seen.add(entry["month"])
            frame = pd.read_parquet(CASE / entry["path"], columns=["link_id", "interval_start_kst", "speed_kmh", "is_valid"])
            frame["date"] = frame.interval_start_kst.dt.strftime("%Y-%m-%d")
            frame["hour"] = frame.interval_start_kst.dt.hour
            frame = frame[frame.date.isin(dates) & frame.link_id.isin(links)].copy()
            frame["cached_speed"] = frame.speed_kmh.where(frame.is_valid & frame.speed_kmh.gt(0))
            cached.append(frame[["date", "link_id", "hour", "cached_speed"]])
    if seen != months:
        raise ValueError("전환 캐시 월 누락")
    checked = raw.merge(pd.concat(cached), on=["date", "link_id", "hour"], how="outer", validate="one_to_one", indicator=True)
    if not checked._merge.eq("both").all() or len(checked) != len(dates) * len(links) * 24:
        raise ValueError("전환 원본·캐시 격자 불일치")
    checked["status_equal"] = checked.source_speed.isna().eq(checked.cached_speed.isna())
    checked["absolute_difference"] = (checked.source_speed - checked.cached_speed).abs()
    checked["value_equal"] = checked.absolute_difference.le(cfg["absolute_tolerance"]) | (checked.source_speed.isna() & checked.cached_speed.isna())
    if not checked.status_equal.all() or not checked.value_equal.all():
        raise ValueError("전환 원본 값·상태 불일치")
    output = OUT / "raw_check_cells.csv"
    checked.drop(columns="_merge").to_csv(output, index=False, lineterminator="\n")
    write_json(OUT / "raw_check.json", dict(completed_at=utcnow(), configuration=cfg,
        code_sha256=sha256(__file__), parser_sha256=sha256(CASE / "gangnam/deepening_road_raw_check.py"),
        inputs={name: sha256(CASE / name) for name in [CONFIG, cfg["selection_config"], cfg["source_manifest"], *cfg["extraction_manifests"]]},
        compared_cells=len(checked), mismatches=0, source_audits=[audit for _, audit in parsed],
        maximum_absolute_difference=float(checked.absolute_difference.max()), outputs={output.name: sha256(output)}))
    print(f"전환 경계 36일·14개 링크·{len(checked):,}개 시간 값/상태 독립 XML 대조 일치", flush=True)


def residualized_coefficient(target, variable, nuisance):
    """다른 열의 QR 공간을 제거한 두 벡터의 단순 기울기다."""
    target, variable, nuisance = np.asarray(target, dtype=float), np.asarray(variable, dtype=float), np.asarray(nuisance, dtype=float)
    if not np.isfinite(target).all() or not np.isfinite(variable).all() or not np.isfinite(nuisance).all():
        raise ValueError("잔차화 계수의 비유한 입력")
    if np.linalg.matrix_rank(nuisance) != nuisance.shape[1]:
        raise ValueError("잔차화 보조 행렬의 계수 부족")
    q, _ = np.linalg.qr(nuisance, mode="reduced")
    x_residual = variable - q @ (q.T @ variable)
    y_residual = target - q @ (q.T @ target)
    denominator = float(x_residual @ x_residual)
    if denominator < 1e-12:
        raise ValueError("잔차화 대상 열이 다른 열과 중복됨")
    return float((x_residual @ y_residual) / denominator)


def coefficients(frame, year, specification, weather):
    dates = pd.to_datetime(frame.date)
    days = (dates - pd.Timestamp(year=year, month=6, day=29)).dt.days.to_numpy(dtype=float)
    columns = {"constant": np.ones(len(frame)), "level_kmh": (days >= 0).astype(float)}
    columns.update({f"day_{weekday}": dates.dt.dayofweek.eq(weekday).to_numpy(dtype=float) for weekday in range(1, 5)})
    if specification != "weekday_level":
        columns["pre_slope_kmh_per_day"] = days
    if specification.endswith("level_slope"):
        columns["slope_change_kmh_per_day"] = days * (days >= 0)
    if weather:
        columns["precipitation_coefficient"] = np.log1p(frame.precipitation_mm.to_numpy())
        columns["temperature_coefficient"] = frame.temperature_c.to_numpy()
    result = {}
    for name in ["level_kmh", "pre_slope_kmh_per_day", "slope_change_kmh_per_day", "precipitation_coefficient", "temperature_coefficient"]:
        if name not in columns:
            continue
        nuisance = np.column_stack([value for label, value in columns.items() if label != name])
        result[name] = residualized_coefficient(frame["index"], columns[name], nuisance)
    result["day30_shift_kmh"] = result["level_kmh"] + 30 * result.get("slope_change_kmh_per_day", 0.)
    return result


def result_check():
    cfg, _ = verify()
    audit_path = OUT / "audit.json"
    audit = json.loads(audit_path.read_text())
    for name, expected in audit["outputs"].items():
        if sha256(OUT / name) != expected:
            raise ValueError("전환 회귀 독립 대조 입력 변경")
    daily = pd.read_csv(OUT / "daily.csv", dtype={"link_id": str}).fillna({"link_id": ""})
    rows = pd.read_csv(OUT / "fixed_date_regressions.csv", dtype={"link_id": str}).fillna({"link_id": ""})
    weather_rows = pd.read_csv(OUT / "weather_regressions.csv")
    source_weather = pd.concat([pd.read_csv(CASE / item["path"]) for item in cfg["weather"]["sources"]], ignore_index=True)
    checks, maximum = 0, 0.
    for table, has_weather in [(rows, False), (weather_rows, True)]:
        for _, row in table.iterrows():
            selected = daily[daily.group.eq(row.group) & daily.year.eq(row.year)]
            if has_weather:
                selected = selected[selected.scope.eq("group") & selected.band.eq("evening") & selected.method.eq("fixed_length_arithmetic")]
                met = source_weather[source_weather.station.eq(row.station) & source_weather.alignment_offset.eq(row.alignment_offset) & source_weather.band.eq("evening")]
                selected = selected.merge(met, on=["date", "band"], validate="one_to_one").dropna(subset=["index", "precipitation_mm", "temperature_c"])
                specification, use_weather = "weekday_trend_level", bool(row.with_weather)
            else:
                selected = selected[selected.scope.eq(row.scope) & selected.link_id.eq(row.link_id) & selected.band.eq(row.band)]
                if row.scope == "group":
                    selected = selected[selected.method.eq("fixed_length_arithmetic")]
                selected = selected.dropna(subset="index")
                specification, use_weather = row.specification, False
            actual = coefficients(selected, int(row.year), specification, use_weather)
            if len(selected) != row.rows or selected.date.duplicated().any():
                raise ValueError("독립 회귀의 행 수·중복 오류")
            for name, value in actual.items():
                difference = abs(value - row[name])
                maximum = max(maximum, difference)
                if not np.isclose(value, row[name], rtol=1e-10, atol=1e-10):
                    raise ValueError("전환 회귀 계수의 독립 잔차화 대조 불일치: " + name)
                checks += 1
    if len(rows) != 270 or len(weather_rows) != 216:
        raise ValueError("전환 회귀의 고정 조합 수 불일치")
    write_json(OUT / "result_validation.json", dict(completed_at=utcnow(), code_sha256=sha256(__file__),
        audit_sha256=sha256(audit_path), regression_rows=len(rows) + len(weather_rows), coefficient_values=checks,
        maximum_absolute_difference=maximum, mismatches=0,
        method="기존 설계·적합 함수를 호출하지 않고 각 계수를 QR 잔차화 기울기로 재계산; 표준오차/인과식별 검증은 아님"))
    print(f"전환 회귀 {len(rows) + len(weather_rows)}행·{checks}개 계수/대비의 독립 잔차화 대조 일치", flush=True)
