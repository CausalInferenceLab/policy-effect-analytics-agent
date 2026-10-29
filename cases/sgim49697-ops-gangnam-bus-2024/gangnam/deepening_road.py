"""고정한 일반도로 링크의 다년·시간대 비교와 원래 핵심 결과 재현을 기록한다."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .overnight_persistence import periods
from .overnight_road_context import speed_daily
from .overnight_road_persistence import read_speed
from .overnight_sensitivity import describe_comparison

CONFIG = CASE / "deepening_road_config.yaml"
OUT = CASE / "results/deepening/road_context"


def validate_scope(cfg):
    months = cfg["months"]
    if len(set(months)) != len(months) or any(pd.Period(m).year >= cfg["locked_year"] for m in months):
        raise ValueError("중복 월 또는 잠금 연도의 도로 값 접근 금지")
    links = [link for group in cfg["groups"].values() for link in group["links"]]
    if not links or len(links) != len(set(links)):
        raise ValueError("공간 집단의 링크가 비었거나 중복됩니다")
    for start, end in cfg["periods"].values():
        if start > end or pd.Timestamp(end).year >= cfg["locked_year"]:
            raise ValueError("비교 기간의 순서 또는 잠금 연도 오류")


def select_fixed_cells(selected, cfg):
    """지정 링크·시간의 원래 셀이 빠지면 실패하며 더 좋은 사후 셀로 채우지 않는다."""
    frame = selected[selected.scope.eq(cfg["original_scope"])].copy()
    result = []
    for group, spec in cfg["groups"].items():
        for band, hours in cfg["bands"].items():
            cells = frame[frame.band.eq(band) & frame.link_id.isin(spec["links"])].copy()
            expected = {(link, hour) for link in spec["links"] for hour in hours}
            actual = list(zip(cells.link_id, cells.hour, strict=True))
            if len(actual) != len(expected) or set(actual) != expected:
                raise ValueError(f"원래 고정 셀의 누락·중복·다른 시간: {group}/{band}")
            if cells.length.isna().any() or cells.length.le(0).any():
                raise ValueError("고정 도로 길이가 누락되거나 양수가 아닙니다")
            cells["original_group"] = cells.group
            cells["group"] = group
            result.append(cells)
    return pd.concat(result, ignore_index=True)


def reproduce_core(daily, cfg):
    """이전 2024~2025년 핵심 집단 일별 결과와 수치·누락·분모를 대조한다."""
    audit_path = CASE / cfg["original_daily_audit"]
    audit = json.loads(audit_path.read_text())
    path = CASE / audit["daily_all_path"]
    if not path.resolve().is_relative_to((CASE / "data/overnight").resolve()) or sha256(path) != audit["daily_all_sha256"]:
        raise ValueError("원래 도로 일별 결과의 경로·해시 변경")
    old = pd.read_parquet(path)
    old = old[old.metric.eq("speed_kmh") & old.scope.eq("core")].copy()
    old["group"] = "core_" + old.group
    keys = ["date", "group", "band", "method"]
    values = ["index", "coverage", "unit_coverage"]
    new = daily[daily.group.str.startswith("core_") & daily.date.ge("2024-01-01")]
    joined = new[keys + values].merge(old[keys + values], on=keys, how="outer", validate="one_to_one",
                                     suffixes=("_new", "_original"), indicator=True)
    if not joined._merge.eq("both").all():
        raise ValueError("기존 도로 일별 비교의 날짜·집단 범위 불일치")
    checks = []
    for field in values:
        a, b = joined[field + "_new"].to_numpy(), joined[field + "_original"].to_numpy()
        if not np.allclose(a, b, rtol=1e-10, atol=1e-10, equal_nan=True):
            raise ValueError("원래 핵심 도로 일별 수치 재현 실패: " + field)
        checks.append(dict(field=field, rows=len(joined), maximum_absolute_difference=float(np.nanmax(np.abs(a - b))),
                           missing_pattern_agrees=bool(np.array_equal(np.isnan(a), np.isnan(b)))))
    return dict(audit_path=str(audit_path.relative_to(CASE)), audit_sha256=sha256(audit_path),
                path=str(path.relative_to(CASE)), sha256=sha256(path), checks=checks)


def run():
    cfg = read_yaml(CONFIG)
    validate_scope(cfg)
    event_path = CASE / cfg["event_sources"]
    event = json.loads(event_path.read_text())
    for entry in event["files"]:
        path = CASE / entry["path"]
        if not path.resolve().is_relative_to((CASE / "data/deepening/references").resolve()) or sha256(path) != entry["sha256"]:
            raise ValueError("동시 공사 원문 경로·해시 변경")
    calendar = periods(cfg)
    dates = sorted({date for values in calendar.values() for date in values})
    speed, original, checked, sources = read_speed(cfg)
    cells = select_fixed_cells(original, cfg)
    links = cells.link_id.unique()
    checked = checked[checked.link_id.isin(links)].copy()
    metadata_pass = checked.groupby("link_id").metadata_pass.all()
    for spec in cfg["groups"].values():
        recorded = checked[checked.link_id.isin(spec["links"])]
        if not recorded.direction_original.eq(spec["direction"]).all():
            raise ValueError("지정한 방향과 원래 링크 방향이 다릅니다")
    comparisons, single, dailies = [], [], []
    for (group, band), part in cells.groupby(["group", "band"]):
        valid_meta = bool(metadata_pass.reindex(part.link_id.unique()).eq(True).all())
        for method in cfg["speed_aggregations"]:
            daily = speed_daily(speed, part, dates, method, cfg["minimum_daily_coverage"])
            labels = dict(group=group, band=band, method=method, selected_links=part.link_id.nunique(), selected_cells=len(part))
            dailies.append(daily.assign(**labels, metadata_pass=valid_meta))
            for name, (before, after) in cfg["comparisons"].items():
                result = describe_comparison(daily, calendar[before], calendar[after], cfg,
                                             interval=method == "fixed_length_arithmetic")
                comparisons.append({**labels, "comparison": name, **result, "metadata_pass": valid_meta,
                                    "quality_pass": bool(result["quality_pass"] and valid_meta)})
        if band == "evening":
            for link, link_cells in part.groupby("link_id"):
                daily = speed_daily(speed, link_cells, dates, "equal_cells", cfg["minimum_daily_coverage"])
                for name, (before, after) in cfg["comparisons"].items():
                    result = describe_comparison(daily, calendar[before], calendar[after], cfg, interval=True)
                    single.append(dict(group=group, link_id=link, comparison=name, **result,
                                       metadata_pass=bool(metadata_pass[link])))
    daily = pd.concat(dailies, ignore_index=True)
    reproduction = reproduce_core(daily, cfg)
    single = pd.DataFrame(single)
    single["quality_pass"] &= single.metadata_pass
    outputs = {"selected_cells.csv": cells, "metadata_check.csv": checked,
               "group_comparisons.csv": pd.DataFrame(comparisons), "single_link_evening.csv": single,
               "daily_indices.csv": daily}
    OUT.mkdir(parents=True, exist_ok=True)
    for name, frame in outputs.items():
        frame.to_csv(OUT / name, index=False, lineterminator="\n")
    files = [str(CONFIG.relative_to(CASE)), cfg["event_sources"], cfg["original_selection"], cfg["original_selection_audit"],
             "gangnam/overnight_road_persistence.py", "gangnam/overnight_road_context.py", "gangnam/overnight_persistence.py",
             "gangnam/overnight_sensitivity.py", "gangnam/directional.py", "directional_config.yaml", "data_contract.yaml",
             *cfg["speed_manifests"]]
    write_json(OUT / "audit.json", dict(completed_at=utcnow(), configuration=cfg, calendar=calendar,
               code_sha256=sha256(Path(__file__)), inputs={name: sha256(CASE / name) for name in files},
               sources=sources, reproduction=reproduction, comparisons=len(comparisons),
               quality_pass=int(outputs["group_comparisons.csv"].quality_pass.sum()),
               metadata_comparisons=len(checked), metadata_pass=int(checked.metadata_pass.sum()),
               outputs={name: sha256(OUT / name) for name in outputs}))
    print(f"공간 집단 {len(comparisons)}개 비교와 저녁 개별 링크 {len(single)}개 비교 완료", flush=True)
