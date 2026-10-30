"""공개 파일만 복사한 환경의 검사와 입력 변조·결과 누락 거부를 확인한다."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

CASE = Path(
    os.environ.get(
        "GANGNAM_CASE", Path(__file__).resolve().parents[1] / "cases/sgim49697-ops-gangnam-bus-2024"
    )
)
sys.path.insert(0, str(CASE))
from _shared import checked, new_run  # noqa: E402
from review_submission import check, compare_tables  # noqa: E402


def public_copy(tmp_path):
    manifest = json.loads((CASE / "run_manifest.json").read_text())
    for name in manifest["public_files"]:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(CASE / name, target)
    return tmp_path


def test_public_copy_verifies_without_local_experiments(tmp_path):
    base = public_copy(tmp_path)
    assert len([p for p in base.rglob("*") if p.is_file()]) == 24
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, str(base / "review_submission.py")],
        cwd=base,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    report = json.loads(result.stdout)
    assert report["snapshot_claims"] == 229 and report["primary_claims_matched"] > 0
    assert (
        report["historical_supplemental_claims"] > 0 and report["recomputed_results_compared"] == {}
    )


def test_changed_evidence_is_rejected(tmp_path):
    base = public_copy(tmp_path)
    path = base / "results/deepening/review/key_numbers.csv"
    with path.open("a") as stream:
        stream.write("\n")
    with pytest.raises(ValueError, match="해시 불일치"):
        check(base)


def test_full_table_comparison_rejects_missing_condition(tmp_path):
    expected = CASE / "results/deepening/cohort/comparisons.csv"
    lines = expected.read_text().splitlines(keepends=True)
    actual = tmp_path / "missing.csv"
    actual.write_text("".join(lines[:-1]))
    keys = ["cohort", "comparison", "segment"]
    with pytest.raises(ValueError, match="누락 또는 추가"):
        compare_tables(actual, expected, keys)
    assert compare_tables(expected, expected, keys) == 30


def test_paths_and_run_ids_cannot_escape_case(tmp_path):
    with pytest.raises(ValueError, match="경로 밖"):
        checked(dict(path="../outside", sha256="0" * 64), tmp_path)
    with pytest.raises(ValueError, match="실행 ID"):
        new_run("../outside")


def test_initial_plan_remains_a_valid_common_engine_record():
    from core.schema.plan import load_plan

    plan = load_plan(CASE / "plan.yaml")
    assert (
        plan.case_id == "sgim49697-ops-gangnam-bus-2024"
        and plan.estimator.method == "did"
        and not plan.synthetic_data
    )
