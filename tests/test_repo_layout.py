"""Smoke tests for repo scaffolding: template, app discovery, activity script. No network."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "cases" / "_template"

# Keys shared by the template skeleton and core.schema.plan.Plan.
REQUIRED_PLAN_KEYS = {
    "title",
    "question",
    "unit",
    "treatment",
    "control",
    "outcomes",
    "estimator",
    "assumptions",
    "data_sources",
}


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses need the module registered
    spec.loader.exec_module(mod)
    return mod


def test_template_files_exist():
    for name in ["plan.yaml", "fetch.py", "discussion.md", "README.md"]:
        assert (TEMPLATE / name).is_file(), name


def test_template_plan_has_fields_and_licenses():
    plan = yaml.safe_load((TEMPLATE / "plan.yaml").read_text(encoding="utf-8"))
    assert REQUIRED_PLAN_KEYS <= plan.keys()
    assert all(src.get("license") for src in plan["data_sources"])


def test_template_validates_against_core_schema():
    pytest.importorskip("pydantic")
    try:
        from core.schema.plan import load_plan
    except ImportError:
        pytest.skip("core.schema.plan not available")
    load_plan(TEMPLATE / "plan.yaml")


def test_template_scripts_import():
    _load(TEMPLATE / "fetch.py", "tmpl_fetch")
    assert (TEMPLATE / "discussion.md").exists()


def test_template_fetch_fails_with_clear_message(tmp_path):
    """채우지 않은 fetch.py 는 알아볼 수 있는 안내와 함께 실패해야 한다."""
    import subprocess
    import sys

    r = subprocess.run([sys.executable, str(TEMPLATE / "fetch.py")], capture_output=True, text=True)
    assert r.returncode != 0 and "build_panel" in r.stderr


def test_app_discovers_cases(tmp_path):
    pytest.importorskip("streamlit")
    app = _load(ROOT / "app" / "streamlit_app.py", "streamlit_app")
    case = tmp_path / "gildong-demo"
    (case / "figures").mkdir(parents=True)
    (case / "plan.yaml").write_text("title: Demo\nquestion: q?\n", encoding="utf-8")
    (case / "report.md").write_text("# Demo", encoding="utf-8")
    (case / "figures" / "effect.png").write_bytes(b"")
    (tmp_path / "_template").mkdir()
    (tmp_path / "_template" / "plan.yaml").write_text("title: T\n", encoding="utf-8")

    cases = app.discover_cases(tmp_path)
    assert [c.slug for c in cases] == ["gildong-demo"]
    assert cases[0].title == "Demo" and cases[0].report and len(cases[0].figures) == 1
    assert len(app.discover_cases(tmp_path, include_templates=True)) == 2
    # the real repo has at least the template
    assert app.discover_cases(include_templates=True)


def test_weekly_activity_runs_on_temp_repo(tmp_path):
    act = _load(ROOT / "scripts" / "weekly_activity.py", "weekly_activity")
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    f = tmp_path / "cases" / "gildong-demo" / "plan.yaml"
    f.parent.mkdir(parents=True)
    f.write_text("a: 1\n")
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "plan(gildong-demo): init"], check=True)

    stats = act.collect(tmp_path, days=7, ref=None)
    assert len(stats["cases/gildong-demo"].commits) == 1
    assert stats["cases/gildong-demo"].added == 1


def test_plan_guide_example_validates(tmp_path):
    """문서의 plan.yaml 예시가 실제 스키마를 통과해야 한다 (문서와 코드가 어긋나지 않게)."""
    import re

    from core.schema.plan import load_plan

    text = (ROOT / "docs" / "strategy" / "plan-guide.md").read_text(encoding="utf-8")
    block = re.search(r"```yaml\n(.*?)```", text, re.S).group(1)
    path = tmp_path / "plan.yaml"
    path.write_text(block, encoding="utf-8")
    assert load_plan(path).case_id == "t3-land-permit-2025"
