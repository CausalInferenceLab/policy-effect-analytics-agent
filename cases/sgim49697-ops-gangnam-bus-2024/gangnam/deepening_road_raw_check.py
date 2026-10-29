"""기존 openpyxl 파서와 별도의 XML 판독으로 지정 도로·날짜의 원본 값을 대조한다."""

import json
import math
import posixpath
from concurrent.futures import ProcessPoolExecutor
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
CONFIG = CASE / "deepening_road_raw_check_config.yaml"
OUT = CASE / "results/deepening/road_context"


def workbook_strings(archive):
    strings = []
    if "xl/sharedStrings.xml" not in archive.namelist():
        return strings
    with archive.open("xl/sharedStrings.xml") as source:
        for _, item in ET.iterparse(source, events=["end"]):
            if item.tag == NS + "si":
                strings.append("".join(node.text or "" for node in item.iter(NS + "t")))
                item.clear()
    return strings


def cell_value(cell, strings):
    if cell.find(NS + "f") is not None:
        raise ValueError("원본 대조 범위에 수식 셀이 있습니다")
    kind = cell.get("t", "n")
    if kind == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(NS + "t"))
    raw = cell.findtext(NS + "v", default="")
    if kind == "s":
        return strings[int(raw)]
    if kind not in {"n", "str"}:
        raise ValueError("지원하지 않는 원본 셀 형식: " + kind)
    return raw


def first_sheet(archive):
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    first = workbook.find(NS + "sheets")[0]
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    candidates = [node.get("Target") for node in rels if node.get("Id") == first.get(REL + "id")]
    if len(candidates) != 1:
        raise ValueError("첫 시트의 관계 파일이 모호합니다")
    target = candidates[0]
    path = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
    if not path.startswith("xl/worksheets/") or path not in archive.namelist():
        raise ValueError("XLSX 첫 시트 경로 오류")
    return path


def parse_source(job):
    entry, dates, links, cfg = job
    if any(int(day[:4]) >= cfg["locked_year"] for day in dates) or int(entry["month"][:4]) >= cfg["locked_year"]:
        raise ValueError("잠금 연도 원본 값 접근 금지")
    path = CASE / entry["path"]
    if not path.resolve().is_relative_to((CASE / "data").resolve()) or sha256(path) != entry["sha256"]:
        raise ValueError("도로 원본의 경로·해시 불일치")
    wanted = {day.replace("-", ""): day for day in dates}
    columns = [chr(ord("A") + n) for n in range(26)] + ["A" + chr(ord("A") + n) for n in range(10)]
    expected_headers = ["일자", "요일", "도로명", "링크아이디", "시점명", "종점명", "방향", "거리",
                        "차선수", "기능유형구분", "도심/외곽구분", "권역구분"]
    records, header, scanned, selected = [], None, 0, set()
    with ZipFile(path) as archive:
        strings = workbook_strings(archive)
        with archive.open(first_sheet(archive)) as source:
            for _, element in ET.iterparse(source, events=["end"]):
                if element.tag != NS + "row":
                    continue
                row = {cell.get("r").rstrip("0123456789"): cell for cell in element if cell.tag == NS + "c"}
                if header is None:
                    header = [cell_value(row[c], strings) if c in row else "" for c in columns]
                    endings = [[f"~{hour:02}시" for hour in range(1, 25)], [f"{hour:02}시" for hour in range(1, 25)]]
                    if header[:12] != expected_headers or header[12:] not in endings:
                        raise ValueError("독립 도로 판독의 날짜·시간 헤더 오류")
                    element.clear()
                    continue
                scanned += 1
                date = cell_value(row["A"], strings).removesuffix(".0") if "A" in row else ""
                link = cell_value(row["D"], strings).removesuffix(".0") if "D" in row else ""
                if date in wanted and link in links:
                    key = (date, link)
                    if key in selected:
                        raise ValueError("독립 대조의 링크·날짜 중복")
                    selected.add(key)
                    for hour, column in enumerate(columns[12:]):
                        raw = cell_value(row[column], strings).strip() if column in row else ""
                        if raw in cfg["sentinels"]:
                            value, status = math.nan, "blank_or_sentinel"
                        else:
                            number = float(raw)
                            if not math.isfinite(number):
                                raise ValueError("비유한 원본 속도")
                            value, status = (number, "positive") if number > 0 else (math.nan, "nonpositive")
                        records.append(dict(date=wanted[date], link_id=link, hour=hour, source_speed=value, source_status=status))
                element.clear()
    expected = {(day, link) for day in wanted for link in links}
    if selected != expected:
        raise ValueError("지정한 원본 링크·날짜가 모두 수록되지 않았습니다")
    return records, dict(month=entry["month"], path=entry["path"], sha256=entry["sha256"],
                         rows_scanned=scanned, selected_link_days=len(selected), compared_cells=len(records), header=header)


