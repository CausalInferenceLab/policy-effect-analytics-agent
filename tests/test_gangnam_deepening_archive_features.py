"""미공개 월·미래 값·발행 경계가 월별 예측 입력에 새지 않는지 검사한다."""

import importlib
import sys
from pathlib import Path

import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")
pytest.importorskip("pyarrow")
mod = importlib.import_module("gangnam.deepening_archive_features")


def test_profile_selection_uses_origin_and_handles_out_of_order_publication():
    targets = pd.date_range("2025-05-11", periods=3, freq="h", tz="Asia/Seoul")
    releases = pd.Series({"2025-02": pd.Timestamp("2025-05-12", tz="Asia/Seoul"),
                          "2025-03": pd.Timestamp("2025-04-11", tz="Asia/Seoul"),
                          "2025-04": pd.Timestamp("2025-05-11", tz="Asia/Seoul")})
    clock, choices, _ = mod.publication_clock(targets, 3, releases, [1, 3])
    assert clock.publication_cursor.tolist() == [1, 1, 2]
    assert choices[(1, 3)] == ("2025-03",)
    assert choices[(2, 1)] == ("2025-04",)
    assert choices[(2, 3)] == ("2025-03", "2025-04")


def test_lag_is_masked_until_file_release_even_if_value_is_old():
    source = pd.date_range("2025-01-01", "2025-03-01", freq="h", tz="Asia/Seoul")
    series = pd.Series(12.0, index=source)
    targets = pd.date_range("2025-02-28", periods=2, freq="h", tz="Asia/Seoul")
    releases = pd.Series({"2025-01": pd.Timestamp("2025-02-28 01:00", tz="Asia/Seoul")})
    values, available = mod.lag_values(series, targets, 1, 56 * 24, releases)
    assert available.tolist() == [0, 1]
    assert np.isnan(values[0]) and values[1] == 12


def test_unpublished_future_values_do_not_change_current_profiles():
    index = pd.date_range("2025-01-01", "2025-05-31 23:00", freq="h", tz="Asia/Seoul")
    matrix = pd.DataFrame({"1": np.arange(len(index), dtype=float)}, index=index)
    changed = matrix.copy()
    changed.loc["2025-04-01":, "1"] = -9999
    before = mod.month_profile(matrix, ("2025-02", "2025-03"))
    after = mod.month_profile(changed, ("2025-02", "2025-03"))
    pd.testing.assert_frame_equal(before, after)
    matrix.loc["2025-03-03 00:00", "1"] = np.nan
    profile = mod.month_profile(matrix, ("2025-03",))
    row = profile.loc[("1", 0, 0)]
    assert row["expected"] == 5 and row["count"] == 4


def test_locked_year_or_missing_clock_row_rejected_before_feature_values():
    cfg = dict(timezone="Asia/Seoul", locked_year=2026)
    matrix = pd.DataFrame({"1": [1., 2.]}, index=pd.date_range("2026-01-01", periods=2, freq="h", tz="Asia/Seoul"))
    with pytest.raises(ValueError, match="잠금"):
        mod.build_features(matrix, pd.Series(dtype=float), 1, cfg, set())


def test_complete_feature_builder_preserves_release_boundary_and_ignores_future_values():
    index = pd.date_range("2025-01-01", "2025-03-31 23:00", freq="h", tz="Asia/Seoul")
    matrix = pd.DataFrame({"1": np.where(index.month == 1, 10., 20.)}, index=index)
    releases = pd.Series({"2025-01": pd.Timestamp("2025-02-11", tz="Asia/Seoul"),
                          "2025-02": pd.Timestamp("2025-03-11", tz="Asia/Seoul"),
                          "2025-03": pd.Timestamp("2025-04-11", tz="Asia/Seoul")})
    cfg = dict(timezone="Asia/Seoul", locked_year=2026, profile_last_published_months=[1, 3],
               target_relative_lags_hours=[56 * 24], splits={"test": ["2025-01-01", "2025-03-31"]})
    before, _, _ = mod.build_features(matrix, releases, 3, cfg, set())
    changed = matrix.copy()
    changed.loc["2025-03-01":, "1"] = 99999
    after, _, _ = mod.build_features(changed, releases, 3, cfg, set())
    fields = mod.feature_sets(before)["published_archive"]
    pd.testing.assert_frame_equal(before[fields], after[fields])
    selected = before.set_index("target_start").loc["2025-03-11 00:00":"2025-03-11 02:00"]
    assert selected.archive_profile_1_q50.tolist() == [10., 10., 20.]
    assert not any(name in fields for name in ["speed_kmh", "target_start", "origin", "split", "publication_cursor"])
