"""생성된 지연값 전체와 월 공개 경계의 프로필을 원래 가공 속도에서 다시 대조한다."""

import json

import numpy as np
import pandas as pd

from .common import CASE, sha256, utcnow, write_json
from .deepening_archive_data import MANIFEST, OUT, checked, read_matrix, verify


def run():
    cfg, manifest = verify()
    audit = json.loads((OUT / "feature_audit.json").read_text())
    if audit["input_manifest_sha256"] != sha256(MANIFEST):
        raise ValueError("특징 검증의 입력 명세 변경")
    matrix, _, _ = read_matrix(cfg, manifest)
    dates = pd.read_csv(CASE / cfg["release_table"]).set_index("month")[cfg["release_scenario"]]
    releases = pd.to_datetime(dates, utc=True).dt.tz_convert(cfg["timezone"])
    summaries, boundaries = [], []
    for ref in audit["outputs"]:
        horizon = ref["horizon"]
        frame = pd.read_parquet(checked(ref))
        total, availability_checks, finite, max_difference = 0, 0, 0, 0.
        for link, group in frame.groupby("link_id", sort=True):
            group = group.sort_values("target_start")
            targets = pd.DatetimeIndex(group.target_start)
            origins = pd.DatetimeIndex(group.origin)
            if not targets.equals(matrix.index):
                raise ValueError("지연 특징 검증의 시간 격자 불일치")
            for lag in cfg["target_relative_lags_hours"]:
                times = targets - pd.Timedelta(hours=lag)
                published = pd.to_datetime(pd.Series(times.strftime("%Y-%m")).map(releases), utc=True).dt.tz_convert(cfg["timezone"])
                allowed = published.notna().to_numpy() & (pd.DatetimeIndex(published) <= origins)
                actual_allowed = group[f"archive_available_{lag}"].to_numpy()
                np.testing.assert_array_equal(actual_allowed, allowed.astype(int))
                expected = matrix[link].reindex(times).to_numpy(dtype=np.float32)
                expected[~allowed] = np.nan
                actual = group[f"archive_lag_{lag}"].to_numpy()
                np.testing.assert_allclose(actual, expected, rtol=0, atol=0, equal_nan=True)
                known = np.isfinite(expected)
                max_difference = max(max_difference, float(np.abs(actual[known] - expected[known]).max(initial=0)))
                total += len(expected)
                availability_checks += len(allowed)
                finite += int(known.sum())
        indexed = frame.set_index(["link_id", "target_start"])
        origins = sorted({stamp.ceil("h") + pd.Timedelta(hours=offset) for stamp in releases for offset in [-1, 0]})
        for origin in origins:
            target = origin + pd.Timedelta(hours=horizon - 1)
            if target not in matrix.index:
                continue
            eligible = sorted(releases[releases.le(origin)].index)
            for window in cfg["profile_last_published_months"]:
                months = eligible[-window:]
                dates_match = (matrix.index.strftime("%Y-%m").isin(months)
                               & (matrix.index.dayofweek == target.dayofweek) & (matrix.index.hour == target.hour))
                for link in cfg["primary_links"]:
                    values = matrix.loc[dates_match, link].dropna()
                    expected = {"mean": values.mean(), "std": values.std(ddof=1), "q10": values.quantile(.1),
                                "q50": values.quantile(.5), "q90": values.quantile(.9),
                                "count": len(values) if months else np.nan, "expected": int(dates_match.sum()) if months else np.nan}
                    actual = indexed.loc[(link, target)]
                    differences = []
                    for name, value in expected.items():
                        measured = actual[f"archive_profile_{window}_{name}"]
                        np.testing.assert_allclose(measured, np.float32(value), rtol=0, atol=1e-6, equal_nan=True)
                        if np.isfinite(value):
                            differences.append(float(abs(measured - np.float32(value))))
                    if actual[f"archive_profile_{window}_months"] != len(months):
                        raise ValueError("독립 검증의 공개 월 수 불일치")
                    boundaries.append(dict(horizon=horizon, origin=origin, target_start=target, link_id=link,
                        window=window, source_months=";".join(months), observed_source_hours=len(values),
                        checked_statistics=len(expected), maximum_absolute_float32_difference=max(differences, default=0.), mismatch=False))
        summaries.append(dict(horizon=horizon, feature_rows=len(frame), lag_value_cells=total,
            lag_availability_cells=availability_checks, finite_lag_cells=finite, maximum_absolute_lag_difference=max_difference))
        print(f"월별 입력 대조 h{horizon}: 지연값·가용 여부 각각 {total:,}칸 일치", flush=True)
    pd.DataFrame(boundaries).to_csv(OUT / "publication_boundary_checks.csv", index=False, lineterminator="\n")
    write_json(OUT / "feature_validation.json", dict(completed_at=utcnow(), code_sha256=sha256(__file__),
        feature_audit_sha256=sha256(OUT / "feature_audit.json"), input_manifest_sha256=sha256(MANIFEST),
        horizons=summaries, boundary_profiles=len(boundaries), boundary_statistics=sum(r["checked_statistics"] for r in boundaries),
        output_sha256=sha256(OUT / "publication_boundary_checks.csv"), mismatches=0,
        scope="기존 가공 속도에서 특징 연산을 별도 재계산; 원본 XLSX 전체의 독립 재추출은 아님"))
