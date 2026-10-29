"""명시한 과거 도로 형상·ID 목록의 공개 첨부만 해시와 함께 별도 보관한다."""

import json
import shutil
from concurrent.futures import ThreadPoolExecutor

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .deepening_history_data import DOWNLOAD, parse_catalog, preserve_requests, validate_file
from .topis import session

CONFIG = CASE / "deepening_geometry_config.yaml"
RAW = CASE / "data/deepening/geometry"
OUT = CASE / "results/deepening/geometry"
MANIFEST = CASE / "deepening-geometry-sources.json"
REQUESTS = OUT / "collection_requests.json"


def prepare():
    cfg = read_yaml(CONFIG)
    refs = json.loads((CASE / "deepening-reference-sources.json").read_text())["files"]
    inputs = {str(CONFIG.relative_to(CASE)): sha256(CONFIG)}
    requests = []
    for item in cfg["catalogs"]:
        entries = [entry for entry in refs if entry["id"] == item["source_id"]]
        if len(entries) != 1:
            raise ValueError("도로 형상 목록 원문이 모호합니다")
        entry = entries[0]
        path = CASE / entry["path"]
        if sha256(path) != entry["sha256"]:
            raise ValueError("도로 형상 목록 원문 해시 변경")
        form, files = parse_catalog(path.read_text(), item["id"])
        if not set(item["titles"]).issubset(files) or any("2026" in title for title in item["titles"]):
            raise ValueError("명시한 과거 도로 형상 파일이 없거나 범위가 다릅니다")
        inputs[entry["path"]] = entry["sha256"]
        for title in item["titles"]:
            ident = item["id"] + "_" + files[title]
            requests.append(dict(id=ident, title=title, source=entry["url"], url=DOWNLOAD, method="POST",
                request=dict(infId=item["id"], infSeq=form["infSeq"], seq=files[title], seqNo=""),
                path=str((RAW / (ident + ".xlsx")).relative_to(CASE))))
    if len(requests) != 3 or len({item["id"] for item in requests}) != 3:
        raise ValueError("고정한 도로 형상 파일 3개와 다릅니다")
    preserve_requests(REQUESTS, dict(configuration=cfg, inputs=inputs, requests=requests))


def verified(entry):
    path = CASE / entry["path"]
    if not path.resolve().is_relative_to(RAW.resolve()) or path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
        raise ValueError("도로 형상 원본 경로·크기·해시 불일치")
    validate_file(path)


def fetch(job):
    spec, cfg = job
    path = CASE / spec["path"]
    if not path.resolve().is_relative_to(RAW.resolve()) or path.exists():
        raise ValueError("도로 형상 원본을 덮어쓸 수 없습니다")
    if shutil.disk_usage(CASE).free < cfg["min_free_gib"] * 1024**3:
        raise ValueError("도로 형상 수집의 여유 공간 부족")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("partial_" + path.name)
    try:
        with session() as client, client.post(spec["url"], data=spec["request"], headers={"Referer": spec["source"]},
                                              stream=True, timeout=(15, 60)) as response:
            response.raise_for_status()
            size = 0
            with temporary.open("xb") as stream:
                for chunk in response.iter_content(1024**2):
                    size += len(chunk)
                    if size > cfg["maximum_file_mib"] * 1024**2:
                        raise ValueError("도로 형상 파일 크기 한도 초과")
                    stream.write(chunk)
        validate_file(temporary)
        result = {**spec, "bytes": size, "sha256": sha256(temporary), "retrieved_at": utcnow()}
        temporary.replace(path)
        write_json(path.with_suffix(".source.json"), result)
        return result
    finally:
        temporary.unlink(missing_ok=True)


def collect():
    cfg = read_yaml(CONFIG)
    record = json.loads(REQUESTS.read_text())
    if cfg != record["configuration"] or any(sha256(CASE / name) != value for name, value in record["inputs"].items()):
        raise ValueError("도로 형상 수집 요청의 설정·원문 변경")
    existing = {entry["id"]: entry for entry in json.loads(MANIFEST.read_text())["files"]} if MANIFEST.exists() else {}
    for path in RAW.glob("*.source.json"):
        entry = json.loads(path.read_text())
        existing.setdefault(entry["id"], entry)
    specs = {entry["id"]: entry for entry in record["requests"]}
    if set(existing) - set(specs) or cfg["workers"] not in {1, 2}:
        raise ValueError("도로 형상의 고정 요청 밖 파일 또는 동시 수집 한도 오류")
    for ident, entry in existing.items():
        if any(entry[name] != value for name, value in specs[ident].items()):
            raise ValueError("도로 형상 원본과 고정 요청 불일치")
        verified(entry)
    with ThreadPoolExecutor(max_workers=cfg["workers"]) as pool:
        for entry in pool.map(fetch, [(spec, cfg) for spec in specs.values() if spec["id"] not in existing]):
            existing[entry["id"]] = entry
            write_json(MANIFEST, dict(requests_sha256=sha256(REQUESTS), files=sorted(existing.values(), key=lambda item: item["id"])))
            print(f"도로 형상 수집: {entry['title']} ({entry['bytes']:,} bytes)", flush=True)
    write_json(MANIFEST, dict(requests_sha256=sha256(REQUESTS), files=sorted(existing.values(), key=lambda item: item["id"])))
