"""독립 잔차화에서 시간 기울기의 혼합과 계수 부족을 검사한다."""

import importlib
import sys
from pathlib import Path

import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
pytest.importorskip("pandas")
np = pytest.importorskip("numpy")
mod = importlib.import_module("gangnam.deepening_transition_check")


def test_residualization_separates_correlated_time_and_level():
    time = np.arange(100, dtype=float)
    post = (time >= 40).astype(float)
    nuisance = np.column_stack([np.ones(100), time])
    target = 100 + 3 * time - 20 * post
    assert mod.residualized_coefficient(target, post, nuisance) == pytest.approx(-20)
    with pytest.raises(ValueError, match="중복"):
        mod.residualized_coefficient(target, time, nuisance)
    with pytest.raises(ValueError, match="계수 부족"):
        mod.residualized_coefficient(target, post, np.column_stack([nuisance, time]))
