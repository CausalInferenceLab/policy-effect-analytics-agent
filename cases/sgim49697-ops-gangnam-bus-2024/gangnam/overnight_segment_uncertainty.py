"""기존 14개 구간·5개 비교에 공통 주 재표집을 적용해 기술적 동시 변동 범위를 계산한다."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .overnight_persistence import periods

OUT = CASE / "results/overnight/segment_uncertainty"


def joint_period_samples(daily, calendar, groups, draws, seed, minimum_weeks):
    """한 기간의 주 가중치를 모든 구간에 공유하고 결측을 평균 분모에서 분리한다."""
    if daily.duplicated(["date", "group"]).any() or draws < 2 or len(set(groups)) != len(groups):
        raise ValueError("주 재표집의 중복 키·반복 수·구간 목록 오류")
    known = daily["index"].dropna()
    if not np.isfinite(known).all() or known.le(0).any():
        raise ValueError("로그 평균비는 유한한 양수 관측만 사용합니다")
    rng = np.random.default_rng(seed)
    actual, samples, audit = {}, {}, []
    for period, dates in calendar.items():
        if not dates or len(set(dates)) != len(dates):
            raise ValueError("빈 날짜 창 또는 중복 예정 날짜")
        data = daily[daily.date.isin(dates)].pivot(index="date", columns="group", values="index").reindex(index=dates, columns=groups)
        weeks = pd.to_datetime(pd.Index(dates)).to_period("W-SUN").astype(str)
        codes, names = pd.factorize(weeks, sort=True)
        if len(names) < minimum_weeks:
            raise ValueError("기간의 달력 주 수가 고정 하한보다 적습니다")
        values = data.to_numpy(dtype=float)
        finite = np.isfinite(values)
        if not finite.any(axis=0).all():
            raise ValueError("기간 안에 유효 관측이 전혀 없는 구간")
        sums = np.zeros((len(names), len(groups)))
        counts = np.zeros_like(sums)
        np.add.at(sums, codes, np.where(finite, values, 0.))
        np.add.at(counts, codes, finite.astype(float))
        weights = rng.multinomial(len(names), np.full(len(names), 1 / len(names)), size=draws)
        numerator, denominator = weights @ sums, weights @ counts
        samples[period] = np.divide(numerator, denominator, out=np.full_like(numerator, np.nan), where=denominator > 0)
        actual[period] = sums.sum(axis=0) / counts.sum(axis=0)
        for i, group in enumerate(groups):
            audit.append({"period": period, "segment": group, "expected_days": len(dates),
                          "valid_days": int(counts[:, i].sum()), "calendar_weeks": len(names),
                          "weeks_with_observation": int((counts[:, i] > 0).sum()), "mean": actual[period][i]})
    return actual, samples, pd.DataFrame(audit)


def simultaneous_band(points, samples, quantile):
    """공통 유효 추출에서 중심화·표준화한 최대 절댓값을 하나의 범위 계수로 사용한다."""
    points, samples = np.asarray(points, dtype=float), np.asarray(samples, dtype=float)
    if points.ndim != 1 or not len(points) or samples.ndim != 2 or samples.shape[1] != len(points) or not 0 < quantile < 1:
        raise ValueError("동시 범위의 차원 또는 분위수 오류")
    valid = np.isfinite(samples).all(axis=1)
    used = samples[valid]
    if not np.isfinite(points).all() or len(used) < 2:
        raise ValueError("동시 범위에 필요한 유효 추출이 부족합니다")
    spread = used.std(axis=0, ddof=1)
    delta = used - points
    scale = np.finfo(float).eps * 64 * (1 + np.abs(points))
    constant = np.max(np.abs(delta), axis=0) <= scale
    if np.any((spread <= 0) & ~constant):
        raise ValueError("관측 중심과 다른 상수 재표집 값의 표준화를 정의할 수 없습니다")
    standardized = np.divide(delta, spread, out=np.zeros_like(delta), where=~constant)
    maximum = np.max(np.abs(standardized), axis=1)
    critical = float(np.quantile(maximum, quantile))
    spread[constant] = 0.
    return {"lower_log": points - critical * spread, "upper_log": points + critical * spread,
            "standard_error_log": spread, "critical": critical, "maximum_statistics": maximum,
            "valid_draws": int(valid.sum()), "invalid_draws": int((~valid).sum())}


def run():
    cfg = read_yaml("overnight_segment_uncertainty_config.yaml")
    if cfg["locked_year"] != 2026 or cfg["band"] != "evening":
        raise ValueError("구간 동시 범위의 잠금 연도·시간대 설정 오류")
    audit_path, daily_path, comparison_path = [CASE / cfg[k] for k in ["source_audit", "daily_source", "comparison_source"]]
    audit = json.loads(audit_path.read_text())
    for path in [daily_path, comparison_path]:
        if sha256(path) != audit["outputs"][path.name]:
            raise ValueError("원래 구간 집계 결과의 해시 변경")
    daily, original = pd.read_csv(daily_path), pd.read_csv(comparison_path, dtype={"from_ars": str, "to_ars": str})
    daily, original = daily[daily.band.eq(cfg["band"])], original[original.band.eq(cfg["band"])].copy()
    groups = sorted(daily.group.unique())
    calendar_cfg = read_yaml(cfg["calendar_from"])
    calendar, definitions = periods(calendar_cfg), audit["configuration"]["comparisons"]
    if len(groups) != 14 or len(definitions) != 5 or len(original) != 70 or not original.quality_pass.all():
        raise ValueError("고정한 14개 구간·5개 비교의 범위 또는 원래 관측 조건이 다릅니다")
    actual, samples, support = joint_period_samples(daily, calendar, groups, cfg["bootstrap"]["draws"],
                                                   cfg["bootstrap"]["seed"], cfg["minimum_weeks"])
    points, simulated, keys = [], [], []
    for comparison, (before, after) in definitions.items():
        points.extend(np.log(actual[after] / actual[before]))
        simulated.append(np.log(samples[after] / samples[before]))
        keys.extend({"segment": group, "comparison": comparison} for group in groups)
    points, simulated = np.asarray(points), np.column_stack(simulated)
    result = simultaneous_band(points, simulated, cfg["bootstrap"]["quantile"])
    table = pd.DataFrame(keys).merge(original, on=["segment", "comparison"], validate="one_to_one")
    reconstructed = 100 * np.expm1(points)
    if not np.allclose(reconstructed, table.change_pct, rtol=1e-10, atol=1e-10):
        raise ValueError("같은 원래 일별 지수로 기간 비교 평균을 재현하지 못했습니다")
    table["simultaneous_low_pct"] = 100 * np.expm1(result["lower_log"])
    table["simultaneous_high_pct"] = 100 * np.expm1(result["upper_log"])
    table["bootstrap_standard_error_log"] = result["standard_error_log"]
    table["simultaneous_excludes_zero"] = table.simultaneous_low_pct.gt(0) | table.simultaneous_high_pct.lt(0)
    table["original_pointwise_excludes_zero"] = table.week_bootstrap_low.gt(0) | table.week_bootstrap_high.lt(0)
    OUT.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUT / "comparisons.csv", index=False)
    support.to_csv(OUT / "period_support.csv", index=False)
    probabilities = [.5, .9, .95, .99, 1.]
    pd.DataFrame({"quantile": probabilities, "maximum_standardized_error": np.quantile(result["maximum_statistics"], probabilities)}).to_csv(
        OUT / "bootstrap_summary.csv", index=False)
    paths = [audit_path, daily_path, comparison_path, CASE / cfg["calendar_from"], CASE / "overnight_segment_uncertainty_config.yaml",
             CASE / "gangnam/overnight_persistence.py"]
    write_json(OUT / "audit.json", {"completed_at": utcnow(), "configuration": cfg, "code_sha256": sha256(Path(__file__)),
        "inputs": {str(p.relative_to(CASE)): sha256(p) for p in paths}, "family_size": len(points), "critical": result["critical"],
        "valid_draws": result["valid_draws"], "invalid_draws": result["invalid_draws"],
        "original_pointwise_excludes_zero": int(table.original_pointwise_excludes_zero.sum()),
        "simultaneous_excludes_zero": int(table.simultaneous_excludes_zero.sum()),
        "outputs": {p.name: sha256(p) for p in OUT.glob("*.csv")}, "interpretation": cfg["interpretation"]})
    print(f"구간 동시 변동 범위: {len(points)}개 비교, 공통 계수 {result['critical']:.4f}, 유효 추출 {result['valid_draws']}", flush=True)
