"""공식 ZIP 구조와 같은 합성 파일로 입력 오류·보류 동작을 검사한다."""

import importlib.util
import io
import json
import sys
from pathlib import Path
from zipfile import ZipFile

import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("retail_sales_fetch", HERE / "fetch.py")
fetch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch)


def zipped(rows):
    data = pd.DataFrame(rows, columns=list(fetch.COLUMNS)).to_csv(index=False).encode("cp949")
    output = io.BytesIO()
    with ZipFile(output, "w") as z:
        z.writestr("sales.csv", data)
    return output.getvalue()


@pytest.fixture
def rows():
    return [
        [f"2021{q}", "A", "test-area", industry, "100"]
        for q in range(1, 5)
        for industry in fetch.INDUSTRIES
    ]


def test_selection_and_original_quarters(rows):
    rows.append(["20211", "D", "excluded-area", "CS300007", "999999"])
    rows.append(["20211", "A", "test-area", "CS300001", "999999"])
    frame, info = fetch.read_sales(zipped(rows), 2021)
    assert len(frame) == 16
    assert set(frame.quarter_idx) == {0, 1, 2, 3}
    assert frame.sales_krw.sum() == 1600
    assert info["encoding"] == "cp949"


@pytest.mark.parametrize("amount", ["", "-1", "x", "NaN", "inf", "1.5"])
def test_reject_unknown_or_invalid_amount(rows, amount):
    rows[0][-1] = amount
    with pytest.raises(ValueError, match="매출"):
        fetch.read_sales(zipped(rows), 2021)


def test_no_fill_of_absent_rows(rows):
    frame, _ = fetch.read_sales(zipped(rows[1:]), 2021)
    assert len(frame) == 15  # 부재를 0으로 보충하지 않는다.


def test_duplicate_key(rows):
    with pytest.raises(ValueError, match="중복"):
        fetch.read_sales(zipped(rows + rows[:1]), 2021)


def test_missing_or_wrong_year(rows):
    with pytest.raises(ValueError, match="분기 누락"):
        fetch.read_sales(zipped(rows[:4]), 2021)
    with pytest.raises(ValueError, match="범위"):
        fetch.read_sales(zipped(rows), 2022)


def test_corrupt_snapshot_stops_and_records_reason(tmp_path):
    source = tmp_path / "snapshot/2021"
    source.mkdir(parents=True)
    (source / "metadata.html").write_text("tampered")
    record = {
        "status": "downloaded",
        "dataset_id": "OA-15572",
        "artifacts": {"metadata": {"file": "metadata.html", "http_status": 200, "sha256": "wrong"}},
    }
    (source / "source.json").write_text(json.dumps(record))
    report = fetch.audit(source.parent, tmp_path / "audit")
    assert report["status"] == "blocked" and not report["panel_written"]
    assert any("해시 불일치" in reason for reason in report["blockers"])
    assert not (tmp_path / "audit/panel.csv").exists()


def test_fixed_groups_and_full_panel_shape():
    names = fetch.selected_districts()
    assert len(names) == len(set(names)) == 21 and names[0] == "동대문구"
    totals = pd.DataFrame(
        [(gu, q, ind, 10) for gu in names for q in range(16) for ind in fetch.INDUSTRIES],
        columns=["gu_code", "quarter_idx", "industry_code", "sales_krw"],
    )
    full, panel = fetch.build_panels(totals, treated_code=names[0], control_codes=names[1:])
    assert len(full) == 336 and len(panel) == 315
    assert full.quarter_idx.eq(12).sum() == 21 and not panel.quarter_idx.eq(12).any()
    assert panel.treated.sum() == 15


def test_existing_panel_is_flagged_and_never_overwritten(tmp_path, monkeypatch):
    case = tmp_path / "case"
    (case / "data").mkdir(parents=True)
    panel = case / "data/panel.csv"
    panel.write_text("unverified input")
    for name in [
        "fetch.py",
        "sales_panel.py",
        "characteristics_files.py",
        "fetch_characteristics.py",
        "plan.yaml",
        "comparison-groups.yaml",
    ]:
        (case / name).write_bytes((HERE / name).read_bytes())
    monkeypatch.setattr(fetch, "HERE", case)
    report = fetch.audit(tmp_path / "absent-snapshot", tmp_path / "audit")
    assert report["existing_panel"]
    assert not report["analysis_ready"] and not report["panel_written"]
    assert "기존 data/panel.csv" in report["blockers"][0]
    assert report["requirements"]["amount_period"]["status"] == "partial"
    assert panel.read_text() == "unverified input"
    assert json.loads((tmp_path / "audit/quality.json").read_text()) == report


