"""정류소 배치 공지의 노선 그룹과 역사적 목록을 값 분석 전에 고정한다."""

import json
import re
import subprocess
from collections import defaultdict

import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .deepening_definitions import Tables
from .deepening_history_data import verify_file
from .deepening_identity import normalize, read_table

CONFIG = "deepening_infrastructure_config.yaml"
OUT = CASE / "results/deepening/infrastructure"
MANIFEST = OUT / "input_manifest.json"


def verify_committed(path):
    content = subprocess.run(["git", "show", "HEAD:" + str(path.relative_to(CASE.parents[1]))], cwd=CASE, capture_output=True, check=True).stdout
    if content != path.read_bytes():
        raise ValueError("운영 이력의 규칙·선택표를 먼저 커밋해야 합니다")


def notice_routes(content, targets):
    parser = Tables()
    parser.feed(content)
    found = defaultdict(list)
    for table in parser.tables:
        for row in table:
            for index, text in enumerate(row[:-1]):
                match = re.search(r"\((\d{2})-(\d{3})\)", text)
                if match and "".join(match.groups()) in targets:
                    ars = "".join(match.groups())
                    value = re.sub(r"\[\d+개노선\]", "", row[index + 1]).strip()
                    if "등" in value:
                        raise ValueError("선택한 공지 행의 노선 목록이 생략돼 있습니다")
                    names = [name.strip() for name in value.split(",")]
                    if not names or len(set(names)) != len(names):
                        raise ValueError("공지 노선 목록의 공란·중복")
                    found[ars].append(names)
    if set(found) != set(targets) or any(len(values) != 1 for values in found.values()):
        raise ValueError("공지 정류소 행의 누락·중복")
    return {ars: values[0] for ars, values in found.items()}


def group_membership(history, retained, cfg, advertised):
    selected = history[history.target_route.isin(retained) & history.match_status.eq("matched")]
    if set(selected.target_route) != set(retained) or selected.groupby("target_route").route_name.nunique().ne(1).any():
        raise ValueError("기존 13개 노선의 역사 이름 누락·다중 대응")
    names = selected[["target_route", "route_name"]].drop_duplicates().rename(columns={"target_route": "route"})
    if names.route_name.duplicated().any():
        raise ValueError("서로 다른 기존 노선 ID에 같은 이름이 대응합니다")
    result = []
    selected_names = set(names.route_name)
    central_sets = [set(advertised[ars]) & selected_names for ars in cfg["notice_ars"]["central"]]
    curb_sets = [set(advertised[ars]) & selected_names for ars in cfg["notice_ars"]["curb"]]
    if central_sets[0] != central_sets[1] or curb_sets[0] != curb_sets[1]:
        raise ValueError("공지 양방향의 공통 노선 목록이 다릅니다")
    expected = {"announced_central": central_sets[0], "announced_curb": curb_sets[0],
                "not_in_selected_notice_rows": selected_names - central_sets[0] - curb_sets[0]}
    if central_sets[0] & curb_sets[0]:
        raise ValueError("중앙·가로변 안내 노선이 중복됩니다")
    for group, spec in cfg["route_groups"].items():
        if expected[group] != set(spec["names"]):
            raise ValueError("사전에 지정한 노선 이름과 공식 안내가 다릅니다")
        part = names[names.route_name.isin(spec["names"])].copy()
        part["group"], part["label"] = group, spec["label"]
        part["historical_name_records"] = part.route.map(selected.groupby("target_route").size())
        result.append(part)
    result = pd.concat(result, ignore_index=True).sort_values(["group", "route"])
    if len(result) != 13 or result.route.duplicated().any():
        raise ValueError("노선 구분은 기존 13개 노선의 완전 분할이어야 합니다")
    return result


