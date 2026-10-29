"""경기도 공식 게시물의 연도별 첨부를 고정하고 제한된 크기로 수집한다."""

import json
import re
import shutil
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from .common import CASE, read_yaml, sha256, utcnow, write_json
from .deepening_history_data import preserve_requests

CONFIG = CASE / "deepening_gyeonggi_config.yaml"
JOBS = CASE / "results/deepening/gyeonggi/collection_requests.json"
MANIFEST = CASE / "deepening-gyeonggi-sources.json"


class RowLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.text = None
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.text, self.links = [], []
        elif tag == "a" and self.text is not None:
            self.links.append(dict(attrs))

    def handle_data(self, value):
        if self.text is not None:
            self.text.append(value)

    def handle_endtag(self, tag):
        if tag == "tr" and self.text is not None:
            self.rows.append((" ".join("".join(self.text).split()), self.links))
            self.text = None


def parse_catalog(text, cfg):
    parser = RowLinks()
    parser.feed(text)
    result = []
    for text, links in parser.rows:
        if cfg["board_title_contains"] not in text:
            continue
        match = re.search(r"(20\d{2})년\s+노선별 버스 이용객수", text)
        if not match or int(match[1]) not in cfg["years"]:
            continue
        year = int(match[1])
        board_links = [a for a in links if "fn_goView" in a.get("href", "")]
        if len(board_links) != 1:
            raise ValueError("ambiguous public board link")
        board = re.search(r"fn_goView\('([0-9]+)',\s*'([0-9]+)'", board_links[0]["href"])
        if not board:
            raise ValueError("public board identifier not found")
        attached = 0
        for link in links:
            title = link.get("title", "")
            if not title.endswith(" 파일다운로드"):
                continue
            filename = title.removesuffix(" 파일다운로드")
            if Path(filename).name != filename or "\\" in filename or Path(filename).suffix not in {".xlsx", ".zip"}:
                raise ValueError(f"unexpected attachment filename: {filename}")
            url = urljoin("https://gits.gg.go.kr", link["href"])
            if urlparse(url).hostname != "gits.gg.go.kr" or urlparse(url).path != "/gtdb/common/download2.do":
                raise ValueError("unexpected public download endpoint")
            attached += 1
            result.append(dict(id=f"gits_routes_{year}_{attached}", year=year, filename=filename,
                               url=url, board_no=board[1], board_order=board[2],
                               path=f"data/deepening/gyeonggi/{year}/{filename}"))
        if not attached:
            raise ValueError(f"no attachments for selected year {year}")
    return result


def prepare():
    cfg = read_yaml(CONFIG)
    if max(cfg["years"]) >= cfg["locked_year"]:
        raise ValueError("locked years selected")
    manifest = json.loads((CASE / cfg["catalog_manifest"]).read_text())
    jobs, sources = [], []
    for key in cfg["catalog_ids"]:
        entry, = [x for x in manifest["files"] if x["id"] == key]
        path = CASE / entry["path"]
        if sha256(path) != entry["sha256"]:
            raise ValueError(f"catalog hash changed: {key}")
        jobs.extend(parse_catalog(path.read_text(encoding="utf-8"), cfg))
        sources.append({k: entry[k] for k in ["id", "url", "path", "sha256"]})
    if len({j["id"] for j in jobs}) != len(jobs) or {j["year"] for j in jobs} != set(cfg["years"]):
        raise ValueError("duplicate attachments or absent selected years")
    JOBS.parent.mkdir(parents=True, exist_ok=True)
    preserve_requests(JOBS, dict(configuration=cfg, configuration_sha256=sha256(CONFIG),
                                catalogs=sources, jobs=sorted(jobs, key=lambda j: j["id"])))
    print(json.dumps([{k: j[k] for k in ["id", "year", "filename"]} for j in jobs], ensure_ascii=False))


def validate_zip(path, cap_mib):
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if sum(x.file_size for x in entries) > cap_mib * 1024 ** 2:
            raise ValueError("expanded archive exceeds cap")
        if len({x.filename for x in entries}) != len(entries):
            raise ValueError("duplicate archive members")
        if archive.testzip() is not None:
            raise ValueError("archive CRC failure")
        if path.suffix == ".xlsx" and "[Content_Types].xml" not in archive.namelist():
            raise ValueError("download is not an XLSX workbook")
        return {"archive_members": len(entries), "expanded_bytes": sum(x.file_size for x in entries)}


