"""공식 파일·월 필터 다운로드로 지하철 카드 원본을 수집하고 전체 행의 기간·폭을 검증한다."""

import csv
import hashlib
import json
import re
import shutil
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .overnight_auxiliary_data import URL, download_request
from .topis import session

RAW = CASE / "data/overnight/subway"
OUT = CASE / "results/overnight/subway"
MANIFEST = CASE / "overnight-subway-sources.json"
SHEET_URL = "https://datafile.seoul.go.kr/bigfile/iot/sheet/csv/download.do"


def columns(header, kind):
    if len(set(header)) != len(header):
        raise ValueError("지하철 CSV 헤더 중복")
    aliases = {"period": ["사용일자"] if kind == "daily" else ["사용월", "사용년월"],
               "line": ["노선명", "호선명"], "station_name": ["역명", "지하철역"]}
    if kind == "daily":
        aliases.update(boardings=["승차총승객수", "승차인원"], alightings=["하차총승객수", "하차인원"])
    result = {}
    for name, options in aliases.items():
        found = [c for c in options if c in header]
        if len(found) != 1:
            raise ValueError(f"지하철 {kind} 헤더의 {name} 필드가 유일하지 않습니다")
        result[name] = found[0]
    if kind == "hourly_month":
        hours = {}
        for name in header:
            match = re.fullmatch(r"(\d{2})시[-~](\d{2})시(승차|하차)(?:인원|승객수)", name.replace(" ", ""))
            if match:
                hour, end = int(match[1]), int(match[2])
                flow = "boardings" if match[3] == "승차" else "alightings"
                if not 0 <= hour < 24 or end % 24 != (hour + 1) % 24 or (hour, flow) in hours:
                    raise ValueError("지하철 시간대의 범위·중복 오류")
                hours[hour, flow] = name
        if set(hours) != {(hour, flow) for hour in range(24) for flow in ["boardings", "alightings"]}:
            raise ValueError("지하철 월 시간대에 24시간×승하차 열이 없습니다")
        result["hours"] = {f"{hour:02}_{flow}": name for (hour, flow), name in hours.items()}
    return result


def normalized_row(row, header):
    """공식 일별 CSV에서 확인한 단 하나의 빈 끝 칸만 허용한다. 값이 있는 초과 칸은 거부한다."""
    if len(row) == len(header):
        return row, False
    if len(row) == len(header) + 1 and row[-1] == "":
        return row[:-1], True
    raise ValueError("지하철 CSV의 헤더·행 폭 불일치")


def validate(path, month, kind):
    """숫자 결과를 읽기 전에 기간 키를 확인하고 비선택 역을 포함한 모든 CSV 행 폭을 검사한다."""
    if kind not in {"daily", "hourly_month"} or not re.fullmatch(r"202[345]-(0[1-9]|1[0-2])", month):
        raise ValueError("지하철 요청 종류·월 또는 잠금 연도 오류")
    for encoding in ["utf-8-sig", "cp949"]:
        try:
            with path.open(encoding=encoding, newline="") as stream:
                reader = csv.reader(stream)
                header = next(reader, [])
                spec = columns(header, kind)
                period_pos, line_pos, station_pos = [header.index(spec[k]) for k in ["period", "line", "station_name"]]
                rows, dates, lines, trailing_empty_rows = 0, set(), set(), 0
                for row in reader:
                    row, extra = normalized_row(row, header)
                    trailing_empty_rows += extra
                    period = row[period_pos]
                    fmt = r"\d{8}" if kind == "daily" else r"\d{6}"
                    if not re.fullmatch(fmt, period) or period[:6] != month.replace("-", ""):
                        raise ValueError("지하철 요청과 실제 기간이 다릅니다. 결과값은 사용하지 않습니다")
                    if not row[line_pos].strip() or not row[station_pos].strip():
                        raise ValueError("지하철 호선·역명 키가 비었습니다")
                    rows += 1
                    dates.add(period)
                    lines.add(row[line_pos])
            if not rows:
                raise ValueError("지하철 CSV에 관측 행이 없습니다")
            if kind == "daily":
                pd.to_datetime(sorted(dates), format="%Y%m%d", errors="raise")
            result = {"encoding": encoding, "rows": rows, "header": header, "columns": spec,
                      "period_keys": sorted(dates), "observed_lines": sorted(lines)}
            if trailing_empty_rows:
                result["trailing_empty_field_rows"] = trailing_empty_rows
            return result
        except UnicodeError:
            continue
    raise ValueError("지하철 CSV 인코딩을 확인할 수 없습니다")


def verify(entry):
    path = CASE / entry["path"]
    if not path.resolve().is_relative_to(RAW.resolve()) or path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
        raise ValueError("지하철 원본 경로·크기·해시 불일치")
    if validate(path, entry["month"], entry["kind"]) != entry["validation"]:
        raise ValueError("지하철 원본의 검증 내용 변경")
    return path


def sheet_request(catalog, month):
    form = re.search(r'<form\b[^>]*name="frmSheet"[^>]*>(.*?)</form>', catalog, re.S)
    if not form or '<option value="USE_MM">' not in form[1]:
        raise ValueError("공식 월별 지하철 다운로드 폼의 사용월 필터가 없습니다")
    values = dict(re.findall(r'<input\b[^>]*name="([^"]+)"[^>]*value="([^"]*)"', form[1]))
    if values.get("infId") != "OA-12252" or values.get("ssUserId") != "SAMPLE_VIEW":
        raise ValueError("월별 지하철 공개 다운로드 폼이 예상과 다릅니다")
    return {**{k: values[k] for k in ["srvType", "infId", "serviceKind", "pageNo", "ssUserId", "strWhere", "strOrderby"]},
            "gridTotalCnt": "", "filterCol": "USE_MM", "txtFilter": month.replace("-", "")}