def prepare():
    cfg = read_yaml(CONFIG)
    verify_committed(CASE / CONFIG)
    if cfg["years"] != [2023, 2024, 2025] or cfg["locked_year"] != 2026:
        raise ValueError("운영 이력 연도 잠금 변경")
    cohort = json.loads((CASE / cfg["cohort_audit"]).read_text())
    original_path = cohort["configuration"]["reference_audit"]
    original = json.loads((CASE / original_path).read_text())
    retained = sorted(set(original["candidate_routes"]) - {cohort["configuration"]["retired_route"]["id"]})
    source = [row for row in json.loads((CASE / cfg["source_manifest"]).read_text())["files"] if row["id"] == cfg["notice_id"]]
    if len(source) != 1 or sha256(CASE / source[0]["path"]) != source[0]["sha256"]:
        raise ValueError("공식 공지 원문·해시 오류")
    advertised = notice_routes((CASE / source[0]["path"]).read_text(), sum(cfg["notice_ars"].values(), []))
    history = pd.read_csv(CASE / cfg["history_routes"], dtype=str, keep_default_na=False)
    memberships = group_membership(history, retained, cfg, advertised)
    paths = [CONFIG, cfg["history_manifest"], cfg["history_routes"], cfg["history_audit"], cfg["cohort_audit"],
             original_path, original["baseline_path"], cfg["reference_config"], source[0]["path"],
             "gangnam/deepening_identity.py", "gangnam/overnight_matched_directions.py", "gangnam/overnight_sensitivity.py"]
    paths.append(read_yaml(cfg["reference_config"])["base_config"])
    record = dict(configuration=cfg, inputs={name: sha256(CASE / name) for name in paths}, notice=source[0],
                  advertised_routes=advertised, retained_routes=retained, grid_path=cohort["grid_path"], grid_sha256=cohort["grid_sha256"])
    if MANIFEST.exists():
        old = json.loads(MANIFEST.read_text())
        if any(old[key] != value for key, value in record.items()):
            raise ValueError("이미 고정한 운영 이력 입력이 변경됐습니다")
        if sha256(OUT / "route_groups.csv") != old["membership_sha256"]:
            raise ValueError("이미 고정한 노선 그룹 변경")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    memberships.to_csv(OUT / "route_groups.csv", index=False, lineterminator="\n")
    write_json(MANIFEST, dict(prepared_at=utcnow(), **record, membership_sha256=sha256(OUT / "route_groups.csv")))
    print("공식 공지의 중앙 7개·가로변 4개·위 행 미수록 2개 노선과 기존 입력 고정", flush=True)


def verify():
    cfg = read_yaml(CONFIG)
    record = json.loads(MANIFEST.read_text())
    for path in [CASE / CONFIG, MANIFEST, OUT / "route_groups.csv"]:
        verify_committed(path)
    if record["configuration"] != cfg or sha256(OUT / "route_groups.csv") != record["membership_sha256"]:
        raise ValueError("운영 이력 규칙·그룹 변경")
    for name, expected in record["inputs"].items():
        if sha256(CASE / name) != expected:
            raise ValueError("운영 이력 입력 해시 변경: " + name)
    return cfg, record


def history_audit():
    cfg, record = verify()
    source = json.loads((CASE / cfg["history_manifest"]).read_text())["files"]
    summaries, rows = [], []
    for entry in source:
        if entry["metadata_only"] or entry["kind"] == "route_identity":
            continue
        if entry["kind"] not in ["stop_positions", "median_stops"]:
            raise ValueError("예상하지 못한 정류소 목록 종류")
        verify_file(entry)
        header, values, _ = read_table(CASE / entry["path"])
        normalized = normalize(header, values, entry, cfg["years"])
        dates = defaultdict(list)
        for item in normalized:
            dates[item["date"]].append(item)
        targets = cfg["new_stop_ars"] + (cfg["curb_stop_ars"] if entry["kind"] == "stop_positions" else [])
        for day, records in sorted(dates.items()):
            summaries.append(dict(source_id=entry["id"], kind=entry["kind"], date=day, rows=len(records)))
            for ars in targets:
                matches = [row for row in records if row["ars"] == ars]
                status = "matched" if len(matches) == 1 else ("duplicate_ars" if matches else "absent_from_catalog")
                found = matches[0] if len(matches) == 1 else {}
                rows.append(dict(source_id=entry["id"], kind=entry["kind"], date=day, target_ars=ars,
                                 role="announced_new_central" if ars in cfg["new_stop_ars"] else "announced_curb",
                                 match_status=status, catalog_rows=len(records),
                                 **{key: found.get(key, "") for key in ["node", "ars", "name", "x", "y", "type", "date_basis"]}))
    outputs = {"stop_history.csv": pd.DataFrame(rows), "stop_snapshots.csv": pd.DataFrame(summaries)}
    for name, table in outputs.items():
        table.to_csv(OUT / name, index=False, lineterminator="\n")
    write_json(OUT / "history_audit.json", dict(completed_at=utcnow(), manifest_sha256=sha256(MANIFEST),
        code_sha256=sha256(__file__), snapshots=len(summaries), target_rows=len(rows),
        matched=sum(row["match_status"] == "matched" for row in rows), duplicate_ars=sum(row["match_status"] == "duplicate_ars" for row in rows),
        outputs={name: sha256(OUT / name) for name in outputs},
        scope="목록 수록·미수록의 관측일, 실제 시행일·미수록 중 폐쇄·정확한 좌표계는 추정하지 않음"))
    print(f"주변 정류소 이력 {len(summaries)}개 목록 기준일·{len(rows)}개 목표 기록 감사 완료", flush=True)
