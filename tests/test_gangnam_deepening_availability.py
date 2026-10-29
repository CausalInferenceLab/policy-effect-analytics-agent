"""현재 월별 목록의 날짜와 특징 발행 시계를 혼동하지 않는지 검사한다."""

import importlib
import sys
from pathlib import Path

import pytest

CASE = Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
sys.path.insert(0, str(CASE))
pd = pytest.importorskip("pandas")
mod = importlib.import_module("gangnam.deepening_availability")


def test_release_is_compared_to_origin_including_hour_offset():
    targets = pd.date_range("2025-05-10 00:00", periods=3, freq="h", tz="Asia/Seoul")
    releases = pd.Series({"2025-04": pd.Timestamp("2025-05-10 00:00", tz="Asia/Seoul")})
    now = mod.feature_availability(targets, 1, 336, "target", releases)
    ahead = mod.feature_availability(targets, 3, 336, "target", releases)
    assert now.available.tolist() == [True, True, True]
    assert ahead.available.tolist() == [False, False, True]
    with pytest.raises(ValueError, match="뒤에"):
        mod.feature_availability(targets, 3, 1, "target", releases)


def test_recent_hour_is_unavailable_until_its_month_is_published():
    targets = pd.date_range("2025-05-10 00:00", periods=3, freq="h", tz="Asia/Seoul")
    releases = pd.Series({"2025-05": pd.Timestamp("2025-06-11", tz="Asia/Seoul")})
    result = mod.feature_availability(targets, 1, 2, "origin", releases)
    assert not result.available.any()
    assert result.source_month.eq("2025-05").all()


def test_catalog_requires_same_cached_file_and_preserves_late_revision():
    rows, sources = [], {}
    for month in range(1, 13):
        key = f"2024-{month:02d}"
        next_month = (pd.Period(key) + 1).to_timestamp()
        spec = dict(apndFileNm=key + ".xlsx", apndFilePathNm=str(month), bdwrSeq=str(month), blbdDivCd="06")
        rows.append(dict(**spec, months=str(month), bdwrDivCd="2024", createDate=str(next_month + pd.Timedelta(days=1)),
            updateDate=str(next_month + pd.Timedelta(days=15)), createId="do_not_export", updateId="do_not_export"))
        sources[key] = dict(request=spec, path=key, sha256="hash")
    result = mod.parse_catalog(rows, 2024, sources)
    assert not {"createId", "updateId"} & set(result.columns)
    assert result.updated_after_creation.all()
    assert result.conservative_guide_and_current_version.eq(result.catalog_updated_at).all()
    rows[0]["apndFilePathNm"] = "different"
    with pytest.raises(ValueError, match="식별자"):
        mod.parse_catalog(rows, 2024, sources)
