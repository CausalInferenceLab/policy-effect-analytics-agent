"""설정·파일 무결성·사전 등록 관문을 공유한다."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

CASE = Path(__file__).resolve().parents[1]
PROTOCOL_FILES = ("plan.yaml", "corridors.yaml", "data_contract.yaml", "ml_config.yaml")


def read_yaml(name, case=CASE):
    with (case / name).open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)


def utcnow():
    return datetime.now(UTC).isoformat()


def require_checks(contract, *names):
    missing = [n for n in names if contract["checks"][n]["status"] != "verified"
               or not contract["checks"][n].get("source")]
    if missing:
        raise ValueError("공식 근거 확인이 필요합니다: " + ", ".join(missing))


def require_data_contract(contract):
    require_checks(contract, "hour_semantics", "speed_unit", "missing_values", "usage_terms",
                   "measurement_consistency", "holidays")
    checks = contract["checks"]
    if checks["hour_semantics"]["value"] != "interval_end_label":
        raise ValueError("확인된 시간 표기에 맞춰 파서를 수정해야 합니다")
    if checks["speed_unit"]["value"] != "km/h":
        raise ValueError("km/h 단위 변환을 먼저 구현해야 합니다")
    missing = checks["missing_values"]["value"]
    if missing["zero"] not in {"valid", "missing"} or missing["negative"] != "missing":
        raise ValueError("0·음수 처리 정의가 구현과 일치하지 않습니다")


def protocol_identity(case=CASE):
    return {name: sha256(case / name) for name in PROTOCOL_FILES}


def require_registration(case=CASE, now=None):
    """네 설정의 현재 내용이 커밋된 지 24시간이 지난 경우만 실자료 분석 허용."""
    def git(*args):
        return subprocess.check_output(["git", "-C", str(case), *args], text=True).strip()

    latest = None
    commits = {}
    for name in PROTOCOL_FILES:
        if git("status", "--porcelain", "--", name):
            raise ValueError(f"설정을 먼저 커밋하세요: {name}")
        item = git("log", "-1", "--format=%H %cI", "--", name)
        if not item:
            raise ValueError(f"사전 등록 커밋이 없습니다: {name}")
        commit, stamp = item.split(" ", 1)
        time = datetime.fromisoformat(stamp)
        latest = max(latest, time) if latest else time
        commits[name] = commit
    ready = latest + timedelta(hours=24)
    if (now or datetime.now(UTC)) < ready:
        raise ValueError(f"최종 설정 커밋 후 24시간 대기: 실자료 분석 가능 시각 {ready.isoformat()}")
    return {"commits": commits, "hashes": protocol_identity(case), "ready_at": ready.isoformat()}


def real_data_gate(case=CASE):
    require_data_contract(read_yaml("data_contract.yaml", case))
    return require_registration(case)


def holiday_dates(start="2023-01-01", end="2024-08-31", case=CASE):
    import holidays
    contract = read_yaml("data_contract.yaml", case)
    require_checks(contract, "holidays")
    spec = contract["checks"]["holidays"]
    if not spec["valid_from"] <= start <= end <= spec["valid_to"]:
        raise ValueError("공휴일 검증 범위 밖의 기간입니다")
    years = range(int(spec["valid_from"][:4]), int(spec["valid_to"][:4]) + 1)
    actual = {str(d) for d in holidays.KR(years=years) if spec["valid_from"] <= str(d) <= spec["valid_to"]}
    if actual != set(spec["dates"]):
        raise ValueError("공휴일 패키지 결과와 공식 대조 목록이 다릅니다")
    return {d for d in actual if start <= d <= end}
