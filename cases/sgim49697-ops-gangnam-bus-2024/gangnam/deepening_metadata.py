"""원래 선택한 도로의 전체 월별 속성을 감사하며 속도 관측값은 열지 않는다."""

import calendar
import json
import math
import subprocess
from datetime import date

import pandas as pd

from .common import CASE, digest, read_yaml, sha256, utcnow, write_json

CONFIG = "deepening_metadata_config.yaml"
OUT = CASE / "results/deepening/metadata"


def validate_record(row, month, fields):
    first = date.fromisoformat(row["observed_from"])
    last = date.fromisoformat(row["observed_to"])
    days = row["days"]
    if not first.isoformat().startswith(month) or not last.isoformat().startswith(month):
        raise ValueError("속성 관측 날짜가 해당 월 밖입니다")
    if first > last or not isinstance(days, int) or not 1 <= days <= (last - first).days + 1:
        raise ValueError("속성의 관측 범위·일수 불일치")
    if any(row.get(field) is None or str(row[field]).strip() == "" for field in fields):
        raise ValueError("도로 속성 필드가 누락됐습니다")
    for field in ["거리", "차선수"]:
        value = row[field]
        if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError("거리·차선수가 양의 유한 숫자가 아닙니다")
    if int(row["차선수"]) != row["차선수"]:
        raise ValueError("차선수가 정수가 아닙니다")


def summarize_month(rows, month, fields):
    expected = calendar.monthrange(*map(int, month.split("-")))[1]
    for row in rows:
        validate_record(row, month, fields)
    signatures = [digest({field: row[field] for field in fields}) for row in rows]
    if len(set(signatures)) != len(signatures):
        raise ValueError("월별 동일 속성 중복")
    observed = sum(row["days"] for row in rows)
    if observed > expected:
        raise ValueError("월별 전체 속성 일수가 달력 일수를 초과합니다")
    complete_single = len(rows) == 1 and observed == expected and rows[0]["observed_from"] == month + "-01" and rows[0]["observed_to"] == f"{month}-{expected:02d}"
    return dict(variants=len(rows), recorded_days=observed, expected_days=expected,
                recorded_fraction=observed / expected, single_variant_full_month=complete_single,
                signature=signatures[0] if len(rows) == 1 else "")


def run():
    cfg = read_yaml(CONFIG)
    path = CASE / CONFIG
    committed = subprocess.run(["git", "show", "HEAD:" + str(path.relative_to(CASE.parents[1]))], cwd=CASE, capture_output=True, check=True).stdout
    if committed != path.read_bytes():
        raise ValueError("전체 속성 감사 규칙을 먼저 커밋해야 합니다")
    months = pd.period_range(*cfg["months"], freq="M").astype(str).tolist()
    if len(months) != 36 or any(int(month[:4]) >= cfg["locked_year"] for month in months):
        raise ValueError("속성 감사 범위·잠금 오류")
    parent = read_yaml(cfg["selection_config"])
    groups = {link: group for group, spec in parent["groups"].items() for link in spec["links"]}
    if len(groups) != 14:
        raise ValueError("원래 선택한 14개 링크와 다릅니다")
    entries, inputs = [], {}
    for name in cfg["extraction_manifests"]:
        source = json.loads((CASE / name).read_text())
        entries.extend(source["extractions"] if isinstance(source, dict) else source)
        inputs[name] = sha256(CASE / name)
    if sorted(entry["month"] for entry in entries) != months:
        raise ValueError("속성 원본 명세의 월 누락·중복")
    # 이미 동결된 예측 입력에 연결된 추출 명세와 같아야 한다. 속도 Parquet는 읽지 않는다.
    frozen_path = CASE / "results/deepening/archive_forecast/input_manifest.json"
    frozen = json.loads(frozen_path.read_text())
    if any(frozen["inputs"].get(name) != value for name, value in inputs.items()):
        raise ValueError("기존 동결 명세와 전체 속성 감사 입력이 다릅니다")
    inputs[str(frozen_path.relative_to(CASE))] = sha256(frozen_path)
    variants, status, history = [], [], {link: [] for link in groups}
    for entry in sorted(entries, key=lambda item: item["month"]):
        month = entry["month"]
        for link, group in groups.items():
            rows = [row for row in entry["metadata"] if row["링크아이디"] == link]
            summary = summarize_month(rows, month, cfg["fields"])
            status.append(dict(month=month, link_id=link, group=group, **summary))
            history[link].append((month, rows, summary))
            for row in rows:
                variants.append(dict(month=month, link_id=link, group=group, source_sha256=entry["source_sha256"],
                                     **{field: row[field] for field in [*cfg["fields"], "observed_from", "observed_to", "days"]}))
    changes = []
    for link, records in history.items():
        for (before, left, left_summary), (after, right, right_summary) in zip(records[:-1], records[1:], strict=True):
            if not left_summary["single_variant_full_month"] or not right_summary["single_variant_full_month"]:
                continue
            for field in cfg["fields"]:
                if left[0][field] != right[0][field]:
                    changes.append(dict(link_id=link, group=groups[link], before_month=before, after_month=after,
                                        field=field, before_value=left[0][field], after_value=right[0][field]))
    OUT.mkdir(parents=True, exist_ok=True)
    tables = {"variants.csv": pd.DataFrame(variants), "monthly_status.csv": pd.DataFrame(status),
              "adjacent_changes.csv": pd.DataFrame(changes, columns=["link_id", "group", "before_month", "after_month", "field", "before_value", "after_value"])}
    for name, frame in tables.items():
        frame.to_csv(OUT / name, index=False, lineterminator="\n")
    write_json(OUT / "audit.json", dict(completed_at=utcnow(), configuration=cfg, code_sha256=sha256(__file__),
        inputs={CONFIG: sha256(path), cfg["selection_config"]: sha256(CASE / cfg["selection_config"]), **inputs},
        monthly_link_states=len(status), metadata_variants=len(variants), changed_adjacent_fields=len(changes),
        full_single_variant_months=sum(row["single_variant_full_month"] for row in status),
        missing_link_months=sum(row["variants"] == 0 for row in status),
        outputs={name: sha256(OUT / name) for name in tables},
        scope="원래 추출 명세의 속성만 감사", speed_values_read=False, physical_invariance_proved=False))
    print(f"전체 속성 {len(status)}개 링크·월, 인접 완전 월의 변경 필드 {len(changes)}건 감사 완료", flush=True)
