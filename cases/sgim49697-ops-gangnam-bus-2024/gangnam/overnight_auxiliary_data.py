"""공개 월별 카드·환승·출도착 원본을 제한된 범위에서 수집하고 출처를 보존한다."""

from __future__ import annotations

import json
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zipfile import ZipFile

import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .topis import session

RAW = CASE / "data/overnight/auxiliary"
MANIFEST = CASE / "overnight-auxiliary-sources.json"
URL = "https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do?&useCache=false"


def card_validate(path, month):
    required = ["사용년월", "노선번호", "표준버스정류장ID", "버스정류장ARS번호"]
    d = pd.read_csv(path, encoding="cp949", dtype=str, usecols=required)
    if d.empty or set(d["사용년월"]) != {month.replace("-", "")}:
        raise ValueError("카드 원본의 실제 월이 요청과 다릅니다")
    if d[required[:3]].isna().any().any():
        raise ValueError("카드 원본의 필수 키가 비어 있습니다")


def requests_config(cfg):
    wanted = []
    card = cfg["card"]
    for year in card["annual_history"]:
        wanted.append(("card_history", year, card["dataset"],
                       f"{year}년_버스노선별_정류장별_시간대별_승하차_인원_정보.zip", ".zip"))
    for month in card["analysis_months"] + card["identity_only_months"]:
        wanted.append(("card", month, card["dataset"],
                       f"{month[:4]}년_버스노선별_정류장별_시간대별_승하차_인원_정보({month[-2:]}월).csv", ".csv"))
    for kind in ("transfer_probe", "od_probe"):
        p = cfg[kind]
        for month in p["months"]:
            wanted.append((kind, month, p["dataset"], f"{p['prefix']}_{month.replace('-', '')}.zip", ".zip"))
    if any(not re.fullmatch(r"20\d{2}(-(?:0[1-9]|1[0-2]))?", x[1]) or int(x[1][:4]) >= 2026 for x in wanted):
        raise ValueError("월 형식 오류 또는 2026년 잠금 자료 요청")
    if len({(x[0], x[1]) for x in wanted}) != len(wanted):
        raise ValueError("중복된 보조 자료 요청")
    return wanted


def verify(entry):
    path = CASE / entry["path"]
    if not path.resolve().is_relative_to((CASE / "data").resolve()):
        raise ValueError("자료 경로가 data 밖입니다")
    if path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
        raise ValueError(f"보조 원본 해시 불일치: {path}")
    if entry["kind"] == "card":
        card_validate(path, entry["month"])
    else:
        validate_archive(path)


def validate_archive(path):
    """OD 월 파일은 해제 크기가 2 GiB를 넘는다. 디스크에 해제하지 않고 순차 읽는다."""
    with ZipFile(path) as z:
        members = z.infolist()
        if not members or len(members) > 64 or any(not i.filename.lower().endswith(".csv") for i in members):
            raise ValueError("보조 ZIP의 CSV 구성 오류")
        size = sum(i.file_size for i in members)
        if size > 8 * 1024**3:
            raise ValueError("보조 ZIP 해제 크기가 8 GiB를 초과합니다")
    return size


def download_request(catalog, dataset, title):
    """파일 탭의 infSeq는 데이터셋마다 다르므로 공식 폼에서 읽는다."""
    form = re.search(r'<form\b[^>]*name="frmFile"[^>]*>(.*?)</form>', catalog, re.S)
    match = re.search(re.escape(title) + r"[^>]*downloadFile\('([^']+)'\)", catalog)
    if not form or not match:
        raise ValueError(f"공식 파일 폼·목록을 찾을 수 없습니다: {title}")
    values = dict(re.findall(r'<input\b[^>]*name="([^"]+)"[^>]*value="([^"]*)"', form[1]))
    if values.get("infId") != dataset or not values.get("infSeq", "").isdigit():
        raise ValueError("파일 폼의 데이터셋 또는 서비스 번호 불일치")
    return {"infId": dataset, "infSeq": values["infSeq"], "seq": match[1], "seqNo": ""}