def run():
    cfg = read_yaml(CONFIG)
    selection = read_yaml(cfg["selection_config"])
    dates = cfg["dates"]
    if len(set(dates)) != len(dates) or any(pd.Timestamp(d).year >= cfg["locked_year"] for d in dates):
        raise ValueError("지정 날짜 중복·잠금 연도")
    months = sorted({date[:7] for date in dates})
    links = sorted({link for spec in selection["groups"].values() for link in spec["links"]})
    source = json.loads((CASE / cfg["source_manifest"]).read_text())["files"]
    entries = [entry for entry in source if entry["month"] in months]
    if len(entries) != len(months) or {entry["month"] for entry in entries} != set(months) or cfg["workers"] not in {1, 2}:
        raise ValueError("원본 월의 누락·중복 또는 작업자 수 오류")
    jobs = [(entry, [day for day in dates if day.startswith(entry["month"])], links, cfg) for entry in entries]
    with ProcessPoolExecutor(max_workers=cfg["workers"]) as pool:
        parts = list(pool.map(parse_source, jobs))
    raw = pd.DataFrame([row for records, _ in parts for row in records])
    extracted, input_paths = [], [str(CONFIG.relative_to(CASE)), cfg["selection_config"], cfg["source_manifest"], *cfg["extraction_manifests"]]
    seen = set()
    for name in cfg["extraction_manifests"]:
        for entry in json.loads((CASE / name).read_text()):
            if entry["month"] not in months:
                continue
            if entry["month"] in seen:
                raise ValueError("추출 월 중복")
            seen.add(entry["month"])
            path = CASE / entry["path"]
            if sha256(path) != entry["sha256"]:
                raise ValueError("도로 추출 해시 불일치")
            d = pd.read_parquet(path)
            d["date"] = d.interval_start_kst.dt.strftime("%Y-%m-%d")
            d["hour"] = d.interval_start_kst.dt.hour
            d = d[d.date.isin(dates) & d.link_id.isin(links)]
            d["cached_speed"] = d.speed_kmh.where(d.is_valid & d.speed_kmh.gt(0))
            extracted.append(d[["date", "link_id", "hour", "cached_speed"]])
    if seen != set(months):
        raise ValueError("추출 월 누락")
    paired = raw.merge(pd.concat(extracted), on=["date", "link_id", "hour"], how="outer", validate="one_to_one", indicator=True)
    paired["status_equal"] = paired.source_speed.isna().eq(paired.cached_speed.isna())
    paired["absolute_difference"] = (paired.source_speed - paired.cached_speed).abs()
    paired["value_equal"] = paired.absolute_difference.le(cfg["absolute_tolerance"]) | (paired.source_speed.isna() & paired.cached_speed.isna())
    if not (paired._merge.eq("both") & paired.status_equal & paired.value_equal).all():
        raise ValueError("독립 원본 대조 불일치")
    output = OUT / "raw_check_cells.csv"
    paired.drop(columns="_merge").to_csv(output, index=False, lineterminator="\n")
    write_json(OUT / "raw_check.json", dict(completed_at=utcnow(), configuration=cfg,
               code_sha256=sha256(__file__), inputs={name: sha256(CASE / name) for name in input_paths},
               source_audits=[audit for _, audit in parts], compared_cells=len(paired), mismatch_cells=0,
               maximum_absolute_difference=float(paired.absolute_difference.max()),
               outputs={output.name: sha256(output)}))
    print(f"도로 원본 {len(paired):,}개 셀의 독립 XML 대조 일치", flush=True)
