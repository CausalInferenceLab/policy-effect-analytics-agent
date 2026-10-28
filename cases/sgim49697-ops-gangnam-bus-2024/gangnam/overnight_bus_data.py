"""승객·다년 버스 원본을 기존 파일과 합쳐 재사용하며 공개 목록의 월 파일만 수집한다."""

from __future__ import annotations

import json
import re
import shutil
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from .common import CASE, read_yaml, write_json
from .followup_data import DATASETS, fetch_one, verify
from .topis import session

BUS_DATASETS = {**DATASETS, "bus_passengers": ("OA-21218", "tpss_a18route_section")}


def collect_requests(wanted, manifest_path, folder, description):
    if any(int(month[:4]) >= 2026 for kind, month in wanted):
        raise ValueError("2026년 잠금 자료 수집 금지")
    folder.mkdir(parents=True, exist_ok=True)
    entries = {}
    for name in ["directional-sources.json", "followup-sources.json", "overnight-passenger-sources.json", manifest_path.name]:
        path = CASE / name
        if path.exists():
            for entry in json.loads(path.read_text())["files"]:
                key = (entry["kind"], entry["month"])
                if key in wanted:
                    entries.setdefault(key, entry)
    for path in folder.glob("*.source.json"):
        entry = json.loads(path.read_text())
        key = (entry["kind"], entry["month"])
        if key in wanted:
            entries.setdefault(key, entry)
    for entry in entries.values():
        verify(entry)
    jobs = []
    with session() as client:
        for kind in sorted({kind for kind, month in wanted}):
            dataset, prefix = BUS_DATASETS[kind]
            source = f"https://data.seoul.go.kr/dataList/{dataset}/S/1/datasetView.do"
            response = client.get(source, timeout=(15, 60))
            response.raise_for_status()
            for month in sorted(month for k, month in wanted if k == kind):
                if (kind, month) in entries:
                    continue
                title = f"{prefix}_{month.replace('-', '')}.zip"
                match = re.search(re.escape(title) + r"[^>]*downloadFile\('([^']+)'\)", response.text)
                if not match:
                    raise ValueError(f"공식 목록에 월 파일이 없습니다: {title}")
                jobs.append({"kind": kind, "month": month, "path": str((folder / f"{kind}_{month}.zip").relative_to(CASE)),
                             "source": source, "url": "https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do?&useCache=false",
                             "method": "POST", "request": {"infId": dataset, "infSeq": "3", "seq": match[1], "seqNo": ""}})
    def save():
        write_json(manifest_path, {"description": description, "files": sorted(entries.values(), key=lambda x: (x["kind"], x["month"]))})
    def fetch(spec):
        if shutil.disk_usage(CASE).free < 25 * 1024**3:
            raise ValueError("디스크 여유가 25 GiB 미만입니다")
        return fetch_one(spec)
    save()
    with ThreadPoolExecutor(max_workers=2) as pool:
        for entry in pool.map(fetch, jobs):
            entries[(entry["kind"], entry["month"])] = entry
            save()
            print(f"버스 추가 수집: {entry['kind']} {entry['month']} {entry['bytes']:,} bytes", flush=True)
    print(f"요청 원본 {len(wanted)}개 확인, 신규 {len(jobs)}개", flush=True)


def passengers():
    cfg = read_yaml("overnight_config.yaml")["passengers"]
    wanted = {("bus_passengers", m) for m in cfg["analysis_months"]}
    collect_requests(wanted, CASE / "overnight-passenger-sources.json", CASE / "data/overnight/passengers",
                     "2024년 4~8월 구간별 총 승객 기록. 중복 구간을 전체 승객으로 더하거나 미확정 분모로 인시·혼잡률을 만들지 않음.")


def multiyear():
    cfg = read_yaml("overnight_multiyear_config.yaml")
    months = set(cfg["reference_2022"]) | {str(p) for p in pd.period_range(*cfg["forecast_development_range"], freq="M")}
    wanted = {(kind, m) for kind in cfg["bus_kinds"] for m in months}
    collect_requests(wanted, CASE / "overnight-multiyear-sources.json", CASE / "data/overnight/multiyear",
                     "2022년 계절 참고 및 2023~2025년 4월 개발용 버스 자료. 2025년 5~8월 시험·2026 잠금 자료 제외.")
