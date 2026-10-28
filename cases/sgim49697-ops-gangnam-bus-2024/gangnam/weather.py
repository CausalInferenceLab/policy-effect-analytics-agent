"""공식 ASOS 서울 108 일별 파일과 정의 근거를 검증해 비우천 민감도에 제공한다."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .common import sha256, utcnow, write_json


def normalize_weather(path, evidence_path, output):
    path, output = Path(path), Path(output)
    evidence = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
    if not evidence.get("verified") or not evidence.get("source") or evidence["raw_sha256"] != sha256(path):
        raise ValueError("기상 원본의 근거·해시 확인이 필요합니다")
    if evidence.get("unit") != "mm" or evidence.get("blank_precipitation") not in {"zero", "missing"}:
        raise ValueError("강수량 단위·빈칸의 공식 정의가 필요합니다")
    try:
        raw = pd.read_csv(path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        raw = pd.read_csv(path, encoding="cp949")
    if set(pd.to_numeric(raw["지점"], errors="raise")) != {108}:
        raise ValueError("서울 ASOS 108번 지점만 허용합니다")
    value = pd.to_numeric(raw["일강수량(mm)"], errors="raise")
    if evidence["blank_precipitation"] == "zero":
        value = value.fillna(0)
    frame = pd.DataFrame({"date": pd.to_datetime(raw["일시"], errors="raise").dt.strftime("%Y-%m-%d"),
                          "precipitation_mm": value})
    validate_weather(frame)
    output.parent.mkdir(parents=True, exist_ok=True)
    frame.sort_values("date").to_csv(output, index=False)
    write_json(output.with_suffix(".source.json"), {**evidence, "sha256": sha256(output), "normalized_at": utcnow()})


def validate_weather(frame):
    pd.to_datetime(frame.date, format="%Y-%m-%d", errors="raise")
    if frame.date.duplicated().any() or not np.isfinite(frame.precipitation_mm).all() or (frame.precipitation_mm < 0).any():
        raise ValueError("기상 날짜 중복·결측·음수를 먼저 해결하세요")


def load_verified_weather(path):
    path = Path(path)
    evidence = json.loads(path.with_suffix(".source.json").read_text(encoding="utf-8"))
    if not evidence.get("verified") or not evidence.get("source") or evidence["sha256"] != sha256(path):
        raise ValueError("기상 정규화 파일의 근거·해시 불일치")
    frame = pd.read_csv(path, dtype={"date": str})
    validate_weather(frame)
    return frame
