"""개발 선택이 완료된 모델·보정·임계값·특징 정의의 해시를 시험 원본 접근 전에 동결한다."""

from __future__ import annotations

import json
import subprocess

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .overnight_forecast_data import OUT, allowed_months


def freeze():
    cfg = read_yaml("overnight_forecast_config.yaml")
    path = OUT / "selection_manifest.json"
    if path.exists():
        allowed_months("test", cfg)
        print("기존 시험 전 동결 해시 확인 완료")
        return
    progress = json.loads((OUT / "training_progress.json").read_text())
    if progress["status"] != "selection_ready_for_review_and_freeze":
        raise ValueError("개발 후보 선택이 완료되지 않았습니다")
    selected = json.loads((OUT / "selected_models_development.json").read_text())
    if len(selected) != progress["selected_count"] or len({x["candidate"] for x in selected}) != len(selected):
        raise ValueError("선택 모델 개수·고유성 불일치")
    paths = [CASE / n for n in ["overnight_forecast_config.yaml", "requirements-overnight.txt",
             "results/overnight/forecast/selected_models_development.json", "results/overnight/forecast/selected_links.json",
             "results/overnight/forecast/feature_audit_development.json", "results/overnight/forecast/environment_development.json",
             "results/overnight/forecast/bus_selected_cells_bus_time.csv", "results/overnight/forecast/bus_selected_cells_bus_trips.csv"]]
    modules = ["overnight_forecast_data", "overnight_forecast_features", "overnight_forecast_bus", "overnight_forecast_test_bus",
               "overnight_forecast_models", "overnight_forecast_train", "overnight_forecast_metrics", "overnight_forecast_evaluate",
               "overnight_forecast_freeze", "overnight_bus_data", "overnight_bus_extract"]
    paths.extend(CASE / "gangnam" / (name + ".py") for name in modules)
    for horizon in cfg["horizons"]:
        primary = [x for x in selected if x["horizon"] == horizon and x["role"] == "primary_selected"]
        if len(primary) != 1:
            raise ValueError("예측 간격별 주 후보가 유일하지 않습니다")
    for item in selected:
        model = CASE / item["model_path"]
        if not model.resolve().is_relative_to((CASE / "data/overnight/forecast/models").resolve()) or sha256(model) != item["model_sha256"]:
            raise ValueError("동결 모델 경로·해시 불일치")
        if item["family"] != "quantile" and (not item.get("calibrator") or not item.get("decision")):
            raise ValueError("분류 모델의 보정기·경보 기준이 없습니다")
        paths.append(model)
    audit = json.loads((OUT / "feature_audit_development.json").read_text())
    for output in audit["outputs"]:
        if sha256(CASE / output["path"]) != output["sha256"]:
            raise ValueError("개발 특징 해시 불일치")
    # 커밋된 코드와 동결 대상 코드가 같아야 새 시험 접근을 시작한다.
    relative = [str(p.relative_to(CASE)) for p in paths if p.suffix == ".py"]
    dirty = subprocess.check_output(["git", "-C", str(CASE), "status", "--porcelain", "--", *relative], text=True)
    if dirty.strip():
        raise ValueError("동결 대상 코드를 검증·커밋한 뒤 시험 접근을 시작하세요")
    commit = subprocess.check_output(["git", "-C", str(CASE), "rev-parse", "HEAD"], text=True).strip()
    manifest = {"created_at": utcnow(), "selection_complete": True, "protocol_sha256": sha256(CASE / "overnight_forecast_config.yaml"),
        "code_commit": commit, "training_candidates": len(progress["candidates"]), "selected_models": len(selected),
        "primary_candidates": [x["candidate"] for x in selected if x["role"] == "primary_selected"],
        "test_period": cfg["splits"]["test"], "locked_year": cfg["locked_year"],
        "frozen_files": [{"path": str(p.relative_to(CASE)), "sha256": sha256(p)} for p in sorted(set(paths))],
        "note": "시험 원본 수집 전에 생성. 시험 결과에 맞춘 모델·특징·보정기·경보 기준 변경 금지."}
    write_json(path, manifest)
    allowed_months("test", cfg)
    print(f"시험 전 동결 완료: 모델 {len(selected)}개, 파일 {len(set(paths))}개", flush=True)
