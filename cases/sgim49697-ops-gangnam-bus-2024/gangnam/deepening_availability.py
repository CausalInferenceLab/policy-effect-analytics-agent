"""속도값을 읽지 않고 공식 공개 일정·현재 목록과 예측 시계를 대조한다."""

import html
import json
import re

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .deepening_definitions import Tables

CONFIG = "deepening_availability_config.yaml"
OUT = CASE / "results/deepening/availability"
REFERENCES = OUT / "reference_sources.json"
SCENARIOS = ["guide_next_month_day10_start", "guide_next_month_day11_start", "catalog_created_proxy",
             "catalog_current_version_proxy", "conservative_guide_and_current_version"]


def verify_ref(ref):
    path = (CASE / ref["path"]).resolve()
    if not path.is_relative_to((CASE / "data/deepening/references").resolve()) or sha256(path) != ref["sha256"]:
        raise ValueError("가용 시점 참고 원본 경로·해시 불일치")
    return path


def freeze_references(cfg):
    OUT.mkdir(parents=True, exist_ok=True)
    if REFERENCES.exists():
        saved = json.loads(REFERENCES.read_text())
        if set(saved) != set(cfg["source_ids"]):
            raise ValueError("고정 참고 문서의 범위 변경")
    else:
        manifest = json.loads((CASE / "deepening-reference-sources.json").read_text())
        saved = {entry["id"]: entry for entry in manifest["files"] if entry["id"] in cfg["source_ids"]}
        if set(saved) != set(cfg["source_ids"]):
            raise ValueError("필요한 가용성 참고 문서 누락")
        for entry in saved.values():
            verify_ref(entry)
        write_json(REFERENCES, saved)
    for entry in saved.values():
        verify_ref(entry)
    return saved


def parse_catalog(rows, year, source_entries, timezone="Asia/Seoul"):
    """공개 등록·수정 날짜와 파일 식별자만 내보내며 작성자 식별자는 제외한다."""
    result = []
    if len(rows) != 12:
        raise ValueError("연간 속도 목록이 12개월이 아닙니다")
    for row in rows:
        month = f"{year}-{int(row['months']):02d}"
        if str(row["bdwrDivCd"]) != str(year) or str(row["blbdDivCd"]) != "06":
            raise ValueError("속도 목록의 연도·종류 불일치")
        request = source_entries[month]["request"]
        keys = ["apndFileNm", "apndFilePathNm", "bdwrSeq", "blbdDivCd"]
        if any(str(request[key]) != str(row[key]) for key in keys):
            raise ValueError("현재 목록과 기존 수집 파일 식별자 불일치")
        created, updated = [pd.Timestamp(row[key]).tz_localize(timezone) for key in ["createDate", "updateDate"]]
        next_month = (pd.Period(month, freq="M") + 1).to_timestamp().tz_localize(timezone)
        if created < next_month or updated < created:
            raise ValueError("등록·수정 시각의 순서 또는 자료 월 경계 오류")
        guide10, guide11 = next_month + pd.Timedelta(days=9), next_month + pd.Timedelta(days=10)
        result.append(dict(month=month, file_name=row["apndFileNm"], file_identifier=row["apndFilePathNm"],
            board_sequence=str(row["bdwrSeq"]), catalog_created_at=created, catalog_updated_at=updated,
            catalog_current_version_at=max(created, updated),
            guide_next_month_day10_start=guide10, guide_next_month_day11_start=guide11,
            catalog_created_proxy=created, catalog_current_version_proxy=max(created, updated),
            conservative_guide_and_current_version=max(guide11, created, updated),
            created_days_after_month_end=(created - next_month).total_seconds() / 86400,
            updated_days_after_month_end=(updated - next_month).total_seconds() / 86400,
            updated_after_creation=updated > created,
            cached_source_path=source_entries[month]["path"], cached_source_sha256=source_entries[month]["sha256"],
            metadata_only=True))
    data = pd.DataFrame(result).sort_values("month").reset_index(drop=True)
    if data.month.duplicated().any() or set(data.month) != {f"{year}-{month:02d}" for month in range(1, 13)}:
        raise ValueError("속도 목록의 중복·누락 월")
    return data


