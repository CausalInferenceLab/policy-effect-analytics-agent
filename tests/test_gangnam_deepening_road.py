"""공간 탐색이 사후 셀 선택·중복·잠금 연도 접근으로 바뀌지 않는지 검사한다."""

import importlib
import sys
from pathlib import Path

import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
pd = pytest.importorskip("pandas")
pytest.importorskip("pyarrow")
mod = importlib.import_module("gangnam.deepening_road")


def test_missing_original_cell_is_not_filled_or_selected_away():
    cfg = dict(original_scope="road_stable_subset", groups={"bridge": {"links": ["1", "2"]}}, bands={"evening": [17]})
    frame = pd.DataFrame([dict(scope="road_stable_subset", band="evening", group="old", link_id="1", hour=17, length=100)])
    with pytest.raises(ValueError, match="누락"):
        mod.select_fixed_cells(frame, cfg)
    frame = pd.concat([frame, frame.assign(link_id="2")], ignore_index=True)
    selected = mod.select_fixed_cells(frame, cfg)
    assert selected.link_id.tolist() == ["1", "2"]
    assert selected.original_group.tolist() == ["old", "old"]
    with pytest.raises(ValueError, match="중복"):
        mod.select_fixed_cells(pd.concat([frame, frame.iloc[:1]]), cfg)


def test_locked_month_rejected_before_loading_road_values():
    cfg = dict(months=["2026-01"], locked_year=2026, groups={"g": {"links": ["1"]}}, periods={})
    with pytest.raises(ValueError, match="잠금"):
        mod.validate_scope(cfg)
