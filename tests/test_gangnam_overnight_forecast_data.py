"""새 예측의 시험 자료 접근 조건과 불완전 도로 캐시 재사용 방지를 검사한다."""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))

from gangnam import overnight_forecast_data as data  # noqa: E402
from gangnam.common import sha256  # noqa: E402


def config():
    return {"locked_year": 2026, "splits": {"train": ["2023-01-01", "2024-12-31"],
            "decision": ["2025-04-01", "2025-04-30"], "test": ["2025-05-01", "2025-08-31"]}}


def test_test_scope_is_blocked_before_selection_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "OUT", tmp_path)
    with pytest.raises(ValueError, match="동결 전"):
        data.allowed_months("test", config())


def test_development_scope_never_includes_test_or_locked_year():
    months = data.allowed_months("development", config())
    assert len(months) == 28 and months[-1] == "2025-04"
    cfg = config()
    cfg["splits"]["decision"][1] = "2026-01-31"
    with pytest.raises(ValueError, match="잠금 연도"):
        data.allowed_months("development", cfg)


def test_frozen_model_hash_and_protocol_are_checked_before_test(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "CASE", tmp_path)
    monkeypatch.setattr(data, "OUT", tmp_path)
    protocol = tmp_path / "overnight_forecast_config.yaml"
    protocol.write_text("frozen")
    model = tmp_path / "model.bin"
    model.write_bytes(b"unit-test-model")
    manifest = {"selection_complete": True, "protocol_sha256": sha256(protocol),
                "frozen_files": [{"path": "model.bin", "sha256": sha256(model)}]}
    (tmp_path / "selection_manifest.json").write_text(json.dumps(manifest))
    assert data.allowed_months("test", config()) == ["2025-05", "2025-06", "2025-07", "2025-08"]
    model.write_bytes(b"changed")
    with pytest.raises(ValueError, match="해시"):
        data.allowed_months("test", config())


def test_old_cache_missing_requested_roads_is_reparsed(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "CASE", tmp_path)
    monkeypatch.setattr(data, "BASE", tmp_path / "new")
    monkeypatch.setattr(data, "verify", lambda entry: tmp_path / "raw.xlsx")
    monkeypatch.setattr(data, "read_yaml", lambda name: {"candidate_roads": ["A"]})
    old = tmp_path / "data/processed/2023-01.parquet"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"old-cache-with-road-A-only")
    # 범위가 다르면 이 메타데이터를 읽어 재사용하려 해서는 안 된다.
    old.with_suffix(".json").write_text("invalid-if-read")
    meta = tmp_path / "data/metadata/2023-01.json"
    meta.parent.mkdir(parents=True)
    meta.write_text("{}")
    calls = []
    def parse(path, month, roads, rules):
        calls.append((month, roads))
        return pd.DataFrame({"link_id": ["a", "b"], "speed_kmh": [10., 20.]}), {"month": month, "metadata": []}
    monkeypatch.setattr(data, "parse_month", parse)
    result = data.prepare_entry(({"month": "2023-01", "sha256": "source"}, ["A", "B"], {}))
    assert calls == [("2023-01", ["A", "B"])]
    assert result["rows"] == 2
    assert result["reused"] is None
