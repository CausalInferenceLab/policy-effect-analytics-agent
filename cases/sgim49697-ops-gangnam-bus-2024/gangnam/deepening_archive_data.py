"""기존 동결을 보존하며 월별 파일만 이용하는 후속 예측 입력을 고정한다."""

import json
import shutil
import subprocess

import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json

CONFIG = "deepening_archive_config.yaml"
OUT = CASE / "results/deepening/archive_forecast"
RAW = CASE / "data/deepening/archive_forecast"
MANIFEST = OUT / "input_manifest.json"
EXTRACTIONS = ["results/overnight/forecast/extraction_development.json", "results/overnight/forecast/extraction_test.json",
               "results/overnight/confirmation/feature_audit.json"]


def validate(cfg):
    if cfg["locked_year"] != 2026 or cfg["months"] != ["2023-01", "2025-12"]:
        raise ValueError("월별 예측의 자료 범위·잠금 설정 변경")
    if cfg["horizons"] != [1, 3] or cfg["feature_sets"] != ["calendar_only", "published_archive"]:
        raise ValueError("월별 예측의 고정 비교 후보 변경")
    if cfg["target_relative_lags_hours"] != [1344, 1512, 1680, 1848] or cfg["profile_last_published_months"] != [1, 3]:
        raise ValueError("월별 예측의 지연·프로필 규칙 변경")
    for start, end in cfg["splits"].values():
        if pd.Timestamp(start) > pd.Timestamp(end) or pd.Timestamp(end).year >= cfg["locked_year"]:
            raise ValueError("잠금 연도 또는 잘못된 개발·평가 기간")
    if shutil.disk_usage(CASE).free < cfg["resources"]["minimum_free_disk_gib"] * 1024**3:
        raise ValueError("남은 디스크가 월별 예측 최소 조건보다 작습니다")


def reference(path):
    return dict(path=str(path.relative_to(CASE)), sha256=sha256(path))


def checked(ref):
    path = (CASE / ref["path"]).resolve()
    if not path.is_relative_to(CASE.resolve()) or sha256(path) != ref["sha256"]:
        raise ValueError("월별 예측 입력 경로·해시 불일치")
    return path


def prepare():
    from .overnight_confirmation_data import verify as verify_previous

    cfg = read_yaml(CONFIG)
    validate(cfg)
    verify_previous()
    if MANIFEST.exists():
        verify(committed=False)
        return
    paths = [CONFIG, *EXTRACTIONS, cfg["selected_links"], cfg["release_table"], "results/deepening/availability/audit.json",
             "data_contract.yaml", "overnight_forecast_config.yaml", "gangnam/overnight_forecast_features.py",
             "gangnam/overnight_forecast_models.py", "gangnam/overnight_forecast_metrics.py",
             "gangnam/overnight_baseline_methods.py", "gangnam/overnight_forecast_diagnostics.py"]
    entries = []
    for path in EXTRACTIONS:
        obj = json.loads((CASE / path).read_text())
        items = obj["extractions"] if isinstance(obj, dict) else obj
        entries.extend({key: row[key] for key in ["month", "path", "sha256", "source_sha256", "rows"]} for row in items)
    if sorted(row["month"] for row in entries) != pd.period_range(*cfg["months"], freq="M").astype(str).tolist():
        raise ValueError("기존 가공 자료의 월별 범위·중복 오류")
    release = pd.read_csv(CASE / cfg["release_table"]).set_index("month")
    for entry in entries:
        checked(entry)
        if entry["source_sha256"] != release.loc[entry["month"], "cached_source_sha256"]:
            raise ValueError("공개 시각 목록과 가공 원본 해시 불일치")
    chosen = json.loads((CASE / cfg["selected_links"]).read_text())
    if len(chosen) != 62 or not set(cfg["primary_links"]).issubset(chosen):
        raise ValueError("기존 고정 링크 선택과 다릅니다")
    write_json(MANIFEST, dict(prepared_at=utcnow(), configuration=cfg, inputs={path: sha256(CASE / path) for path in paths},
        extractions=entries, selected_links=len(chosen), planned_fits=len(cfg["feature_sets"]) * len(cfg["horizons"]) * len(cfg["training"]["seeds"]),
        scope="이미 본 2025년을 월별 공개 파일 시나리오로 다시 비교; 독립 시험 아님"))
    print(f"월별 예측 입력 {len(entries)}개월·{len(chosen)}개 링크·8회 학습 규칙 고정", flush=True)


def verify(committed=True):
    cfg = read_yaml(CONFIG)
    validate(cfg)
    record = json.loads(MANIFEST.read_text())
    if record["configuration"] != cfg:
        raise ValueError("월별 예측 고정 설정 변경")
    for path, expected in record["inputs"].items():
        checked(dict(path=path, sha256=expected))
    for entry in record["extractions"]:
        checked(entry)
    if committed:
        path = str(MANIFEST.relative_to(CASE.parents[1]))
        content = subprocess.run(["git", "show", "HEAD:" + path], cwd=CASE, capture_output=True, check=True).stdout
        if content != MANIFEST.read_bytes():
            raise ValueError("월별 예측 입력 규칙을 먼저 커밋해야 합니다")
    return cfg, record


def read_matrix(cfg, manifest):
    from .overnight_forecast_features import mask_changed_metadata

    metadata = []
    for path in EXTRACTIONS:
        source = json.loads((CASE / path).read_text())
        metadata.extend(source["extractions"] if isinstance(source, dict) else source)
    selected = json.loads((CASE / cfg["selected_links"]).read_text())
    frames = []
    for entry in manifest["extractions"]:
        if int(entry["month"][:4]) >= cfg["locked_year"]:
            raise ValueError("잠금 월 값 읽기 금지")
        frame = pd.read_parquet(checked(entry), columns=["link_id", "interval_start_kst", "speed_kmh", "is_valid"])
        if len(frame) != entry["rows"] or not frame.interval_start_kst.dt.strftime("%Y-%m").eq(entry["month"]).all():
            raise ValueError("가공 자료의 월·행 수 불일치")
        if (frame.speed_kmh.notna() & ~frame.is_valid).any():
            raise ValueError("무효 관측에 속도값이 남아 있습니다")
        frames.append(frame[frame.link_id.isin(selected)][["link_id", "interval_start_kst", "speed_kmh"]])
    joined = pd.concat(frames, ignore_index=True)
    if joined.duplicated(["link_id", "interval_start_kst"]).any():
        raise ValueError("월별 예측 원본 키 중복")
    index = pd.date_range("2023-01-01", "2025-12-31 23:00", freq="h", tz=cfg["timezone"])
    matrix = joined.pivot(index="interval_start_kst", columns="link_id", values="speed_kmh").reindex(index)
    matrix, exclusions = mask_changed_metadata(matrix, metadata, selected, read_yaml("overnight_forecast_config.yaml"))
    return matrix, selected, exclusions