def collect(stage="all"):
    cfg = read_yaml("overnight_subway_config.yaml")
    if cfg["locked_year"] != 2026 or cfg["resources"]["download_workers"] not in {1, 2} or stage not in {"probe", "all"}:
        raise ValueError("지하철 수집의 잠금·동시성·단계 오류")
    months = [f"{year}-{month:02}" for year in cfg["years"] for month in cfg["months_of_year"]]
    if len(set(months)) != len(months) or any(int(m[:4]) >= 2026 for m in months):
        raise ValueError("지하철 수집 월의 중복·잠금 범위 오류")
    requested = [cfg["probe_month"]] if stage == "probe" else months
    if not set(requested).issubset(months):
        raise ValueError("지하철 형식 확인 월이 수집 범위 밖입니다")
    RAW.mkdir(parents=True, exist_ok=True)
    entries = {}
    paths = ([MANIFEST] if MANIFEST.exists() else []) + list(RAW.glob("*.source.json"))
    for path in paths:
        doc = json.loads(path.read_text())
        for entry in doc["files"] if "files" in doc else [doc]:
            key = entry["kind"], entry["month"]
            if key in entries and entries[key]["sha256"] != entry["sha256"]:
                raise ValueError("같은 지하철 월 원본의 출처 충돌")
            entries[key] = entry
    for (kind, month), entry in entries.items():
        if month not in months or kind not in cfg["datasets"]:
            raise ValueError("수집 규칙 밖의 지하철 원본이 있습니다")
        verify(entry)
    jobs = []
    with session() as client:
        for kind, dataset in cfg["datasets"].items():
            if all((kind, month) in entries for month in requested):
                continue
            source = f"https://data.seoul.go.kr/dataList/{dataset}/S/1/datasetView.do"
            catalog_url = source if kind == "daily" else "https://data.seoul.go.kr/dataList/sheetView.do?infId=OA-12252&srvType=S"
            response = client.get(catalog_url, timeout=(15, 60))
            response.raise_for_status()
            for month in requested:
                if (kind, month) in entries:
                    continue
                title = f"CARD_SUBWAY_MONTH_{month.replace('-', '')}.csv" if kind == "daily" else f"OA-12252_USE_MM_{month.replace('-', '')}.csv"
                request = download_request(response.text, dataset, title) if kind == "daily" else sheet_request(response.text, month)
                jobs.append({"kind": kind, "month": month, "dataset": dataset, "source": source, "catalog_url": catalog_url,
                             "catalog_sha256": hashlib.sha256(response.content).hexdigest(), "title": title,
                             "url": URL if kind == "daily" else SHEET_URL, "method": "POST", "request": request,
                             "path": str((RAW / f"{kind}_{month}.csv").relative_to(CASE))})

    def save():
        write_json(MANIFEST, {"description": "주변 역·호선 카드 맥락의 공개 일별·월 시간대 원본. 신분당선 미제공.",
                   "config_sha256": sha256(CASE / "overnight_subway_config.yaml"),
                   "files": sorted(entries.values(), key=lambda x: (x["kind"], x["month"]))})

    def fetch(spec):
        if shutil.disk_usage(CASE).free < cfg["resources"]["minimum_free_gib"] * 1024**3:
            raise ValueError("지하철 수집 디스크 여유 부족")
        path = CASE / spec["path"]
        if path.exists():
            raise ValueError("출처 없는 지하철 원본 덮어쓰기 금지")
        part = path.with_suffix(".csv.part")
        try:
            with session() as client, client.post(spec["url"], data=spec["request"], headers={"Referer": spec["catalog_url"]},
                                                  stream=True, timeout=(20, 90)) as response:
                response.raise_for_status()
                if "html" in response.headers.get("Content-Type", "").lower():
                    raise ValueError("지하철 CSV 대신 HTML 응답")
                size = 0
                with part.open("wb") as stream:
                    for block in response.iter_content(1024 * 1024):
                        size += len(block)
                        if size > cfg["resources"]["maximum_file_mib"] * 1024**2:
                            raise ValueError("지하철 월 원본 크기 상한 초과")
                        stream.write(block)
                if response.headers.get("Content-Length") and int(response.headers["Content-Length"]) != size:
                    raise ValueError("지하철 월 원본의 다운로드 미완료")
            entry = {**spec, "bytes": size, "sha256": sha256(part), "retrieved_at": utcnow(),
                     "validation": validate(part, spec["month"], spec["kind"])}
            part.replace(path)
            write_json(path.with_suffix(".csv.source.json"), entry)
            return entry
        finally:
            part.unlink(missing_ok=True)

    save()
    with ThreadPoolExecutor(max_workers=cfg["resources"]["download_workers"]) as pool:
        for entry in pool.map(fetch, jobs):
            entries[entry["kind"], entry["month"]] = entry
            save()
            print(f"지하철 카드 수집: {entry['kind']} {entry['month']} {entry['bytes']:,} bytes", flush=True)
    print(f"지하철 카드 원본 {len(entries)}개 검증", flush=True)