def test_observation_turnover_keeps_absent_amount_unknown():
    rows = [("구", 0, "CS300007", "old", 10), ("구", 1, "CS300007", "new", 20)]
    rows += [("구", q, "CS300007", "stable", 5) for q in range(16)]
    selected = pd.DataFrame(
        rows, columns=["gu_name", "quarter_idx", "industry_code", "area_code", "sales_krw"]
    )
    result = fetch.observation_diagnostics(selected, ["구"])
    meat = result.loc[result.industry_code.eq("CS300007")].reset_index(drop=True)
    assert meat.loc[0, "observed_raw_amount_krw"] == 15
    assert meat.loc[1, "observed_raw_amount_krw"] == 25
    assert pd.isna(meat.loc[0, "entered_observation"])
    assert meat.loc[1, "entered_observation"] == 1
    assert meat.loc[1, "left_observation"] == 1
    assert meat.observed_all_16_quarters.eq(1).all()
    absent = result.loc[result.industry_code.eq("CS300008")]
    assert absent.observed_raw_amount_krw.isna().all()
    assert absent.observed_areas.eq(0).all()


def observed_fixture():
    names = fetch.selected_districts()
    frame = pd.DataFrame(
        [(gu, q, "area-" + gu, "CS300007", 10) for gu in names for q in range(16)],
        columns=["gu_name", "quarter_idx", "area_code", "industry_code", "sales_krw"],
    )
    return names, frame


def test_observed_panel_accepts_partial_industries_without_imputation():
    names, frame = observed_fixture()
    full, panel = fetch.build_observed_panels(frame, names)
    assert len(full) == 336 and len(panel) == 315
    assert full.observed_industries.eq(1).all() and full.observed_rows.eq(1).all()
    assert full.observed_sales_krw.eq(10).all()
    assert set(panel.quarter_idx) == set(range(16)) - {12}
    assert panel.treated.sum() == 15 and panel.log_observed_sales.notna().all()


@pytest.mark.parametrize("problem", ["absent", "duplicate", "zero", "negative", "nan"])
def test_observed_panel_rejects_unusable_input(problem):
    names, frame = observed_fixture()
    if problem == "absent":
        frame = frame.iloc[1:]
    elif problem == "duplicate":
        frame = pd.concat([frame, frame.iloc[:1]])
    else:
        frame.loc[0, "sales_krw"] = {"zero": 0, "negative": -1, "nan": float("nan")}[problem]
    with pytest.raises(ValueError):
        fetch.build_observed_panels(frame, names)


def test_audit_observed_publication_and_original_scope_block(tmp_path, monkeypatch):
    case = tmp_path / "case"
    case.mkdir()
    for name in [
        "fetch.py",
        "sales_panel.py",
        "characteristics_files.py",
        "fetch_characteristics.py",
        "plan.yaml",
        "comparison-groups.yaml",
    ]:
        (case / name).write_bytes((HERE / name).read_bytes())
    snapshot = tmp_path / "snapshot"
    for key in ["2021", "2022", "2023", "2024", "territory"]:
        folder = snapshot / key
        folder.mkdir(parents=True)
        record = {
            "status": "downloaded",
            "dataset_id": "OA-15560" if key == "territory" else "OA-15572",
        }
        (folder / "source.json").write_text(json.dumps(record))
    names, frame = observed_fixture()
    monkeypatch.setattr(fetch, "HERE", case)
    monkeypatch.setattr(fetch, "verified_bytes", lambda *args: b"verified fixture")
    monkeypatch.setattr(
        fetch, "inspect_territory", lambda *args: ({"area-" + n: n for n in names}, {})
    )
    monkeypatch.setattr(
        fetch,
        "read_sales",
        lambda raw, year: (
            frame.loc[frame.quarter_idx.between((year - 2021) * 4, (year - 2021) * 4 + 3)]
            .drop(columns="gu_name")
            .copy(),
            {"year": year},
        ),
    )
    report = fetch.audit(snapshot, tmp_path / "audit")
    assert not report["panel_written"]
    report = fetch.audit(snapshot, tmp_path / "audit", observed=True)
    assert report["panel_written"] and report["panel_rows"] == 315
    assert report["limitations"] and report["causal_identification"] == "not_identified"
    panel = pd.read_csv(case / "data/panel.csv")
    assert len(panel) == 315 and panel.observed_industries.eq(1).all()
    assert json.loads((case / "data/panel.source.json").read_text())[
        "panel_sha256"
    ] == fetch.digest((case / "data/panel.csv").read_bytes())
