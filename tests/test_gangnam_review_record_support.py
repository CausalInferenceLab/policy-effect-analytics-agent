# test_gangnam_review_record_support.py - 남행 기록 지원 표의 분모 정의와 고정 노선 겹침 검사를 확인한다.
import csv
import importlib
import sys
from pathlib import Path

import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
mod = importlib.import_module("review_record_support")
HEADER = ["cohort", "band", "group", "route", "period", "policy_group", "expected_cells", "source_date_absent", "positive"]


def write_case(tmp_path, rows, routes):
    (tmp_path / "results/overnight/bus").mkdir(parents=True, exist_ok=True)
    with (tmp_path / mod.SOURCE).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(HEADER)
        writer.writerows(rows)
    (tmp_path / mod.ROUTES).write_text("expected_common_routes: " + str(routes).replace("'", '"') + "\n", encoding="utf-8")


def row(route, period, policy, expected, absent, positive, group="central_south"):
    return ["common_pre_source_days", "evening", group, route, period, policy, expected, absent, positive]


def test_denominator_excludes_missing_source_dates_and_other_groups(tmp_path):
    keep = [f"r{i}" for i in range(14)]
    rows = [row("p1", "pre2024", "curb", 10, 2, 4), row("p1", "post2024", "curb", 10, 0, 2),
            row("p1", "pre2024", "curb", 99, 0, 99, group="curb_south")]
    for route in keep:
        rows += [row(route, "pre2024", "other_or_unclassified", 10, 1, 9), row(route, "post2024", "other_or_unclassified", 10, 0, 10)]
    write_case(tmp_path, rows, keep)
    result = {(r["group"], r["period"]): r for r in mod.derive(tmp_path)}
    assert result["policy_candidate", "pre2024"]["positive_fraction_source_dates"] == pytest.approx(4 / 8)
    assert result["policy_candidate", "pre2024"]["positive_fraction_all_cells"] == pytest.approx(4 / 10)
    assert result["retained_14", "pre2024"]["policy_candidate_routes"] == 0
    assert result["retained_14", "post2024"]["routes"] == 14


def test_overlap_with_policy_group_is_counted_and_empty_group_is_rejected(tmp_path):
    keep = [f"r{i}" for i in range(14)]
    rows = [row("r0", "pre2024", "dongtan", 10, 0, 5), row("r0", "post2024", "dongtan", 10, 0, 5)]
    write_case(tmp_path, rows, keep)
    with pytest.raises(ValueError, match="빈 집단"):
        mod.derive(tmp_path)
    rows += [row("x", "pre2024", "other_or_unclassified", 10, 0, 10), row("x", "post2024", "other_or_unclassified", 10, 0, 10)]
    write_case(tmp_path, rows, keep)
    assert {r["group"]: r["policy_candidate_routes"] for r in mod.derive(tmp_path)}["retained_14"] == 1
