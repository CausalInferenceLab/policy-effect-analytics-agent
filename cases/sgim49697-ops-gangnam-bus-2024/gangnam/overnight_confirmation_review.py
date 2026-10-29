"""가을·겨울 저장 예측의 휴일 표식·구간 이탈 방향·단일 주 의존을 사후 점검한다."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .overnight_baseline_methods import interval_losses
from .overnight_forecast_diagnostics import align_predictions

OUT = CASE / "results/overnight/confirmation_review"


def week_labels(times):
    if str(times.dt.tz) != "Asia/Seoul":
        raise ValueError("사후 진단은 서울 시간대 예측을 사용합니다")
    return times.dt.tz_localize(None).dt.to_period("W-SUN").dt.start_time.dt.strftime("%Y-%m-%d")


def calendar_groups(times, holiday_dates):
    holiday = times.dt.date.isin(holiday_dates)
    return np.select([holiday, times.dt.dayofweek.ge(5)], ["public_holiday", "nonholiday_weekend"], default="nonholiday_weekday")


def leave_week_out(left, right):
    joined = align_predictions(left.assign(label=0), right.assign(label=0))
    weeks = week_labels(joined.target_start)
    if weeks.nunique() < 2:
        raise ValueError("한 주 제외 진단에는 두 주 이상이 필요합니다")
    loss = []
    for suffix in ["left", "right"]:
        frame = pd.DataFrame({key: joined[key + "_" + suffix] for key in ["speed_kmh", "q10", "q50", "q90"]})
        loss.append(interval_losses(frame)["interval_score_alpha_0.2"])
    delta = pd.Series(loss[0] - loss[1], index=joined.index)
    rows = []
    for omitted in ["none", *sorted(weeks.unique())]:
        keep = weeks.ne(omitted)
        rows.append({"omitted_week": omitted, "remaining_rows": int(keep.sum()), "remaining_weeks": weeks[keep].nunique(),
                     "difference": float(delta[keep].mean())})
    weekly = pd.DataFrame({"week": weeks, "difference": delta}).groupby("week").agg(
        rows=("difference", "size"), mean_difference=("difference", "mean")).reset_index()
    return pd.DataFrame(rows), weekly


def run():
    import holidays

    cfg = read_yaml("overnight_confirmation_review_config.yaml")
    audit_path = CASE / cfg["source_audit"]
    audit = json.loads(audit_path.read_text())
    if not audit["comparison_quality_pass"] or audit["configuration"]["period"] != cfg["period"]:
        raise ValueError("사후 진단의 추가 검증 범위·품질 오류")
    holiday_dates = set(holidays.KR(years=[2025]))
    inputs = {cfg["source_audit"]: sha256(audit_path), "overnight_confirmation_review_config.yaml": sha256(CASE / "overnight_confirmation_review_config.yaml"),
              str(Path(__file__).relative_to(CASE)): sha256(Path(__file__))}
    cache, grouped, weekly_rows, omitted_rows, used_holidays = {}, [], [], [], set()
    for ref in audit["predictions"]:
        if ref["task"] != "quantile" or ref["name"] not in cfg["models"]:
            continue
        path = (CASE / ref["path"]).resolve()
        if not path.is_relative_to((CASE / "data/overnight/confirmation").resolve()) or sha256(path) != ref["sha256"]:
            raise ValueError("사후 진단 예측 경로·해시 오류")
        inputs[ref["path"]] = ref["sha256"]
        frame = pd.read_parquet(path)
        if not frame.target_start.dt.strftime("%Y-%m-%d").between(*cfg["period"]).all():
            raise ValueError("사후 진단 예측의 기간 오류")
        frame["calendar_group"] = calendar_groups(frame.target_start, holiday_dates)
        frame["week"] = week_labels(frame.target_start)
        used_holidays.update(frame.loc[frame.calendar_group.eq("public_holiday"), "target_start"].dt.strftime("%Y-%m-%d"))
        cache[(ref["horizon"], ref["name"])] = frame
        for name in cfg["subgroups"]:
            part = frame[frame.calendar_group.eq(name)]
            weeks = part.week.nunique()
            row = {"horizon": ref["horizon"], "model": ref["name"], "calendar_group": name, "rows": len(part),
                   "days": part.target_start.dt.date.nunique(), "weeks": weeks,
                   "comparison_quality_pass": len(part) >= cfg["minimum_rows"] and weeks >= cfg["minimum_calendar_weeks"]}
            if len(part):
                row.update({key: float(values.mean()) for key, values in interval_losses(part).items()})
                row.update(below_q10_fraction=float(part.speed_kmh.lt(part.q10).mean()),
                           above_q90_fraction=float(part.speed_kmh.gt(part.q90).mean()),
                           median_bias_kmh=float((part.q50 - part.speed_kmh).mean()))
            grouped.append(row)
    for horizon in cfg["horizons"]:
        for scope in cfg["leave_one_week_out"]["slices"]:
            def part(name, horizon=horizon, scope=scope):
                frame = cache[(horizon, name)]
                return frame[frame.target_start.dt.hour.isin([17, 18, 19])] if scope == "evening_17_19" else frame
            for right in cfg["leave_one_week_out"]["right"]:
                omitted, weeks = leave_week_out(part(cfg["leave_one_week_out"]["left"]), part(right))
                omitted_rows.append(omitted.assign(horizon=horizon, scope=scope, right=right))
                weekly_rows.append(weeks.assign(horizon=horizon, scope=scope, right=right))
    OUT.mkdir(parents=True, exist_ok=True)
    tables = {"calendar_groups": pd.DataFrame(grouped), "leave_one_week_out": pd.concat(omitted_rows, ignore_index=True),
              "weekly_differences": pd.concat(weekly_rows, ignore_index=True)}
    for name, frame in tables.items():
        frame.to_csv(OUT / f"{name}.csv", index=False)
    write_json(OUT / "audit.json", {"completed_at": utcnow(), "configuration": cfg, "inputs": inputs,
        "observed_holiday_dates": sorted(used_holidays), "outputs": {name + ".csv": sha256(OUT / f"{name}.csv") for name in tables},
        "interpretation": "추가 검증 결과를 본 뒤 정한 진단. 단일 주 제외 범위는 신뢰구간이 아니며 모델·예측을 변경하지 않음."})
    print(f"가을·겨울 사후 점검: 집단 {len(grouped)}개, 주 제외 {len(tables['leave_one_week_out'])}개", flush=True)