def fetch(job, cfg):
    path = CASE / job["path"]
    sidecar = path.with_suffix(path.suffix + ".source.json")
    if path.exists():
        if not sidecar.exists():
            raise ValueError(f"existing file has no provenance: {path.name}")
        entry = json.loads(sidecar.read_text())
        if entry["id"] != job["id"] or sha256(path) != entry["sha256"]:
            raise ValueError(f"cached source changed: {path.name}")
        return entry
    if shutil.disk_usage(CASE).free < cfg["min_free_gib"] * 1024 ** 3:
        raise ValueError("free disk below configured floor")
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + ".part")
    size = 0
    try:
        with requests.get(job["url"], stream=True, timeout=(15, 60)) as response:
            response.raise_for_status()
            if int(response.headers.get("Content-Length", 0)) > cfg["max_file_mib"] * 1024 ** 2:
                raise ValueError("attachment Content-Length exceeds cap")
            with part.open("xb") as stream:
                for chunk in response.iter_content(1024 ** 2):
                    size += len(chunk)
                    if size > cfg["max_file_mib"] * 1024 ** 2:
                        raise ValueError("attachment exceeds cap")
                    stream.write(chunk)
            content_type = response.headers.get("Content-Type", "")
        quality = validate_zip(part, cfg["max_expanded_file_mib"])
        if path.suffix == ".xlsx":
            with zipfile.ZipFile(part) as archive:
                if "[Content_Types].xml" not in archive.namelist():
                    raise ValueError("XLSX attachment has no workbook content types")
        part.rename(path)
        entry = {**job, "retrieved_at": utcnow(), "bytes": size, "sha256": sha256(path),
                 "content_type": content_type, "quality": quality}
        write_json(sidecar, entry)
        return entry
    finally:
        if part.exists():
            part.unlink()


def collect():
    cfg = read_yaml(CONFIG)
    jobs = json.loads(JOBS.read_text())
    if jobs["configuration_sha256"] != sha256(CONFIG):
        raise ValueError("collection configuration changed after preparation")
    records, failures = [], []
    # Worst-case reservation keeps concurrent downloads below the total configured cap.
    cached = sum((CASE / j["path"]).stat().st_size for j in jobs["jobs"] if (CASE / j["path"]).exists())
    remaining = [j for j in jobs["jobs"] if not (CASE / j["path"]).exists()]
    if cached + min(len(remaining), cfg["workers"]) * cfg["max_file_mib"] * 1024 ** 2 > cfg["max_total_mib"] * 1024 ** 2:
        raise ValueError("download reservation exceeds total cap")
    for start in range(0, len(jobs["jobs"]), cfg["workers"]):
        batch = jobs["jobs"][start:start + cfg["workers"]]
        total = sum(p.stat().st_size for p in (CASE / "data/deepening/gyeonggi").rglob("*") if p.suffix in {".zip", ".xlsx"})
        if total + sum(not (CASE / j["path"]).exists() for j in batch) * cfg["max_file_mib"] * 1024 ** 2 > cfg["max_total_mib"] * 1024 ** 2:
            raise ValueError("next batch reservation exceeds total cap")
        with ThreadPoolExecutor(max_workers=cfg["workers"]) as pool:
            pending = {pool.submit(fetch, job, cfg): job for job in batch}
            for future in as_completed(pending):
                job = pending[future]
                try:
                    entry = future.result()
                    records.append(entry)
                    print(f"{entry['id']}: {entry['bytes']} bytes", flush=True)
                except (OSError, ValueError, requests.RequestException, zipfile.BadZipFile) as error:
                    failures.append(dict(id=job["id"], error_type=type(error).__name__, message=str(error)))
                write_json(MANIFEST, dict(requests_sha256=sha256(JOBS), files=sorted(records, key=lambda x: x["id"]), failures=failures))
        if failures:
            raise RuntimeError("public attachment collection failed; see preserved manifest")
    print(f"collected {len(records)} files, {sum(x['bytes'] for x in records)} bytes", flush=True)
