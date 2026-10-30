"""고정 14개/폐선 제외 13개 노선의 양방향 공동 관측 지수를 재계산한다."""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from _shared import checked, config, load_json, new_run, reference, verify_inputs, write_json


def clean_duplicates(frame, keys):
    """같은 값의 중복만 제거하고, 값이 다른 중복 키는 전체를 격리한다."""
    if frame[keys].isna().any().any():
        raise ValueError("결측 결합 키")
    exact = int(frame.duplicated().sum())
    unique = frame.drop_duplicates()
    conflicts = unique.duplicated(keys, keep=False)
    return unique.loc[~conflicts].copy(), {
        "identical_removed": exact,
        "conflicting_rows_quarantined": int(conflicts.sum()),
        "conflicting_keys": len(unique.loc[conflicts, keys].drop_duplicates()),
    }


def joint_directions(rows, routes, hours, dates):
    """두 방향의 모든 시간 중 하나라도 없으면 양쪽 노선·날짜를 같이 제외한다."""
    if rows.duplicated(["date", "route", "segment", "hour"]).any():
        raise ValueError("양방향 공동 관측 키 중복")
    if not routes or not dates or not hours or len(set(hours)) != len(hours):
        raise ValueError("양방향 후보 격자가 비었거나 시간이 중복됩니다")
    if not set(rows.segment).issubset({"south", "north"}):
        raise ValueError("양방향 이외 구간")
    grid = pd.MultiIndex.from_product([dates, routes], names=["date", "route"])
    columns = pd.MultiIndex.from_product([["south", "north"], hours], names=["segment", "hour"])
    matrix = rows.pivot(index=["date", "route"], columns=["segment", "hour"], values="value")
    matrix = matrix.reindex(index=grid, columns=columns)
    matrix = matrix.where(np.isfinite(matrix) & matrix.gt(0))
    joint = matrix.notna().all(axis=1)
    return matrix.where(joint, axis=0), joint


def daily_paired(normalized, expected_routes, dates, report_hours, minimum):
    """사후 누락 노선도 고정 분모에 남기며 두 방향에 동일한 노선·날짜를 적용한다."""
    rows = []
    for segment in ["south", "north"]:
        values = normalized[segment][report_hours].mean(axis=1)
        grouped = values.groupby(level="date").agg(["mean", "count"]).reindex(dates)
        coverage = (
            grouped["count"].fillna(0) / expected_routes
            if expected_routes
            else pd.Series(0.0, index=dates)
        )
        rows.append(
            pd.DataFrame(
                {
                    "date": dates,
                    "segment": segment,
                    "index": grouped["mean"].where(coverage.ge(minimum)).to_numpy(),
                    "coverage": coverage.to_numpy(),
                    "unit_coverage": coverage.to_numpy(),
                }
            )
        )
    result = pd.concat(rows, ignore_index=True)
    shared = result.pivot(index="date", columns="segment", values="coverage")
    if not shared.south.equals(shared.north):
        raise ValueError("양방향의 공동 표본 분모가 다릅니다")
    return result


def paired_gap(daily, before, after, draws, seed):
    """동일 달력 주를 양쪽에 함께 재표집해 방향별 변화율 차이의 기술적 범위를 구한다."""
    wide = daily.pivot(index="date", columns="segment", values="index")[["south", "north"]].dropna()
    parts = [wide.loc[wide.index.isin(days)] for days in [before, after]]
    counts = {"before_days": len(parts[0]), "after_days": len(parts[1])}
    if any(
        part.empty or not np.isfinite(part).all().all() or part.le(0).any().any() for part in parts
    ):
        return {
            **counts,
            "gap_percentage_points": np.nan,
            "week_bootstrap_low": np.nan,
            "week_bootstrap_high": np.nan,
        }
    rng = np.random.default_rng(seed)
    samples = []
    for label, part in zip(["before", "after"], parts, strict=True):
        week = pd.to_datetime(part.index).to_period("W-SUN")
        grouped = part.groupby(week)
        sums, sizes = grouped.sum().to_numpy(), grouped.size().to_numpy()
        counts[label + "_weeks"] = len(sizes)
        selected = rng.integers(0, len(sizes), size=(draws, len(sizes)))
        samples.append(sums[selected].sum(axis=1) / sizes[selected].sum(axis=1)[:, None])
    change = 100 * (parts[1].mean().to_numpy() / parts[0].mean().to_numpy() - 1)
    sample_change = 100 * (samples[1] / samples[0] - 1)
    low, high = np.quantile(sample_change[:, 1] - sample_change[:, 0], [0.025, 0.975])
    return {
        **counts,
        "gap_percentage_points": change[1] - change[0],
        "week_bootstrap_low": float(low),
        "week_bootstrap_high": float(high),
    }