def fetch_file(spec):
    path = CASE / spec["path"]
    if path.exists():
        raise ValueError(f"출처 없이 남은 원본을 덮어쓰지 않습니다: {path}")
    part = path.with_suffix(path.suffix + ".part")
    try:
        with session() as client, client.post(URL, data=spec["request"], headers={"Referer": spec["source"]},
                                              stream=True, timeout=(20, 120)) as r:
            r.raise_for_status()
            if "html" in r.headers.get("Content-Type", "").lower():
                raise ValueError("보조 원본 대신 HTML 오류 응답")
            size = 0
            with part.open("wb") as f:
                for chunk in r.iter_content(1024 * 1024):
                    size += len(chunk)
                    cap = (40 if spec["kind"] == "card" else 400) * 1024**2
                    if size > cap:
                        raise ValueError(f"보조 월 파일이 압축 원본 한도 {cap} bytes를 초과합니다")
                    f.write(chunk)
            if r.headers.get("Content-Length") and int(r.headers["Content-Length"]) != size:
                raise ValueError("불완전한 보조 자료 다운로드")
        extra = {}
        if spec["kind"] == "card":
            card_validate(part, spec["month"])
        else:
            extra["uncompressed_bytes"] = validate_archive(part)
        entry = {**spec, **extra, "bytes": size, "sha256": sha256(part), "retrieved_at": utcnow()}
        part.replace(path)
        write_json(path.with_suffix(path.suffix + ".source.json"), entry)
        return entry
    finally:
        part.unlink(missing_ok=True)


def previous():
    entries = []
    for filename in ("directional-history-sources.json", "discovery-sources.json"):
        for entry in json.loads((CASE / filename).read_text())["files"]:
            path = entry.get("path", f"data/discovery/{entry.get('file', '')}")
            match = re.fullmatch(r"boarding_(202[34]\d{2})\.csv", Path(path).name)
            if match:
                m = match[1]
                entries.append({**entry, "path": path, "kind": "card", "month": f"{m[:4]}-{m[4:]}"})
    if MANIFEST.exists():
        entries.extend(json.loads(MANIFEST.read_text())["files"])
    entries.extend(json.loads(p.read_text()) for p in RAW.glob("*.source.json"))
    result = {}
    for entry in entries:
        key = (entry["kind"], entry["month"])
        if key in result and result[key]["sha256"] != entry["sha256"]:
            raise ValueError("동일 보조 원본의 출처 해시가 서로 다릅니다")
        result.setdefault(key, entry)
    return result


def collect():
    wanted = requests_config(read_yaml("overnight_auxiliary_config.yaml"))
    RAW.mkdir(parents=True, exist_ok=True)
    entries = previous()
    keys = {(x[0], x[1]) for x in wanted}
    entries = {k: v for k, v in entries.items() if k in keys}
    for entry in entries.values():
        verify(entry)
    jobs, catalogs = [], {}
    with session() as client:
        for kind, month, dataset, title, suffix in wanted:
            if (kind, month) in entries:
                continue
            source = f"https://data.seoul.go.kr/dataList/{dataset}/S/1/datasetView.do"
            if dataset not in catalogs:
                r = client.get(source, timeout=(15, 60))
                r.raise_for_status()
                catalogs[dataset] = r.text
            request = download_request(catalogs[dataset], dataset, title)
            jobs.append({"kind": kind, "month": month, "path": str((RAW / f"{kind}_{month}{suffix}").relative_to(CASE)),
                         "source": source, "url": URL, "method": "POST", "title": title,
                         "request": request})

    def save():
        write_json(MANIFEST, {"description": "서울 면허 월별 카드와 환승·출도착 원본 탐색. 2025년 카드는 ID 이력 확인 전용.",
                              "config_sha256": sha256(CASE / "overnight_auxiliary_config.yaml"),
                              "files": sorted(entries.values(), key=lambda x: (x["kind"], x["month"]))})

    def fetch(spec):
        if shutil.disk_usage(CASE).free < 25 * 1024**3:
            raise ValueError("디스크 여유가 25 GiB 미만입니다")
        return fetch_file(spec)

    save()
    with ThreadPoolExecutor(max_workers=2) as pool:
        for entry in pool.map(fetch, jobs):
            entries[(entry["kind"], entry["month"])] = entry
            save()
            print(f"보조 원본: {entry['kind']} {entry['month']} {entry['bytes']:,} bytes", flush=True)
    print(f"보조 원본 {len(entries)}개, 신규 {len(jobs)}개", flush=True)
