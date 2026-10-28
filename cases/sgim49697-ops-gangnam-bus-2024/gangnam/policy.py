"""고정 길이가중 속도지수와 동일 날짜 패널로 정책 전후 변화를 비교한다."""

from __future__ import annotations

import copy
from datetime import timedelta

import numpy as np
import pandas as pd


def workdays(start, end, holidays):
    return pd.DatetimeIndex([d for d in pd.date_range(start, end) if d.weekday() < 5
                             and str(d.date()) not in holidays])


def daily_index(hourly, spec, hours, holidays):
    ids = [x["id"] for x in spec["links"]]
    lengths = pd.Series({x["id"]: float(x["length"]) for x in spec["links"]})
    if not ids or len(ids) != len(set(ids)) or (lengths <= 0).any():
        raise ValueError("고정 링크와 양의 길이를 확인하세요")
    if hourly.duplicated(["link_id", "interval_start_kst"]).any():
        raise ValueError("링크×시간 중복")
    d = hourly[hourly.link_id.isin(ids)].copy()
    t = pd.to_datetime(d.interval_start_kst)
    d["date"] = t.dt.tz_localize(None).dt.normalize()
    d["hour"] = t.dt.hour
    d = d[d.hour.isin(hours) & (t.dt.weekday < 5) & ~d.date.dt.strftime("%Y-%m-%d").isin(holidays)]
    d.loc[~d.is_valid, "speed_kmh"] = np.nan
    grid = d.pivot(index="date", columns=["link_id", "hour"], values="speed_kmh")
    cols = pd.MultiIndex.from_product([ids, hours], names=["link_id", "hour"])
    grid = grid.reindex(columns=cols)
    weights = np.array([lengths[link] / lengths.sum() / len(hours) for link, _ in cols])
    # numpy sum은 NaN을 유지하므로 일부 관측 누락 시 가중치를 재조정하지 않는다.
    return pd.Series(grid.to_numpy() @ weights, index=grid.index, name="speed_index")


def build_panel(hourly, cfg, holidays):
    pre_days, post_days = [workdays(*cfg[p], holidays) for p in ("pre", "post")]
    if min(len(pre_days), len(post_days)) == 0:
        raise ValueError("전후 평일이 없습니다")
    series, quality = {}, {}
    treated_ids = [k for k, v in cfg["corridors"].items() if v["treated"]]
    if len(treated_ids) != 1:
        raise ValueError("처치 도로는 정확히 하나여야 합니다")
    treated = treated_ids[0]
    for name, spec in cfg["corridors"].items():
        if spec["status"] != "verified" or not spec.get("source") or not spec.get("direction"):
            quality[name] = {"eligible": False, "reason": "historical_evidence_pending"}
            continue
        s = daily_index(hourly, spec, cfg["hours"], holidays)
        cov_pre = float(s.reindex(pre_days).notna().mean())
        cov_post = float(s.reindex(post_days).notna().mean())
        eligible = (min(cov_pre, cov_post) >= cfg["minimum_coverage"]
                    and abs(cov_pre - cov_post) <= cfg["maximum_coverage_gap"] + 1e-12)
        quality[name] = {"eligible": eligible, "pre_coverage": cov_pre, "post_coverage": cov_post}
        if eligible:
            series[name] = s.reindex(pre_days.union(post_days))
    if treated not in series:
        raise ValueError("처치 구간의 역사적 근거 또는 전후 관측률이 기준에 미달합니다")
    wide = pd.DataFrame(series)
    # 날짜 집합까지 동일하게 맞춘다. 도로별 관측 개수만 같은 패널을 허용하지 않는다.
    balanced = wide.dropna(how="any")
    counts = {"pre": int(balanced.index.isin(pre_days).sum()),
              "post": int(balanced.index.isin(post_days).sum())}
    comparative = len(series) - 1 >= cfg["minimum_controls"]
    if comparative and min(counts.values()) < cfg["minimum_common_days"]:
        comparative = False
    quality.update({"common_days": counts, "comparative": comparative,
                    "selected_controls": [x for x in series if x != treated]})
    selected = balanced if comparative else wide
    panel = selected.rename_axis("date").reset_index().melt(
        id_vars="date", var_name="corridor_id", value_name="speed_index").dropna()
    panel["treated"] = (panel.corridor_id == treated).astype(int)
    panel["day_idx"] = (panel.date - pd.Timestamp(cfg["origin"])).dt.days
    return panel.sort_values(["corridor_id", "date"]), quality


def balanced_wide(panel):
    if panel.duplicated(["corridor_id", "date"]).any():
        raise ValueError("도로×날짜 중복")
    p = panel.pivot(index="date", columns="corridor_id", values="speed_index").sort_index()
    if p.isna().any().any():
        raise ValueError("도로마다 날짜 집합이 다릅니다")
    return p