def select_routes(matrix, joint, reference, minimum):
    """사전 공동 관측으로만 노선을 선택하고 각 시간의 사전 평균으로 기준화한다."""
    support = pd.DataFrame(index=matrix.index.get_level_values("route").unique())
    for name, dates in reference.items():
        if not dates:
            raise ValueError("공동 시간의 사전 선택 분모가 비었습니다")
        sample = joint[joint.index.get_level_values("date").isin(dates)]
        support[f"{name}_coverage"] = sample.groupby(level="route").mean()
    support["eligible"] = support.ge(minimum).all(axis=1)
    values = matrix[matrix.index.get_level_values("route").isin(support.index[support.eligible])]
    before = values[values.index.get_level_values("date").isin(reference["pre2024"])]
    baseline = before.groupby(level="route").mean()
    if baseline.isna().any().any() or baseline.le(0).any().any():
        raise ValueError("공동 시간 사전 기준값 오류")
    normalized = values / baseline.reindex(values.index.get_level_values("route")).to_numpy() * 100
    return support.reset_index(), baseline, normalized


def week_means(frame, draws, rng):
    """관측 날짜를 달력 주로 묶어 주 전체를 재표집한다."""
    d = frame.dropna(subset=["index"]).copy()
    if d.empty:
        return None
    d["week"] = pd.to_datetime(d.date).dt.to_period("W-SUN").astype(str)
    weeks = d.groupby("week")["index"].agg(["sum", "count"])
    if len(weeks) < 2:
        return None
    multiplicity = rng.multinomial(len(weeks), np.full(len(weeks), 1 / len(weeks)), size=draws)
    return (multiplicity @ weeks["sum"].to_numpy()) / (multiplicity @ weeks["count"].to_numpy())


def compare(daily, before, after, cfg):
    a, b = daily[daily.date.isin(before)], daily[daily.date.isin(after)]
    av, bv = a["index"].dropna(), b["index"].dropna()
    ac, bc = a.coverage.mean(), b.coverage.mean()
    change = 100 * (bv.mean() / av.mean() - 1) if len(av) and len(bv) and av.mean() else None
    rng = np.random.default_rng(cfg["bootstrap"]["seed"])
    boot_a = week_means(a, cfg["bootstrap"]["draws"], rng)
    boot_b = week_means(b, cfg["bootstrap"]["draws"], rng)
    interval = (
        [None, None]
        if boot_a is None or boot_b is None
        else np.quantile(100 * (boot_b / boot_a - 1), [0.025, 0.975]).tolist()
    )
    passed = (
        len(av) >= cfg["minimum_days"]
        and len(bv) >= cfg["minimum_days"]
        and pd.notna(ac)
        and pd.notna(bc)
        and abs(ac - bc) <= cfg["maximum_coverage_gap"]
    )
    return {
        "before_mean": float(av.mean()) if len(av) else None,
        "after_mean": float(bv.mean()) if len(bv) else None,
        "change_pct": float(change) if change is not None else None,
        "before_days": len(av),
        "after_days": len(bv),
        "before_coverage": float(ac) if pd.notna(ac) else None,
        "after_coverage": float(bc) if pd.notna(bc) else None,
        "quality_pass": bool(passed),
        "week_bootstrap_low": interval[0],
        "week_bootstrap_high": interval[1],
    }


