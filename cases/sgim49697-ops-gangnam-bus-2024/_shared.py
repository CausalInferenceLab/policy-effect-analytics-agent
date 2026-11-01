"""두 최종 분석이 공유하는 경로·해시·설정·독립 실행 디렉터리 규칙."""

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import yaml

CASE = Path(__file__).resolve().parent
INPUT_FILES = ["analysis-plan.yaml", "source-manifest.json"]


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def config():
    result = yaml.safe_load((CASE / "analysis-plan.yaml").read_text(encoding="utf-8"))
    if result["version"] != 1 or result["forecast"]["locked_year"] != 2026:
        raise ValueError("지원하지 않는 분석 버전·연도")
    return result


def inside(base, relative):
    path = (Path(base) / relative).resolve()
    if not path.is_relative_to(Path(base).resolve()):
        raise ValueError("작업 경로 밖의 입력은 허용하지 않습니다")
    return path


def checked(ref, base=CASE):
    path = inside(base, ref["path"])
    if sha256(path) != ref["sha256"]:
        raise ValueError(f"입력 해시 불일치: {ref['path']}")
    return path


def reference(path, base=CASE):
    path = Path(path).resolve()
    return dict(path=str(path.relative_to(Path(base).resolve())), sha256=sha256(path))


def new_run(run_id):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", run_id):
        raise ValueError("실행 ID는 영문·숫자로 시작하는 80자 이내 영문·숫자·하이픈·밑줄입니다")
    path = inside(CASE, "runs/" + run_id)
    path.mkdir(parents=True, exist_ok=False)
    write_json(
        path / "run.json",
        dict(
            started_at=datetime.now(UTC).isoformat(),
            run_id=run_id,
            inputs={name: sha256(CASE / name) for name in INPUT_FILES},
            code={
                name: sha256(CASE / name)
                for name in ["_shared.py", "fetch.py", "estimate.py", "forecast.py"]
            },
        ),
    )
    return path


def verify_inputs(manifest):
    if manifest["inputs"] != {name: sha256(CASE / name) for name in INPUT_FILES}:
        raise ValueError("수집 후 분석 설정 또는 원본 명세가 변경됐습니다")
    return manifest
