import copy
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from core.agent import validate_plan
from core.schema.plan import Plan, load_plan

ROOT = Path(__file__).resolve().parents[2]

CASE = ROOT / "cases" / "_example_night_clinic"


def _raw():
    return yaml.safe_load((CASE / "plan.yaml").read_text(encoding="utf-8"))


def test_example_plan_is_valid():
    p = load_plan(CASE / "plan.yaml")
    assert p.synthetic_data and p.primary_outcome.col == "night_ed_rate"
    assert validate_plan(str(CASE / "plan.yaml"))["ok"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("abstention"),  # 보류 조건 필수
        lambda d: d["estimator"].update(method="magic"),  # 알 수 없는 방법
        lambda d: d["data_sources"][0].update(license="free"),  # 라이선스 enum
        lambda d: d.update(synthetic_data=False),  # 합성 플래그 불일치
        lambda d: d["treatment"].pop("treat_time"),  # 도입 시점 없음
        lambda d: d.update(typo_field=1),  # 미정의 필드
    ],
)
def test_invalid_plans_rejected(mutate):
    d = copy.deepcopy(_raw())
    mutate(d)
    with pytest.raises(ValidationError):
        Plan.model_validate(d)


def test_example_case_runs_end_to_end(tmp_path):
    # 추적 중인 예제 산출물을 건드리지 않도록 임시 복사본에서 실행
    case = tmp_path / "cases" / CASE.name
    shutil.copytree(CASE, case)
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    for script in ("fetch.py", "estimate.py"):
        subprocess.run([sys.executable, str(case / script)], check=True, cwd=case, env=env)
    report = (case / "report.md").read_text(encoding="utf-8")
    assert "합성(synthetic)" in report and (case / "figures" / "event_study.png").exists()