def feature_availability(targets, horizon, lag_hours, anchor, releases):
    origins = targets - pd.Timedelta(hours=horizon - 1)
    if anchor not in {"origin", "target"} or lag_hours < 1:
        raise ValueError("지연 특징의 기준·시간 오류")
    source_hours = (origins if anchor == "origin" else targets) - pd.Timedelta(hours=lag_hours)
    if not (source_hours + pd.Timedelta(hours=1) <= origins).all():
        raise ValueError("발행 시각 뒤에 끝나는 자료 시간대")
    months = source_hours.strftime("%Y-%m")
    if not set(months).issubset(releases.index):
        raise ValueError("특징 자료 월의 공개 시각 미확인")
    available_at = pd.DatetimeIndex(releases.loc[months].to_numpy())
    available = available_at <= origins
    return pd.DataFrame(dict(target_start=targets, origin=origins, source_hour=source_hours,
        source_month=months, available_at=available_at, available=available))


def api_fields(path):
    parser = Tables()
    parser.feed(path.read_text(encoding="utf-8"))
    requests = [t for t in parser.tables if t and t[0] == ["변수명", "타입", "변수설명", "값설명"]]
    outputs = [t for t in parser.tables if t and t[0] == ["No", "출력명", "출력설명"]]
    if len(requests) != 1 or len(outputs) != 1:
        raise ValueError("실시간 API 명세의 요청·출력 표 누락")
    request = [row[0] for row in requests[0][1:]]
    output = [row[1] for row in outputs[0][1:] if row[0].isdigit()]
    if request != ["KEY", "TYPE", "SERVICE", "START_INDEX", "END_INDEX", "LINK_ID"]:
        raise ValueError("실시간 API 요청 항목이 검토한 명세와 다릅니다")
    if output != ["LINK_ID", "PRCS_SPD", "PRCS_TRV_TIME"]:
        raise ValueError("실시간 API 출력 항목이 검토한 명세와 다릅니다")
    return dict(request_fields=request, observation_fields=output, observation_timestamp_field_documented=False,
        historical_date_parameter_documented=False, key_required=True, actual_service_called=False)


