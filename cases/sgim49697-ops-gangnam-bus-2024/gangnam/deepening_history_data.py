"""공식 파일 폼을 확인해 2023~2025년 정류장·노선 이력과 컬럼 명세를 별도 수집한다."""

import json
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from zipfile import ZipFile

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .topis import session

RAW = CASE / "data/deepening/history"
MANIFEST = CASE / "deepening-history-sources.json"
REQUESTS = CASE / "results/deepening/history/collection_requests.json"
DOWNLOAD = "https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do?&useCache=false"


class FileCatalog(HTMLParser):
    """API 폼과 파일 폼의 서로 다른 infSeq 및 중복 다운로드 링크를 구별한다."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_file_form = False
        self.form = {}
        self.files = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.in_file_form = attrs.get("id", attrs.get("name")) == "frmFile"
        if self.in_file_form and tag == "input" and attrs.get("name") in {"infId", "infSeq", "seqNo", "seq"}:
            self.form[attrs["name"]] = attrs.get("value", "")
        title = attrs.get("title", "")
        action = attrs.get("onclick", attrs.get("href", ""))
        match = re.fullmatch(r"(?:javascript:)?downloadFile\('([0-9]+)'\);?", action)
        if title and match and Path(title).suffix.lower() in {".csv", ".xlsx", ".zip", ".pdf", ".hwp"}:
            if Path(title).name != title or "\\" in title:
                raise ValueError("다운로드 제목에 경로가 포함되어 있습니다")
            if title in self.files and self.files[title] != match[1]:
                raise ValueError("같은 파일 제목에 다른 다운로드 번호가 있습니다")
            self.files[title] = match[1]

    def handle_endtag(self, tag):
        if tag == "form":
            self.in_file_form = False


def parse_catalog(content, dataset):
    parser = FileCatalog()
    parser.feed(content)
    if (parser.form.get("infId") != dataset or not parser.form.get("infSeq", "").isdigit()
            or not parser.files):
        raise ValueError("공식 파일 폼·목록이 없습니다. 서비스 오류 HTML을 목록으로 사용하지 않습니다")
    return parser.form, parser.files


def selected_title(title, cfg):
    metadata = title.startswith(cfg["metadata_title_prefix"])
    if Path(title).suffix.lower() not in cfg["allowed_data_extensions"]:
        return False, metadata
    years = {int(year) for year in re.findall(r"20\d{2}", title)}
    allowed = bool(years and years.issubset(set(cfg["years"])) and not years.intersection(cfg["locked_outcome_years"]))
    return metadata or allowed, metadata


def prepare_requests():
    cfg = read_yaml("deepening_history_config.yaml")
    if cfg["years"] != [2023, 2024, 2025] or cfg["locked_outcome_years"] != [2026]:
        raise ValueError("역사 자료의 고정 수집 연도 오류")
    sources = json.loads((CASE / "deepening-sources.json").read_text())["files"]
    requests, inputs = [], {}
    for dataset in cfg["datasets"]:
        matches = [item for item in sources if item["id"] == dataset["catalog"]]
        if len(matches) != 1 or matches[0]["status"].startswith("rejected"):
            raise ValueError("유효한 공식 과거 목록 원문이 없습니다")
        entry = matches[0]
        path = CASE / entry["path"]
        if sha256(path) != entry["sha256"]:
            raise ValueError("목록 원문 해시 변경")
        form, files = parse_catalog(path.read_text(encoding="utf-8"), dataset["id"])
        inputs[entry["path"]] = entry["sha256"]
        for title, sequence in sorted(files.items()):
            include, metadata = selected_title(title, cfg)
            if not include:
                continue
            requests.append({"id": f"{dataset['id']}_{sequence}", "dataset": dataset["id"], "kind": dataset["key"],
                "title": title, "metadata_only": metadata, "source": entry["source"], "url": DOWNLOAD, "method": "POST",
                "request": {"infId": dataset["id"], "infSeq": form["infSeq"], "seq": sequence, "seqNo": ""},
                "path": str((RAW / dataset["key"] / f"{sequence}_{title}").relative_to(CASE))})
    if not requests or len({item["id"] for item in requests}) != len(requests):
        raise ValueError("역사 자료 요청이 비었거나 다운로드 ID가 중복됩니다")
    inputs["deepening_history_config.yaml"] = sha256(CASE / "deepening_history_config.yaml")
    write_json(REQUESTS, {"prepared_at": utcnow(), "configuration": cfg, "inputs": inputs, "requests": requests})
    print(f"역사적 파일·명세 {len(requests)}개 요청 확정. 파일 본문은 아직 열지 않았습니다.", flush=True)


def validate_file(path):
    if path.suffix == ".xlsx":
        with ZipFile(path) as archive:
            if "xl/workbook.xml" not in archive.namelist() or sum(x.file_size for x in archive.infolist()) > 400 * 1024**2:
                raise ValueError("유효한 크기의 XLSX 문서가 아닙니다")
            if archive.testzip() is not None:
                raise ValueError("XLSX 내부 파일 무결성 오류")
    elif path.suffix == ".csv":
        with path.open("rb") as f:
            prefix = f.read(2048).lstrip()
        if not prefix or prefix.startswith((b"<", b"\xef\xbb\xbf<")):
            raise ValueError("CSV 대신 빈 응답·HTML/XML을 받았습니다")
    else:
        raise ValueError("지원하지 않는 역사 파일 형식")


def verify_file(entry):
    path = (CASE / entry["path"]).resolve()
    if not path.is_relative_to(RAW.resolve()) or path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
        raise ValueError("역사 원본 경로·크기·해시 불일치")
    validate_file(path)
    return path


def fetch(job):
    spec, maximum = job
    path = (CASE / spec["path"]).resolve()
    if not path.is_relative_to(RAW.resolve()) or path.exists():
        raise ValueError("역사 원본을 덮어쓰거나 지정 경로 밖에 저장할 수 없습니다")
    if shutil.disk_usage(CASE).free < 25 * 1024**3:
        raise ValueError("여유 공간 25 GiB 미만")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("temporary_" + path.name)
    try:
        with session() as client, client.post(spec["url"], data=spec["request"],
                headers={"Referer": spec["source"]}, timeout=(20, 60), stream=True) as response:
            response.raise_for_status()
            size = 0
            with temporary.open("xb") as f:
                for chunk in response.iter_content(1024**2):
                    size += len(chunk)
                    if size > maximum:
                        raise ValueError("역사 파일이 사전 크기 한도를 초과했습니다")
                    f.write(chunk)
        validate_file(temporary)
        entry = {**spec, "bytes": size, "sha256": sha256(temporary), "retrieved_at": utcnow()}
        temporary.replace(path)
        write_json(path.with_suffix(path.suffix + ".source.json"), entry)
        return entry
    finally:
        temporary.unlink(missing_ok=True)


def collect():
    cfg = read_yaml("deepening_history_config.yaml")
    record = json.loads(REQUESTS.read_text())
    if record["configuration"] != cfg or any(sha256(CASE / name) != expected for name, expected in record["inputs"].items()):
        raise ValueError("준비한 역사 수집 규칙·목록이 변경됐습니다")
    existing = {item["id"]: item for item in json.loads(MANIFEST.read_text())["files"]} if MANIFEST.exists() else {}
    for sidecar in RAW.rglob("*.source.json"):
        item = json.loads(sidecar.read_text())
        existing.setdefault(item["id"], item)
    for item in existing.values():
        verify_file(item)
    jobs = [(spec, cfg["maximum_file_mib"] * 1024**2) for spec in record["requests"] if spec["id"] not in existing]
    for spec in record["requests"]:
        if spec["id"] in existing and any(existing[spec["id"]][key] != spec[key] for key in ["title", "request", "path"]):
            raise ValueError("같은 다운로드 ID의 제목·요청·경로가 달라졌습니다")
    with ThreadPoolExecutor(max_workers=2) as pool:
        for entry in pool.map(fetch, jobs):
            existing[entry["id"]] = entry
            write_json(MANIFEST, {"description": "공식 2023~2025년 정류장·노선 이력 파일과 별도 컬럼 명세. 원문 재배포하지 않음.",
                "requests_sha256": sha256(REQUESTS), "files": sorted(existing.values(), key=lambda item: item["id"])})
            print(f"역사 파일 수집: {entry['title']} ({entry['bytes']:,} bytes)", flush=True)

