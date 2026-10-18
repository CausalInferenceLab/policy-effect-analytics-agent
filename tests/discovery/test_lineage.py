"""트랙 A 데이터 계보: 형식·참조 검사와 그래프."""

import pytest
import yaml
from pydantic import ValidationError

from core.discovery.lineage import LINEAGE_DIR, Lineage, depth, graph, load_lineages, validate


def _lin(steps, **kw):
    base = {
        "id": "zz-test",
        "owner": "zz",
        "topic": "housing-regulation",
        "title": "t",
        "steps": steps,
    }
    return Lineage.model_validate({**base, **kw})


def test_all_lineages_pass():
    lins = load_lineages()
    assert lins, "예시 계보가 있어야 합니다"
    for lin in lins:
        errors, _ = validate(lin, lin.id)
        assert not errors, (lin.id, errors)


def test_template_is_valid_shape():
    Lineage.model_validate(
        yaml.safe_load((LINEAGE_DIR / "_template.yaml").read_text(encoding="utf-8"))
    )


def test_inputs_must_come_first():
    with pytest.raises(ValidationError):
        _lin(
            [
                {"id": "m", "kind": "metric", "inputs": ["raw"], "how": "x"},
                {"id": "raw", "kind": "dataset", "ref": "15126468"},
            ]
        )


def test_transform_needs_how_and_policy_needs_source():
    with pytest.raises(ValidationError):
        _lin(
            [
                {"id": "raw", "kind": "dataset", "ref": "15126468"},
                {"id": "t", "kind": "transform", "inputs": ["raw"]},
            ]
        )
    with pytest.raises(ValidationError):
        _lin([{"id": "p", "kind": "policy"}])


def test_unknown_refs_are_errors_new_data_is_warning():
    lin = _lin(
        [
            {"id": "issue", "kind": "issue", "ref": "no-such-issue"},
            {"id": "raw", "kind": "dataset", "ref": "no-such-dataset"},
            {"id": "new", "kind": "dataset", "url": "https://example.org/data"},
            {"id": "m", "kind": "metric", "inputs": ["new"], "how": "x"},
        ]
    )
    errors, warns = validate(lin, "other-name")
    assert any("no-such-issue" in m for m in errors)
    assert any("no-such-dataset" in m for m in errors)
    assert any("파일 이름" in m for m in errors)
    assert any("카탈로그에 없는 데이터" in m for m in warns)


def test_graph_links_lineage_to_case_and_catalog():
    g = graph()
    ids = {n["id"] for n in g["nodes"]}
    assert "case:t3-land-permit-2025" in ids and "dataset:15126468" in ids
    assert any(e["to"] == "case:t3-land-permit-2025" and e.get("lineage") for e in g["edges"])


def test_depth_orders_columns():
    lin = next(lin for lin in load_lineages() if lin.id == "t3-land-permit-2025")
    d = depth(lin)
    assert d["issue"] == 0 and d["raw_trades"] == 1 and d["gu_month"] == 2 and d["log_trades"] == 3


def test_missing_dataset_is_a_gap_not_an_error():
    lin = _lin(
        [
            {"id": "raw", "kind": "dataset", "ref": "15126468"},
            {"id": "gap", "kind": "dataset", "status": "missing", "label": "권종별 자료"},
            {"id": "m", "kind": "metric", "inputs": ["raw"], "how": "x"},
            {"id": "later", "kind": "metric", "inputs": ["gap"], "how": "x"},
        ]
    )
    errors, warns = validate(lin, lin.id)
    assert not errors
    assert not any("카탈로그에 없는 데이터" in m for m in warns)
    assert any("later" in m and "done" in m for m in warns)  # 빈칸을 쓰는 단계가 done 이면 경고
    with pytest.raises(ValidationError):  # missing 은 데이터에만
        _lin([{"id": "t", "kind": "metric", "inputs": [], "how": "x", "status": "missing"}])
    with pytest.raises(ValidationError):  # 빈칸이 아니면 데이터는 ref·url 필요
        _lin([{"id": "d", "kind": "dataset", "status": "planned"}])


def test_artifact_must_exist_in_repo():
    ok = _lin(
        [
            {
                "id": "raw",
                "kind": "dataset",
                "ref": "15126468",
                "artifact": "catalog/lineage/data/climate-card-stations.csv",
            }
        ]
    )
    assert not validate(ok, ok.id)[0]
    bad = _lin([{"id": "raw", "kind": "dataset", "ref": "15126468", "artifact": "nope.csv"}])
    assert any("artifact" in m for m in validate(bad, bad.id)[0])


def test_climate_card_lineage_feeds_real_case():
    g = graph()
    assert any(e["to"] == "case:t3-climate-card-seongnam" for e in g["edges"])
    gaps = [n for n in g["nodes"] if n.get("status") == "missing"]
    assert gaps, "기후동행카드 계보는 빈칸(권종별 자료 등)을 적어 둡니다"
