"""② 수집: 국토교통부 아파트 매매 실거래가(data.go.kr 15126469) → data/

    python cases/hyun2-land-permit-spillover-2020/fetch.py              # 받기 + 만들기
    python cases/hyun2-land-permit-spillover-2020/fetch.py --parse-only # data/raw/ 로 다시 만들기

- 인증키: 환경변수 DATA_GO_KR_API_KEY (레포 루트 .env 도 읽음, 커밋 금지). 키는 화면에 찍지 않는다.
- 받는 범위: 서울 25개 구 × 계약월 2019-06~2021-03, 그리고 강남·서초·송파 × 2014-06~2019-05
  (analysis-plan.yaml 의 과거 해 가짜 지정일·장기 추세 보조 분석용). 약 740쪽, 1쪽 1,000건.
- 받은 응답은 data/raw/<구>/<YYYYMM>_p<쪽>.xml 에 그대로 두고 쪽마다 sha256 을
  data/fetch-manifest.csv 에 적는다. 중간에 끊겨도 다시 돌리면 이미 받은 쪽은 건너뛴다.
- 만드는 파일 (모두 커밋하지 않음):
  - data/deals.csv.gz : 거래 단위 원자료 → estimate.py (주 분석)
  - data/panel.csv    : 옆 동 10곳 vs 먼 동 10곳 × 월, ㎡당 가격 중위값의 로그 → make flow (plan.yaml)
- 가격은 출력하지 않는다. 건수와 sha256 만 출력한다.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import math
import os
import statistics
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from core.adapters.base import MissingAPIKey, load_env  # noqa: E402

DATA = HERE / "data"
RAW = DATA / "raw"
MANIFEST = DATA / "fetch-manifest.csv"
DEALS = DATA / "deals.csv.gz"
PANEL = DATA / "panel.csv"

ENDPOINT = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"
KEY_ENV = "DATA_GO_KR_API_KEY"
PER_PAGE = 1000
SUCCESS_CODES = {"00", "000"}
PAUSE, RETRIES = 0.1, 3

# 서울 25개 자치구 시군구코드. build_outputs 가 응답의 sggCd 와 대조하므로 틀리면 바로 멈춘다.
SEOUL = {
    "11110": "종로", "11140": "중구", "11170": "용산", "11200": "성동", "11215": "광진",
    "11230": "동대문", "11260": "중랑", "11290": "성북", "11305": "강북", "11320": "도봉",
    "11350": "노원", "11380": "은평", "11410": "서대문", "11440": "마포", "11470": "양천",
    "11500": "강서", "11530": "구로", "11545": "금천", "11560": "영등포", "11590": "동작",
    "11620": "관악", "11650": "서초", "11680": "강남", "11710": "송파", "11740": "강동",
}  # fmt: skip
DISTRICT = {"강남": "11680", "서초": "11650", "송파": "11710"}
PLAN_DISTRICTS = tuple(DISTRICT.values())


def months(first: str, last: str) -> list[str]:
    return [
        f"{y}{m:02d}"
        for y in range(int(first[:4]), int(last[:4]) + 1)
        for m in range(1, 13)
        if first <= f"{y}{m:02d}" <= last
    ]


WINDOW = months("201906", "202103")  # month_idx 0..21
HISTORY = months("201406", "201905")
DROPPED = "202006"  # 발표·시행이 겹친 달, 모든 분석에서 뺀다
TARGETS = [(lawd, ymd) for lawd in PLAN_DISTRICTS for ymd in HISTORY + WINDOW] + [
    (lawd, ymd) for lawd in SEOUL if lawd not in PLAN_DISTRICTS for ymd in WINDOW
]

FIELDS = ["sggCd", "umdNm", "dealYear", "dealMonth", "dealDay", "dealAmount", "excluUseAr",
          "buildYear", "cdealType", "cdealDay", "aptNm", "jibun", "floor"]  # fmt: skip
MANIFEST_FIELDS = ["lawd_cd", "deal_ymd", "page", "items", "result_code", "bytes", "sha256"]


class CollectionError(RuntimeError):
    pass


def api_key() -> str:
    load_env()
    key = os.getenv(KEY_ENV, "")
    if not key:
        raise MissingAPIKey(f"환경변수 {KEY_ENV} 가 필요합니다 (.env 에 설정, 커밋 금지).")
    return key


def redact(text: str, key: str) -> str:
    """요청 URL 이 오류 메시지에 찍혀도 키가 보이지 않게 가린다(원문·URL 인코딩 모두)."""
    from urllib.parse import quote, quote_plus

    for form in {key, quote(key, safe=""), quote_plus(key)}:
        text = text.replace(form, "***")
    return text


def page_path(lawd: str, ymd: str, page: int) -> Path:
    return RAW / lawd / f"{ymd}_p{page}.xml"


def parse(body: bytes) -> tuple[str, list[dict[str, str]]]:
    root = ET.fromstring(body)
    code = (root.findtext("./header/resultCode") or root.findtext(".//resultCode") or "").strip()
    items = [{c.tag: (c.text or "").strip() for c in item} for item in root.iter("item")]
    return code, items


def request_page(lawd: str, ymd: str, page: int, key: str) -> bytes:
    import requests

    params = {"serviceKey": key, "LAWD_CD": lawd, "DEAL_YMD": ymd,
              "numOfRows": PER_PAGE, "pageNo": page}  # fmt: skip
    last = ""
    for attempt in range(RETRIES):
        try:
            r = requests.get(ENDPOINT, params=params, timeout=30)
            r.raise_for_status()
            time.sleep(PAUSE)
            return r.content
        except requests.RequestException as err:
            last = redact(f"{type(err).__name__}: {err}", key)
            time.sleep(1.5 * (attempt + 1))
    raise CollectionError(f"{lawd} {ymd} p{page}: 요청 실패 {RETRIES}회 ({last})")


def read_page(lawd: str, ymd: str, page: int) -> tuple[bytes, list[dict[str, str]]] | None:
    """받아 둔 쪽과 그 거래 목록. 없으면 None. 오류 응답이 남아 있으면 멈춘다
    (빈 목록이 '거래 없는 달'로 읽히지 않게)."""
    path = page_path(lawd, ymd, page)
    if not path.exists():
        return None
    body = path.read_bytes()
    code, items = parse(body)
    if code not in SUCCESS_CODES:
        raise CollectionError(f"{path.relative_to(HERE)}: resultCode {code!r}")
    return body, items


def collect(lawd: str, ymd: str, key: str) -> None:
    page = 1
    while True:
        kept = read_page(lawd, ymd, page)
        if kept is None:
            body = request_page(lawd, ymd, page, key)
            code, items = parse(body)
            if code not in SUCCESS_CODES:
                raise CollectionError(f"{lawd} {ymd} p{page}: resultCode {code!r}, 저장 안 함")
            path = page_path(lawd, ymd, page)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(body)
            tmp.replace(path)
        else:
            _, items = kept
        if len(items) < PER_PAGE:
            return
        page += 1


def build_deals() -> tuple[int, list[dict[str, str]]]:
    """data/raw/ 만으로 manifest 와 deals.csv.gz 를 다시 만든다."""
    manifest, deals = [], []
    for lawd, ymd in TARGETS:
        page = 1
        while True:
            path = page_path(lawd, ymd, page)
            kept = read_page(lawd, ymd, page)
            if kept is None:
                raise CollectionError(f"받지 않은 쪽: {path.relative_to(HERE)}")
            body, items = kept
            manifest.append({"lawd_cd": lawd, "deal_ymd": ymd, "page": page,
                             "items": len(items), "result_code": parse(body)[0],
                             "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})  # fmt: skip
            for item in items:
                if item.get("sggCd") != lawd:
                    raise CollectionError(f"{path.relative_to(HERE)}: sggCd {item.get('sggCd')!r}")
                if f"{item['dealYear']}{int(item['dealMonth']):02d}" != ymd:
                    raise CollectionError(f"{path.relative_to(HERE)}: DEAL_YMD 밖의 거래")
                deals.append({f: item.get(f, "") for f in FIELDS})
            if len(items) < PER_PAGE:
                break
            page += 1
    with MANIFEST.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(manifest)
    # mtime=0: 같은 원자료로 다시 만들면 gzip 바이트도 같다.
    with DEALS.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
        text = io.TextIOWrapper(gz, encoding="utf-8", newline="")
        writer = csv.DictWriter(text, FIELDS)
        writer.writeheader()
        writer.writerows(deals)
        text.flush()
        text.detach()
    return len(manifest), deals


def build_panel(deals: list[dict[str, str]]) -> int:
    """plan.yaml 의 단일 대비: 옆 동(ring1=1) vs 먼 동(ring1=0), 동 × 월 ㎡당 가격 중위값의 로그.
    해제 신고는 빼고, 거래가 없는 칸은 행을 만들지 않는다."""
    units = yaml.safe_load((HERE / "analysis-plan.yaml").read_text(encoding="utf-8"))["units"]
    group = {}
    for key, flag in (("ring1_adjacent", 1), ("far_comparison", 0)):
        for name in units[key]:
            gu, dong = name.split()
            group[(DISTRICT[gu], dong)] = flag
    index = {m: i for i, m in enumerate(WINDOW)}
    prices: dict[tuple, list[float]] = {}
    for d in deals:
        unit = (d["sggCd"], d["umdNm"])
        month = f"{d['dealYear']}{int(d['dealMonth']):02d}"
        if unit in group and month in index and month != DROPPED and not d["cdealType"]:
            amount = int(d["dealAmount"].replace(",", ""))
            prices.setdefault((unit, month), []).append(amount / float(d["excluUseAr"]))
    with PANEL.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["dong_id", "month", "month_idx", "ring1", "log_price_m2", "n_deals"])
        for (unit, month), values in sorted(prices.items()):
            writer.writerow([f"{unit[0]}-{unit[1]}", month, index[month], group[unit],
                             math.log(statistics.median(values)), len(values)])  # fmt: skip
    return len(prices)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--parse-only", action="store_true", help="요청 없이 data/raw/ 로 다시 만들기"
    )
    args = parser.parse_args()
    DATA.mkdir(exist_ok=True)
    if not args.parse_only:
        key = api_key()
        for i, (lawd, ymd) in enumerate(TARGETS, 1):
            try:
                collect(lawd, ymd, key)
            except Exception as err:  # 어떤 예외든 키를 가린 메시지만 남긴다
                raise CollectionError(redact(f"{type(err).__name__}: {err}", key)) from None
            if i % 50 == 0 or i == len(TARGETS):
                print(f"{i}/{len(TARGETS)} 구×월 받음", flush=True)
    pages, deals = build_deals()
    cells = build_panel(deals)
    print(f"쪽 {pages}, 거래 {len(deals)}행, 구×월 {len(TARGETS)}, panel 칸 {cells}")
    print(f"deals.csv.gz sha256 {hashlib.sha256(DEALS.read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
