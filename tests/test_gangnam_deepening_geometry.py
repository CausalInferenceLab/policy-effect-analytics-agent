"""좌표 반올림과 키 부재를 실제 위치 변경·불변으로 덮어쓰지 않는다."""

import importlib
import sys
from pathlib import Path

import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
pd = pytest.importorskip("pandas")
pytest.importorskip("openpyxl")
mod = importlib.import_module("gangnam.deepening_geometry")


def test_rounding_is_distinct_from_exact_and_missing_vertex():
    before = pd.DataFrame([dict(link_id="1", sequence=1, x=100.4, y=200.6),
                           dict(link_id="1", sequence=2, x=101.2, y=201.8)])
    after = pd.DataFrame([dict(link_id="1", sequence=1, x=100., y=201.),
                          dict(link_id="1", sequence=3, x=101., y=202.)])
    paired = mod.compare_vertices(before, after).set_index("sequence")
    assert len(paired) == 3
    assert not paired.loc[1, "exact_coordinates"] and paired.loc[1, "rounding_compatible"]
    assert paired.loc[2, "record_state"] == "left_only"
    assert paired.loc[3, "record_state"] == "right_only"
    assert not paired.loc[[2, 3], "rounding_compatible"].any()


def test_unknown_mapping_order_is_preserved_without_inventing_order():
    data = pd.DataFrame([dict(link_id="1", sequence=None, standard_link_id="2"),
                         dict(link_id="1", sequence=None, standard_link_id="3")])
    result = mod.validate_mapping_sequence(data)
    assert len(result) == 2 and result.sequence.isna().all()
    repeated = mod.validate_mapping_sequence(data.assign(sequence=1))
    assert repeated.order_state.eq("repeated_known_order").all()
    with pytest.raises(ValueError, match="양의 정수"):
        mod.validate_mapping_sequence(data.assign(sequence=0))
