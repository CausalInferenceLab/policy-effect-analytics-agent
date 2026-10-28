"""사전 승객 기록이 있는 고정 하위 표본에서 동일 날짜의 셀 평균과 가중 평균을 비교한다."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, write_json
from .directional import period_dates
from .overnight_bus import read_panel
from .overnight_passengers import weighted_daily
from .overnight_sensitivity import aggregate_daily, describe_comparison, normalized

OUT = CASE / "results/overnight/passengers"


def match_valid_dates(equal, weighted):
    """둘 중 하나라도 관측 기준에 미달한 날짜는 양쪽 평균에서 함께 제외한다."""
    keys = ["group", "date"]
    if equal.duplicated(keys).any() or weighted.duplicated(keys).any():
        raise ValueError("가중 비교 날짜가 중복됩니다")
    valid = equal[keys + ["index"]].merge(weighted[keys + ["index"]], on=keys, how="outer",
        validate="one_to_one", suffixes=("_equal", "_weighted"))
    valid["paired_valid"] = valid.index_equal.notna() & valid.index_weighted.notna()
    result = []
    for frame in [equal, weighted]:
        d = frame.merge(valid[keys + ["paired_valid"]], on=keys, how="left", validate="one_to_one")
        d.loc[~d.paired_valid, "index"] = np.nan
        result.append(d)
    return result


def weight_concentration(weights):
    values = weights.weight.dropna().to_numpy()
    if np.any(~np.isfinite(values)) or np.any(values < 0):
        raise ValueError("사전 고정 가중치가 유한한 비음수 값이 아닙니다")
    total = values.sum()
    ordered = np.sort(values)[::-1]
    return {"total_pre_weight": float(total), "positive_weight_cells": int((values > 0).sum()),
        "zero_weight_cells": int((values == 0).sum()),
        "effective_weight_cells": float(total ** 2 / (values @ values)) if total else np.nan,
        "largest_cell_weight_fraction": float(ordered[0] / total) if total else np.nan,
        "top10_cell_weight_fraction": float(ordered[:10].sum() / total) if total else np.nan}


def run():
    cfg = read_yaml("overnight_covered_passengers_config.yaml")
    base = read_yaml("directional_config.yaml")
    base.update(minimum_days=cfg["minimum_days"], maximum_coverage_gap=cfg["maximum_coverage_gap"])
    weights_path = CASE / cfg["selection_file"]
    prior = json.loads((OUT / "passenger_audit.json").read_text())
    if sha256(weights_path) != prior["outputs"][weights_path.name]:
        raise ValueError("기존 사전 승객 가중치 해시가 다릅니다")
    weights = pd.read_csv(weights_path, dtype={c: str for c in ["route", "stop", "arrival"]})
    panel, audit = read_panel()
    panel = panel[panel.date.str.startswith("2024")]
    periods = period_dates(base, set(audit["source_available_dates"]))
    dates = sorted(panel.date.unique())
    rows, daily_tables, eligibility = [], [], []
    for (band, subset, group), full in weights.groupby(["band", "subset", "group"]):
        if band not in cfg["bands"] or subset not in cfg["subsets"]:
            continue
        chosen = full[full.weight.notna()].copy()
        tags = {"band": band, "subset": subset, "group": group, "full_preselected_cells": len(full),
            "covered_cells": len(chosen), "covered_fraction": len(chosen) / len(full),
            "covered_routes": chosen.route.nunique(), **weight_concentration(chosen)}
        eligibility.append(tags)
        if chosen.empty or chosen.weight.sum() <= 0:
            for comparison in cfg["comparisons"]:
                for method in ["equal_cells_same_covered", "fixed_pre_passengers_same_covered"]:
                    rows.append({**tags, "comparison": comparison, "method": method, "status": "no_eligible_pre_weight", "quality_pass": False})
            continue
        data = normalized(panel, chosen)
        equal = aggregate_daily(data, chosen, dates, "equal_cells", cfg["daily_cell_coverage"])
        weighted = weighted_daily(data, chosen, dates, cfg["daily_weight_coverage"])
        equal, weighted = match_valid_dates(equal, weighted)
        for method, daily in [("equal_cells_same_covered", equal), ("fixed_pre_passengers_same_covered", weighted)]:
            daily_tables.append(daily.assign(band=band, subset=subset, method=method))
            for comparison in cfg["comparisons"]:
                after = periods["post2024" if comparison == "summer2024" else "autumn2024"]
                result = describe_comparison(daily, periods["pre2024"], after, base, interval=True)
                rows.append({**tags, "comparison": comparison, "method": method, "status": "evaluated_restricted_population", **result})
    outputs = {"covered_comparisons.csv": pd.DataFrame(rows), "covered_daily.csv": pd.concat(daily_tables, ignore_index=True),
               "covered_eligibility.csv": pd.DataFrame(eligibility)}
    for name, frame in outputs.items():
        frame.to_csv(OUT / name, index=False)
    write_json(OUT / "covered_audit.json", {"code_sha256": sha256(Path(__file__)),
        "configuration_sha256": sha256(CASE / "overnight_covered_passengers_config.yaml"),
        "selection_sha256": sha256(weights_path), "panel_sha256": audit["panel_sha256"],
        "outputs": {name: sha256(OUT / name) for name in outputs}, "comparisons": len(rows),
        "selection": "기존 사전 고정 값만으로 추가 선택하며 사후 관측량을 선택에 사용하지 않음.",
        "scope": cfg["interpretation"], "paired_dates": cfg["paired_dates"]})
    print(f"사전 승객 관측 하위 집단: {len(rows)}개 비교", flush=True)
