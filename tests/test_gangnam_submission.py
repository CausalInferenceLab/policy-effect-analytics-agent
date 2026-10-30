"""test_gangnam_submission.py - 추적 파일만으로 공개 검증과 문서 연결이 유지되는지 확인한다."""

import csv
import hashlib
import importlib
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
RELATIVE = Path("cases/sgim49697-ops-gangnam-bus-2024")
CASE = ROOT / RELATIVE
sys.path.insert(0, str(CASE))
mod = importlib.import_module("review_submission")


@pytest.fixture(scope="module")
def public_checkout(tmp_path_factory):
    root = tmp_path_factory.mktemp("gangnam-public")
    names = subprocess.check_output(
        ["git", "ls-files", "-z", "--", str(RELATIVE)], cwd=ROOT
    ).decode().split("\0")
    names = [name for name in names if name]
    manifest = json.loads((CASE / mod.MANIFEST).read_text())
    archived = {str(RELATIVE / item["path"]) for item in manifest["archived_files"]}
    assert not archived.intersection(names), "추적에서 제외한 파일이 공개 복사본에 들어가면 안 됩니다"
    for name in names + ["docs/strategy/plan-guide.md", "tests/test_gangnam_directional.py"]:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(subprocess.check_output(["git", "show", ":" + name], cwd=ROOT))
    case = root / RELATIVE
    assert not (root / ".git").exists()
    assert not (case / "runs").exists()
    assert not (case / ".venv").exists()
    assert list((case / "data").iterdir()) == [case / "data/README.md"]
    assert {str(p.relative_to(case)) for p in case.rglob("*.md")} == set(manifest["documents"])
    return case


@pytest.fixture
def isolated_case(public_checkout, tmp_path):
    case = tmp_path / "case"
    shutil.copytree(public_checkout, case)
    return case


def run_isolated_check(case):
    wrapper = """
import os, runpy, sys
from pathlib import Path
case = Path(sys.argv[1])
sys.path.insert(0, str(case))
sys.argv = ['review_submission.py', '--check']
def readonly(event, args):
    if event == 'open':
        mode, flags = args[1], args[2]
        if (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (
            isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)
        ):
            raise RuntimeError('쓰기 시도: ' + str(args[0]))
    if event in {'socket.connect', 'socket.getaddrinfo'}:
        raise RuntimeError('네트워크 접근 시도')
sys.addaudithook(readonly)
runpy.run_path(str(case / 'review_submission.py'), run_name='__main__')
"""
    return subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", wrapper, str(case)],
        cwd=case, capture_output=True, text=True, timeout=30,
    )


def test_public_checkout_without_git_models_packages_or_writes(public_checkout):
    result = run_isolated_check(public_checkout)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "229개·근거 35개·산출물 155개" in result.stdout
    assert "보관 파일 484개는 검사하지 않았습니다" in result.stdout
    assert re.search(r"HTML 근거 [1-9]\d*개·표시 [1-9]\d*곳", result.stdout)


def test_displayed_html_value_must_match_its_source(isolated_case):
    path = isolated_case / "project-overview.html"
    changed, count = re.subn(
        r'(<([a-z][a-z0-9]*)\b[^>]*\bdata-claim="[^"]+"[^>]*>)([^<]+)(</\2>)',
        lambda match: match[1] + "999999" + match[4], path.read_text(), count=1,
    )
    assert count == 1
    path.write_text(changed)
    result = run_isolated_check(isolated_case)
    assert result.returncode == 1
    assert "화면 표시 수치 불일치" in result.stderr


@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_missing_or_changed_public_source_fails(isolated_case, damage):
    path = isolated_case / "results/deepening/cohort/comparisons.csv"
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="파일 누락|해시와 다른"):
        mod.check(isolated_case)


@pytest.mark.parametrize("damage, message", [
    ("duplicate", "정확히 하나"), ("quality", "품질"), ("nonfinite", "유한 숫자"),
])
def test_replacing_inventory_hash_does_not_bypass_claim_rules(isolated_case, damage, message):
    spec = json.loads((isolated_case / "deepening_review_spec.json").read_text())
    claim = next(c for c in spec["claims"] if c["source"].endswith(".csv") and c.get("require"))
    path = isolated_case / claim["source"]
    reader = csv.DictReader(io.StringIO(path.read_text()))
    rows, fields = list(reader), reader.fieldnames
    selected = next(row for row in rows if all(row[k] == str(v) for k, v in claim["where"].items()))
    if damage == "duplicate":
        rows.append(dict(selected))
    elif damage == "quality":
        selected[next(iter(claim["require"]))] = "invalid"
    else:
        selected[claim["field"]] = "nan"
    content = io.StringIO(newline="")
    writer = csv.DictWriter(content, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(content.getvalue())
    manifest_path = isolated_case / mod.MANIFEST
    manifest = json.loads(manifest_path.read_text())
    entry = next(r for r in manifest["public_artifacts"] if r["path"] == claim["source"])
    entry.update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), bytes=path.stat().st_size)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match=message):
        mod.check(isolated_case)


def test_required_evidence_cannot_be_removed_from_manifest(isolated_case):
    path = isolated_case / mod.MANIFEST
    manifest = json.loads(path.read_text())
    manifest["public_artifacts"] = [r for r in manifest["public_artifacts"]
                                    if r["path"] != "results/deepening/cohort/comparisons.csv"]
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="핵심 근거"):
        mod.check(isolated_case)


def test_case_ignore_allows_public_results_and_future_code():
    manifest = json.loads((CASE / mod.MANIFEST).read_text())
    public = {str(RELATIVE / item["path"]) for item in manifest["public_artifacts"]}
    archived = {str(RELATIVE / item["path"]) for item in manifest["archived_files"]}
    future_private = {str(RELATIVE / name) for name in (
        "results/new-run/detail.csv", "results/new-run/audit.json", "runs/new-run/model.pt",
        ".cache/new-run/log.txt", "data/processed/new.csv",
    )}
    future_public = {str(RELATIVE / name) for name in (
        "new_config.yaml", "gangnam/new_analysis.py", "new-report.md",
    )} | {"cases/another-participant/results/example.csv"}
    candidates = sorted(public | archived | future_private | future_public)
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-z", "--stdin"], cwd=ROOT,
        input="\0".join(candidates) + "\0", capture_output=True, text=True, check=True,
    )
    assert set(result.stdout.rstrip("\0").split("\0")) == archived | future_private


def test_public_document_links_and_images_exist(public_checkout):
    manifest = json.loads((public_checkout / mod.MANIFEST).read_text())
    root = public_checkout.parents[1]
    for name in manifest["documents"]:
        document = public_checkout / name
        text = document.read_text()
        for target in re.findall(r"\]\(([^\n]+?)\)", text):
            link = urlsplit(target.strip("<>"))
            if link.scheme or link.netloc:
                continue
            path = (document.parent / unquote(link.path)).resolve() if link.path else document
            assert path.is_relative_to(root), (name, target)
            assert path.is_file(), (name, target)
            if link.fragment and path.suffix in {".md", ".html"}:
                content = path.read_text()
                identifiers = set(re.findall(r'\bid=["\']([^"\']+)["\']', content))
                for heading in re.findall(r"^#{1,6}\s+(.+)$", content, re.MULTILINE):
                    identifiers.add(re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-"))
                assert unquote(link.fragment) in identifiers, (name, target)
