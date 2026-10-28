"""정류장 분산 후속 분석의 공개 원본을 검증하며 수집한다."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from zipfile import ZipFile

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .topis import BASE, session, validate_xlsx

RAW = CASE / "data/followup"
MANIFEST = CASE / "followup-sources.json"
DATASETS = {"bus_time": ("OA-21217", "tpss_route_section_speedh"),
            "bus_trips": ("OA-21220", "tpss_sta_route_hturn"),
            "bus_boardings": ("OA-21219", "tpss_sta_route_hpasngr")}


def read_manifest():
    return json.loads(MANIFEST.read_text())["files"] if MANIFEST.exists() else []


def validate(path, kind):
    if kind == "volume":
        validate_xlsx(path)
    else:
        with ZipFile(path) as z:
            if not z.namelist() or any(not n.endswith(".csv") for n in z.namelist()):
                raise ValueError("버스 ZIP 구성 오류")
            if sum(i.file_size for i in z.infolist()) > 2 * 1024**3:
                raise ValueError("ZIP 해제 크기가 2 GiB 한도를 초과합니다")


def verify(entry):
    path = CASE / entry["path"]
    if not path.resolve().is_relative_to((CASE / "data").resolve()):
        raise ValueError("자료 경로가 data 밖입니다")
    if path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
        raise ValueError(f"원본 무결성 오류: {path}")
    validate(path, entry["kind"])
    return path


def fetch_one(spec):
    """한 요청당 별도 세션을 써서 쿠키·연결 풀을 스레드끼리 공유하지 않는다."""
    path = CASE / spec["path"]
    if path.exists():
        raise ValueError(f"매니페스트 없는 파일은 덮어쓰지 않습니다: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    try:
        with session() as client, client.post(spec["url"], data=spec["request"],
                headers={"Referer": spec["source"]}, stream=True, timeout=(20, 120)) as r:
            r.raise_for_status()
            if "html" in r.headers.get("Content-Type", "").lower():
                raise ValueError("파일 대신 HTML 오류를 받았습니다")
            size = 0
            with temporary.open("wb") as f:
                for chunk in r.iter_content(1024 * 1024):
                    size += len(chunk)
                    if size > 400 * 1024**2:
                        raise ValueError("월 원본이 예상을 넘어 400 MiB를 초과합니다")
                    f.write(chunk)
            declared = r.headers.get("Content-Length")
            if declared and int(declared) != size:
                raise ValueError("불완전한 다운로드")
        validate(temporary, spec["kind"])
        entry = {**spec, "bytes": size, "sha256": sha256(temporary), "retrieved_at": utcnow()}
        temporary.replace(path)
        # 병렬 다운로드 중 프로세스가 종료돼도 완료 파일의 출처가 남는다.
        write_json(path.with_suffix(path.suffix + ".source.json"), entry)
        return entry
    finally:
        temporary.unlink(missing_ok=True)


def collect(workers=2):
    if workers not in {1, 2, 3}:
        raise ValueError("동시 수집은 1~3개 요청으로 제한합니다")
    months = read_yaml("followup_config.yaml")["collection_months"]
    existing = {(x["kind"], x["month"]): x for x in read_manifest()}
    old = json.loads((CASE / "discovery-sources.json").read_text())["files"]
    for x in old:
        m = re.fullmatch(r"(bus_time|bus_trips|bus_boardings|volume)_(2024\d{2})\.(zip|xlsx)", x["file"])
        if m:
            kind, month = m[1], f"{m[2][:4]}-{m[2][4:]}"
            existing.setdefault((kind, month), {**x, "kind": kind, "month": month,
                                               "path": f"data/discovery/{x['file']}"})
    RAW.mkdir(parents=True, exist_ok=True)
    # 완료된 sidecar를 복구하되 데이터 파일이 없거나 해시가 다르면 실패한다.
    for path in RAW.glob("*.source.json"):
        x = json.loads(path.read_text())
        existing.setdefault((x["kind"], x["month"]), x)
    for x in existing.values():
        verify(x)
    specs = []
    with session() as client:
        for kind, (dataset, prefix) in DATASETS.items():
            source = f"https://data.seoul.go.kr/dataList/{dataset}/S/1/datasetView.do"
            r = client.get(source, timeout=(15, 60))
            r.raise_for_status()
            catalog = r.text
            for month in months:
                if (kind, month) in existing:
                    continue
                compact = month.replace("-", "")
                title = f"{prefix}_{compact}.zip"
                pattern = re.escape(title) + r"[^>]*downloadFile\('([^']+)'\)"
                match = re.search(pattern, catalog)
                if not match:
                    raise ValueError(f"공식 목록에서 다운로드 인자를 찾지 못했습니다: {title}")
                specs.append({"kind": kind, "month": month, "path": f"data/followup/{kind}_{compact}.zip",
                              "source": source, "url": "https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do?&useCache=false",
                              "method": "POST", "request": {"infId": dataset, "infSeq": "3", "seq": match[1], "seqNo": ""}})
        r = client.post(BASE + "/refroom/selectRefRoomListASC.do",
                        data={"blbdDivCd": "08", "bdwrDivCd": "2024", "mainBdwrRowNum": "12"}, timeout=(15, 60))
        r.raise_for_status()
        rows = {int(x["months"]): x for x in r.json()["rows"]}
        for month in months:
            if ("volume", month) in existing:
                continue
            row = rows[int(month[-2:])]
            if not row.get("apndFileNm"):
                raise ValueError(f"교통량 첨부파일 없음: {month}")
            specs.append({"kind": "volume", "month": month, "path": f"data/followup/volume_{month.replace('-', '')}.xlsx",
                          "source": BASE + "/refRoom/openRefRoom_2.do", "url": BASE + "/downloadFileRefRoom.do",
                          "method": "POST", "request": {k: row[k] for k in ("apndFileNm", "apndFilePathNm", "bdwrSeq", "blbdDivCd")}})
    def save():
        write_json(MANIFEST, {"description": "정류장 분산 후속 분석의 2024년 4~8월 고정 원본. 재배포하지 않음.",
                              "files": sorted(existing.values(), key=lambda x: (x["kind"], x["month"]))})
    save()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for entry in pool.map(fetch_one, specs):
            existing[(entry["kind"], entry["month"])] = entry
            save()
            print(f"수집: {entry['kind']} {entry['month']} {entry['bytes']:,} bytes", flush=True)
    print(f"원본 {len(existing)}개 확보", flush=True)


if __name__ == "__main__":
    collect()
