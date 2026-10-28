"""추출된 환승·출도착 기록의 공개 키 중복과 수치 분모를 검사해 활용 한계를 기록한다."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, sha256, utcnow, write_json
from .overnight_transfer_probe import OUT


def transfer_quality(frame):
    keys = list(frame)[:4]
    if keys != ["기준_날짜", "하차_정류장/역사_ID", "승차_정류장/역사_ID", "시간대"]:
        raise ValueError("환승 식별 열이 다릅니다")
    hour = pd.to_numeric(frame["시간대"], errors="raise")
    if not hour.between(0, 23).all() or hour.mod(1).ne(0).any():
        raise ValueError("환승 시간대가 0~23의 정수가 아닙니다")
    values = frame.iloc[:, 4:].apply(pd.to_numeric, errors="raise")
    if values.isna().any().any() or not np.isfinite(values.to_numpy()).all() or values.lt(0).any().any():
        raise ValueError("환승 수치에 미정의 공란·비유한 값·음수가 있습니다")
    ambiguous = frame.duplicated(keys, keep=False)
    size = frame.groupby(keys).size()
    counts, averages = values.iloc[:, :6], values.iloc[:, 6:]
    remainder = counts.iloc[:, 0] - counts.iloc[:, 1:].sum(axis=1)
    estimated_mean = (counts.iloc[:, 1:].to_numpy() * averages.iloc[:, 1:].to_numpy()).sum(axis=1) / counts.iloc[:, 0].replace(0, np.nan)
    difference = (averages.iloc[:, 0] - estimated_mean).where(remainder.eq(0) & counts.iloc[:, 0].gt(0))
    audit = {"rows": len(frame), "distinct_public_keys": len(size),
             "exact_duplicate_extra_rows": int(frame.duplicated().sum()), "ambiguous_rows": int(ambiguous.sum()),
             "ambiguous_row_fraction": float(ambiguous.mean()), "ambiguous_keys": int(size.gt(1).sum()),
             "unique_key_rows": int((~ambiguous).sum()), "max_public_key_multiplicity": int(size.max()),
             "category_count_sum_mismatch_rows": int(remainder.ne(0).sum()),
             "category_count_remainder_range": [float(remainder.min()), float(remainder.max())],
             "category_mean_consistency_eligible_rows": int(difference.notna().sum()),
             "category_mean_difference_abs_over_one_rows": int(difference.abs().gt(1).sum()),
             "time_unit_status": "not_verified", "hour_attribution_status": "not_verified",
             "decision": "공개 키의 행 구분·시간 단위를 확인하기 전 승객 수 합산과 환승시간 전후 효과 분석 보류"}
    daily = frame[keys].assign(ambiguous=ambiguous, category_mismatch=remainder.ne(0)).groupby(keys[0]).agg(
        rows=("ambiguous", "size"), ambiguous_rows=("ambiguous", "sum"), category_mismatch_rows=("category_mismatch", "sum")).reset_index()
    daily["ambiguous_fraction"] = daily.ambiguous_rows / daily.rows
    multiplicity = size.value_counts().sort_index().rename_axis("multiplicity").rename("public_keys").reset_index()
    return audit, daily, multiplicity


def od_quality(frame):
    keys = list(frame)[:3]
    if keys != ["기준_날짜", "승차_정류장/역사_ID", "하차_정류장/역사_ID"]:
        raise ValueError("출도착 식별 열이 다릅니다")
    if frame.duplicated(keys).any():
        raise ValueError("출도착 공개 키가 중복됩니다")
    values = frame.iloc[:, 3:].apply(pd.to_numeric, errors="raise")
    if np.isinf(values.to_numpy()).any() or values.lt(0).any().any():
        raise ValueError("출도착 수치에 비유한 값 또는 음수가 있습니다")
    daily_total, hours = values.iloc[:, 0], values.iloc[:, 1:]
    known_sum = hours.sum(axis=1, min_count=1)
    mismatch = daily_total.notna() & known_sum.notna() & daily_total.ne(known_sum)
    audit = {"rows": len(frame), "duplicate_keys": 0, "daily_total_missing_rows": int(daily_total.isna().sum()),
             "hourly_cells": int(hours.size), "hourly_known_cells": int(hours.notna().sum().sum()),
             "hourly_blank_cells": int(hours.isna().sum().sum()), "all_hours_known_rows": int(hours.notna().all(axis=1).sum()),
             "known_hour_sum_daily_total_mismatch_rows": int(mismatch.sum()),
             "decision": "일별 명시적 합계의 관측 기록 분석 후보. 공란 시각을 0으로 대체하지 않고 수단·노선·미수록 범위 확인 필요."}
    daily = frame[keys].assign(daily_total=daily_total, known_hours=hours.notna().sum(axis=1), mismatch=mismatch).groupby(keys[0]).agg(
        rows=("daily_total", "size"), daily_total_known_rows=("daily_total", "count"),
        known_hour_cells=("known_hours", "sum"), sum_mismatch_rows=("mismatch", "sum")).reset_index()
    return audit, daily


def run():
    source = json.loads((OUT / "probe_audit.json").read_text())
    results = []
    for entry in source["files"]:
        path = CASE / entry["path"]
        if sha256(path) != entry["sha256"]:
            raise ValueError("보조 추출 파일 해시 불일치")
        d = pd.read_csv(path, dtype=str)
        if entry["kind"] == "transfer_probe":
            audit, daily, multiplicity = transfer_quality(d)
            multiplicity.to_csv(OUT / "transfer_key_multiplicity.csv", index=False)
        else:
            audit, daily = od_quality(d)
        daily.to_csv(OUT / f"{entry['kind']}_selected_quality_by_day.csv", index=False)
        results.append({"kind": entry["kind"], "month": entry["month"], "source_sha256": entry["raw_sha256"], **audit})
    write_json(OUT / "selected_quality_audit.json", {"completed_at": utcnow(), "code_sha256": sha256(Path(__file__)),
                                                    "probe_audit_sha256": sha256(OUT / "probe_audit.json"), "files": results})