def did_point(panel, policy_date):
    """동일 날짜·동시 처치·공변량 없는 균형 패널의 TWFE 계수와 같은 이중차분."""
    p = balanced_wide(panel)
    treated = panel.loc[panel.treated == 1, "corridor_id"].unique()
    controls = [c for c in p if c not in treated]
    if len(treated) != 1 or not controls:
        raise ValueError("처치 1곳과 비교 도로가 필요합니다")
    gap = p[treated[0]] - p[controls].mean(axis=1)
    post = gap.index >= pd.Timestamp(policy_date)
    if post.all() or not post.any():
        raise ValueError("전후 기간이 모두 필요합니다")
    return float(gap[post].mean() - gap[~post].mean()), gap


def diagnostics(panel, cfg):
    point, gap = did_point(panel, cfg["policy_date"])
    relative = (gap.index - pd.Timestamp(cfg["policy_date"])).days // 7
    weekly = gap.groupby(relative).mean()
    reference = weekly.get(-1)
    if reference is None:
        raise ValueError("정책 직전 기준 주(-1)가 없습니다")
    weekly = weekly - reference
    pre = panel[panel.date < pd.Timestamp(cfg["policy_date"])]
    placebo, _ = did_point(pre, cfg["sensitivities"]["placebo_date"])
    loo = {}
    for control in panel.loc[panel.treated == 0, "corridor_id"].unique():
        reduced = panel[panel.corridor_id != control]
        if reduced.corridor_id.nunique() >= 2:
            loo[control] = did_point(reduced, cfg["policy_date"])[0]
    return {"verdict": "not_identified", "did_kmh": point,
            "weekly_gap_relative_to_week_minus_one": {str(k): float(v) for k, v in weekly.items()},
            "placebo_date": cfg["sensitivities"]["placebo_date"], "placebo_kmh": placebo,
            "leave_one_control_out_kmh": loo,
            "note": "1개 처치 도로. 주별 격차는 진단이며 p값·신뢰구간을 인과 결론으로 제공하지 않음"}


def sensitivities(hourly, cfg, holidays, controls, weather=None):
    """주 분석의 비교군을 고정하고 사전 지정한 변경만 적용한다."""
    variants = {}
    announcement = copy.deepcopy(cfg)
    announcement["pre"][1] = str((pd.Timestamp(cfg["sensitivities"]["exclude_announcement"][0]) - timedelta(days=1)).date())
    announcement["minimum_common_days"] = cfg["minimum_sensitivity_days"]
    variants["exclude_announcement"] = announcement
    first_week = copy.deepcopy(cfg)
    first_week["post"][0] = cfg["sensitivities"]["include_first_week_from"]
    variants["include_first_week"] = first_week
    results = {}
    if cfg["extension"]["status"] == "verified":
        extended = copy.deepcopy(cfg)
        treated = next(v for v in extended["corridors"].values() if v["treated"])
        treated["links"].append(extended["extension"]["link"])
        variants["extend_yangjae"] = extended
    else:
        results["extend_yangjae"] = {"status": "blocked", "reason": "extension_evidence_pending"}
    for name, spec in variants.items():
        spec["corridors"] = {k: v for k, v in spec["corridors"].items() if v["treated"] or k in controls}
        try:
            p, q = build_panel(hourly, spec, holidays)
            if not q["comparative"] or set(q["selected_controls"]) != set(controls):
                raise ValueError("고정 비교군·공통 날짜 기준 미달")
            results[name] = {"status": "ok", "did_kmh": did_point(p, spec["policy_date"])[0]}
        except ValueError as e:
            results[name] = {"status": "blocked", "reason": str(e)}
    if weather is None:
        results["dry_days"] = {"status": "blocked", "reason": "verified_weather_missing"}
    else:
        p, _ = build_panel(hourly, cfg, holidays)
        required = set(p.date.dt.strftime("%Y-%m-%d"))
        if not required <= set(weather.date):
            raise ValueError("일별 기상 결측을 비우천으로 처리할 수 없습니다")
        dry = set(weather.loc[weather.precipitation_mm == 0, "date"])
        p = p[p.date.dt.strftime("%Y-%m-%d").isin(dry)]
        try:
            counts = p.groupby(p.date >= pd.Timestamp(cfg["policy_date"])).date.nunique()
            if len(counts) != 2 or counts.min() < cfg["minimum_sensitivity_days"]:
                raise ValueError("비우천일 민감도의 전후 최소 날짜 수 미달")
            results["dry_days"] = {"status": "ok", "did_kmh": did_point(p, cfg["policy_date"])[0],
                                   "days": p.date.nunique()}
        except ValueError as e:
            results["dry_days"] = {"status": "blocked", "reason": str(e)}
    return results
