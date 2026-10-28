"""작은 합성 시험 패널에서 저장 모델 예측부터 구간별 평가·해시 기록까지 확인한다."""

import importlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"))


def test_frozen_prediction_evaluation_keeps_model_and_omits_missing_target(tmp_path, monkeypatch):
    joblib = pytest.importorskip("joblib")
    pytest.importorskip("sklearn")
    pytest.importorskip("pyarrow")
    module = importlib.import_module("gangnam.overnight_forecast_evaluate")
    models = importlib.import_module("gangnam.overnight_forecast_models")
    base, out = tmp_path / "data", tmp_path / "results"
    base.mkdir()
    out.mkdir()
    cfg = {"primary_links": ["A", "B", "C"]}
    monkeypatch.setattr(module, "CASE", tmp_path)
    monkeypatch.setattr(module, "BASE", base)
    monkeypatch.setattr(module, "OUT", out)
    monkeypatch.setattr(module, "read_yaml", lambda _: cfg)
    monkeypatch.setattr(module, "allowed_months", lambda *_: ["2025-05"])
    (tmp_path / "overnight_forecast_config.yaml").write_text("synthetic_fixture: true\n")
    parts = []
    for link in cfg["primary_links"]:
        dates = pd.date_range("2025-05-01", periods=24 * 15, freq="h", tz="Asia/Seoul")
        label = (dates.hour >= 17) & (dates.hour <= 19)
        parts.append(pd.DataFrame({"link_id": link, "target_start": dates, "origin": dates,
            "hour": dates.hour, "weekday": dates.dayofweek, "speed_kmh": np.where(label, 8., 20.),
            "label_10": label.astype(int), "split": "test"}))
    frame = pd.concat(parts, ignore_index=True)
    model = models.fit_seasonal(frame, "label_10", 20)
    model_path = base / "model.joblib"
    joblib.dump(model, model_path)
    checksum = module.sha256(model_path)
    frame.loc[0, "speed_kmh"] = np.nan
    features = base / "features.parquet"
    frame.to_parquet(features, index=False)
    selected = [{"candidate": "synthetic", "horizon": 1, "feature_set": "calendar_only", "family": "seasonal",
        "parameter": "fixed", "seed": 17, "label": "label_10", "role": "primary_selected",
        "model_path": "data/model.joblib", "model_sha256": checksum,
        "calibrator": {"intercept": 0., "slope": 1.}, "decision": {"threshold": .5}}]
    (out / "selected_models_development.json").write_text(json.dumps(selected))
    (out / "selection_manifest.json").write_text("{}")
    audit = {"protocol_sha256": module.sha256(tmp_path / "overnight_forecast_config.yaml"), "bus_features_available": True,
             "outputs": [{"horizon": 1, "path": "data/features.parquet", "sha256": module.sha256(features)}]}
    (out / "feature_audit_test.json").write_text(json.dumps(audit))
    module.evaluate()
    result = pd.read_csv(out / "test_metrics.csv")
    primary = result[result.slice.eq("primary_all_hours")].iloc[0]
    assert primary["rows"] == len(frame) - 1
    assert primary.average_precision == 1.
    assert set(result.slice) >= {"primary_evening_17_19", "link_A", "month_2025-05", "all_selected_links_secondary"}
    assert module.sha256(model_path) == checksum
    summary = json.loads((out / "test_evaluation_audit.json").read_text())
    assert summary["models_evaluated"] == 1
    assert summary["predictions"][0]["rows"] == len(frame) - 1