def run():
    cfg = read_yaml(CONFIG)
    if cfg["catalog_years"] != [2023, 2024, 2025] or cfg["scenarios"] != SCENARIOS:
        raise ValueError("공개 시점 감사 범위·시나리오 변경")
    for start, end in cfg["periods"].values():
        if pd.Timestamp(start) >= pd.Timestamp(end) or (pd.Timestamp(end) - pd.Timedelta(hours=1)).year >= cfg["locked_outcome_year"]:
            raise ValueError("잠금 연도를 포함하는 특징 가용성 평가")
    refs = freeze_references(cfg)
    source_files = ["overnight-forecast-sources.json", "overnight-confirmation-sources.json"]
    sources = {}
    for name in source_files:
        for entry in json.loads((CASE / name).read_text())["files"]:
            if entry["kind"] == "road_speed":
                if entry["month"] in sources:
                    raise ValueError("기존 수집 목록의 중복 월")
                sources[entry["month"]] = entry
    monthly = pd.concat([parse_catalog(json.loads(verify_ref(refs[f"topis_speed_catalog_{year}"]).read_text())["rows"],
        year, sources, cfg["timezone_assumption"]) for year in cfg["catalog_years"]], ignore_index=True)
    monthly = monthly.set_index("month", drop=False)
    guide = " ".join(html.unescape(re.sub(r"<[^>]+>", " ",
        verify_ref(refs["topis_speed_method_release"]).read_text(encoding="utf-8"))).split())
    if "도로별 일자별 통행속도" not in guide or "익월 10일" not in guide:
        raise ValueError("공식 월별 제공 일정 문구를 확인할 수 없습니다")
    specification = api_fields(verify_ref(refs["seoul_road_realtime_api_spec"]))
    base = read_yaml("overnight_forecast_config.yaml")
    if cfg["origin_relative_lags_hours"] != base["availability"]["recent_road_assumption"]["origin_relative_lags_hours"]:
        raise ValueError("기존 최근 속도 지연값과 감사 범위 불일치")
    lag_rows, state_rows, stages, freshness = [], [], [], []
    for scenario in cfg["scenarios"]:
        releases = monthly[scenario]
        state_ready = {}
        for stage in ["train", "tuning", "calibration", "decision"]:
            start, end = base["splits"][stage]
            months = pd.period_range(start[:7], end[:7], freq="M").astype(str)
            state_ready[stage] = releases.loc[months].max()
            stages.append(dict(scenario=scenario, stage=stage, target_start=start, target_end=end,
                source_months=len(months), latest_required_file_at=state_ready[stage]))
        final_ready = max(state_ready.values())
        for period, (start, end) in cfg["periods"].items():
            targets = pd.date_range(start, end, inclusive="left", freq="h", tz=cfg["timezone_assumption"])
            for horizon in cfg["horizons"]:
                origins = targets - pd.Timedelta(hours=horizon - 1)
                ready = origins >= final_ready
                state_rows.append(dict(scenario=scenario, period=period, horizon=horizon, origins=len(origins),
                    final_model_state_not_before=final_ready, available_origins=int(ready.sum()),
                    unavailable_origins=int((~ready).sum()), fraction_available=float(ready.mean()),
                    first_available_origin=origins[ready][0] if ready.any() else None))
                for anchor, lags in [("origin", cfg["origin_relative_lags_hours"]), ("target", cfg["target_relative_lags_hours"])]:
                    for lag in lags:
                        details = feature_availability(targets, horizon, lag, anchor, releases)
                        lag_rows.append(dict(scenario=scenario, period=period, horizon=horizon, anchor=anchor,
                            lag_hours=lag, origins=len(details), available_origins=int(details.available.sum()),
                            unavailable_origins=int((~details.available).sum()), fraction_available=float(details.available.mean())))
                latest = []
                for origin in origins:
                    eligible = releases[releases.le(origin)].index
                    if not len(eligible):
                        raise ValueError("공개된 과거 파일이 없는 발행 시점")
                    end_of_latest = (pd.Period(max(eligible), freq="M") + 1).to_timestamp().tz_localize(cfg["timezone_assumption"])
                    latest.append((origin - end_of_latest).total_seconds() / 86400)
                freshness.append(dict(scenario=scenario, period=period, horizon=horizon, origins=len(origins),
                    newest_month_end_age_days_min=float(np.min(latest)), newest_month_end_age_days_median=float(np.median(latest)),
                    newest_month_end_age_days_max=float(np.max(latest))))
    tables = {"monthly_catalog.csv": monthly.reset_index(drop=True), "feature_availability.csv": pd.DataFrame(lag_rows),
              "model_stage_availability.csv": pd.DataFrame(stages), "model_state_availability.csv": pd.DataFrame(state_rows),
              "newest_archive_age.csv": pd.DataFrame(freshness)}
    for name, table in tables.items():
        table.to_csv(OUT / name, index=False, lineterminator="\n")
    write_json(OUT / "audit.json", dict(completed_at=utcnow(), config_sha256=sha256(CASE / CONFIG),
        code_sha256=sha256(__file__), references_sha256=sha256(REFERENCES),
        inputs={name: sha256(CASE / name) for name in [*source_files, "overnight_forecast_config.yaml", "gangnam/deepening_definitions.py"]},
        matched_catalog_files=len(monthly), api_specification=specification,
        outputs={name: sha256(OUT / name) for name in tables}, interpretation=[
          "current catalog timestamps are proxies, not proof of historical publication vintages or user access",
          "timezone is assumed Asia/Seoul because catalog timestamps have no explicit zone",
          "guide day10 start and day11 start bracket unspecified time of day; actual dates can differ",
          "current-version scenario uses maximum created/updated timestamp, not a complete revision history",
          "conservative scenario takes maximum of next-month day11 and current-version proxy",
          "counts use one clock per horizon, not three duplicated links; no road outcome values read",
          "same API origin system does not prove equivalence between real-time samples and archived hourly aggregates",
          "no public service call, account creation, historical archive request, or 2026 outcome access"] ))
    print(f"월별 파일 {len(monthly)}개 대응·특징 가용성 {len(lag_rows)}개·모형 상태 {len(state_rows)}개 시나리오 감사", flush=True)