def describe_comparison(daily, before, after, cfg, interval=False):
    a, b = daily[daily.date.isin(before)], daily[daily.date.isin(after)]
    av, bv = a["index"].dropna(), b["index"].dropna()
    ac, bc = a.coverage.mean(), b.coverage.mean()
    au, bu = a.unit_coverage.mean(), b.unit_coverage.mean()
    passed = (
        len(av) >= cfg["minimum_days"]
        and len(bv) >= cfg["minimum_days"]
        and pd.notna(ac)
        and pd.notna(bc)
        and abs(ac - bc) <= cfg["maximum_coverage_gap"]
        and pd.notna(au)
        and pd.notna(bu)
        and abs(au - bu) <= cfg["maximum_coverage_gap"]
    )
    result = {
        "before_mean": av.mean(),
        "after_mean": bv.mean(),
        "change_pct": 100 * (bv.mean() / av.mean() - 1)
        if len(av) and len(bv) and av.mean() > 0
        else np.nan,
        "before_days": len(av),
        "after_days": len(bv),
        "before_expected_days": len(before),
        "after_expected_days": len(after),
        "before_coverage": ac,
        "after_coverage": bc,
        "before_unit_coverage": au,
        "after_unit_coverage": bu,
        "quality_pass": bool(passed),
        "week_bootstrap_low": np.nan,
        "week_bootstrap_high": np.nan,
    }
    if interval and len(av) and len(bv):
        interval_result = compare(daily, before, after, cfg)
        result.update(
            {k: interval_result[k] for k in ("week_bootstrap_low", "week_bootstrap_high")}
        )
    return result


def accepted_dates_only(daily, reference):
    """날짜 집합을 원래 유효 일자로 제한하며 관측률 분모는 현재 고정 노선을 유지한다."""
    keys = ["date", "segment"]
    if daily.duplicated(keys).any() or reference.duplicated(keys).any():
        raise ValueError("일별 비교 키 중복")
    mask = reference[keys].assign(reference_accepted=reference["index"].notna())
    result = daily.merge(mask, on=keys, how="left", validate="one_to_one")
    if result.reference_accepted.isna().any():
        raise ValueError("원래 분석에 없는 날짜")
    result["index"] = result["index"].where(result.reference_accepted)
    return result.drop(columns="reference_accepted")


def load_panel(inputs, cfg):
    """월 경계 중복과 재방문을 격리한 뒤 고정된 두 정류장 구간만 긴 표로 만든다."""
    entries = [entry for entry in inputs["files"] if entry["kind"] == "bus_time"]
    expected = pd.period_range("2023-01", "2025-08", freq="M").astype(str).tolist()
    if sorted(e["month"] for e in entries) != expected:
        raise ValueError("버스 32개월 입력의 누락·중복")
    legs = pd.DataFrame(cfg["segments"])[["segment", "stop", "arrival"]]
    stops = sorted(set(legs.stop) | set(legs.arrival))
    parts, audits = [], {}
    for scope in ["multiyear", "forecast_bus_test"]:
        pieces = [
            pd.read_parquet(
                checked(e), filters=[("route", "in", cfg["routes"]), ("stop", "in", stops)]
            )
            for e in entries
            if scope in e["scopes"]
        ]
        wide, audit = clean_duplicates(
            pd.concat(pieces, ignore_index=True),
            ["date", "route", "stop", "sequence", "arrival", "arrival_sequence"],
        )
        wide["date"] = pd.to_datetime(wide.date, format="%Y%m%d", errors="raise").dt.strftime(
            "%Y-%m-%d"
        )
        eligible = wide.date.between(*cfg["record_window"]) & (
            wide.date.ge("2025-05-01") == (scope == "forecast_bus_test")
        )
        parts.append(wide[eligible])
        audits[scope] = audit
    wide = pd.concat(parts, ignore_index=True).merge(
        legs, on=["stop", "arrival"], validate="many_to_one"
    )
    repeated = wide.duplicated(["date", "route", "stop", "arrival"], keep=False)
    audits["excluded_revisit_rows"] = int(repeated.sum())
    panel = wide[~repeated].melt(
        id_vars=["date", "route", "segment"],
        value_vars=[f"h{h:02}" for h in cfg["hours"]],
        var_name="hour",
        value_name="raw_value",
    )
    panel["hour"] = panel.hour.str[1:].astype(int)
    panel["value"] = panel.raw_value.where(panel.raw_value.gt(0))
    if np.isinf(panel.value).any():
        raise ValueError("유한하지 않은 버스 값")
    return panel, audits


def analyze(panel, cfg):
    calendar = cfg["calendar"]
    dates = sorted(set().union(*calendar.values(), *cfg["selection_reference_dates"].values()))
    matrix, joint = joint_directions(panel, cfg["routes"], cfg["hours"], dates)
    support, baseline, normalized = select_routes(
        matrix, joint, cfg["selection_reference_dates"], cfg["minimum_pre_joint_coverage"]
    )
    if set(support.loc[support.eligible, "route"]) != set(cfg["routes"]):
        raise ValueError("원래 고정한 14개 노선의 사전 관측 조건이 달라졌습니다")
    original = daily_paired(
        normalized, len(cfg["routes"]), dates, cfg["report_hours"], cfg["minimum_coverage"]
    )
    kept = normalized[normalized.index.get_level_values("route") != cfg["retired_route"]["id"]]
    native = daily_paired(
        kept, len(cfg["routes"]) - 1, dates, cfg["report_hours"], cfg["minimum_coverage"]
    )
    variants = dict(
        original_14_reproduction=original,
        retained_13_same_accepted_dates=accepted_dates_only(native, original),
        retained_13_original_coverage_rule=native,
    )
    if list(variants) != cfg["cohorts"]:
        raise ValueError("고정한 구성 민감도 조건과 다릅니다")
    comparisons, gaps, dailies = [], [], []
    for label, daily in variants.items():
        number = len(cfg["routes"]) - (not label.startswith("original"))
        dailies.append(daily.assign(cohort=label))
        for name, (before, after) in cfg["comparisons"].items():
            passed = []
            for segment in ["south", "north"]:
                result = describe_comparison(
                    daily[daily.segment.eq(segment)],
                    calendar[before],
                    calendar[after],
                    cfg,
                    interval=True,
                )
                result["quality_pass"] = bool(
                    result["quality_pass"]
                    and number >= cfg["minimum_routes"]
                    and min(result["before_coverage"], result["after_coverage"])
                    >= cfg["minimum_coverage"]
                )
                passed.append(result["quality_pass"])
                comparisons.append(
                    dict(
                        cohort=label,
                        comparison=name,
                        segment=segment,
                        selected_routes=number,
                        **result,
                    )
                )
            gaps.append(
                dict(
                    cohort=label,
                    comparison=name,
                    selected_routes=number,
                    quality_pass=all(passed),
                    **paired_gap(daily, calendar[before], calendar[after], **cfg["bootstrap"]),
                )
            )
    baseline.columns = [f"{segment}_h{hour:02}" for segment, hour in baseline.columns]
    return dict(
        comparisons=pd.DataFrame(comparisons),
        paired_gaps=pd.DataFrame(gaps),
        daily=pd.concat(dailies, ignore_index=True),
        baseline=baseline.reset_index(),
    )


def run(inputs_path, run_id):
    inputs = verify_inputs(load_json(inputs_path))
    out = new_run(run_id)
    panel, audit = load_panel(inputs, config()["bus"])
    tables = analyze(panel, config()["bus"])
    for name, frame in tables.items():
        frame.to_csv(out / (name + ".csv"), index=False)
    write_json(
        out / "result.json",
        dict(
            input_manifest=reference(inputs_path),
            quality=audit,
            outputs={name: reference(out / (name + ".csv")) for name in tables},
            interpretation="운행시간 기록의 기술 비교. 초·분 및 인과 효과를 의미하지 않음",
        ),
    )
    print(f"버스 {len(tables['comparisons'])}개 조건 재계산 완료: {out}")
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    run(args.inputs, args.run_id)
