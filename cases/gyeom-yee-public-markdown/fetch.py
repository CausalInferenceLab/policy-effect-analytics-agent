"""② 수집: 중앙행정기관 × 월(2024-01 ~ 2026-09) 보도자료 형식 패널 → data/panel.csv

- 출처: 대한민국 정책브리핑(korea.kr) 보도자료 목록·본문 페이지와 첨부 HWPX·PDF (공공누리 제1유형).
  robots.txt 가 수집을 허용한다. 공공데이터포털 API(15095295)는 2026.11 확인 시 폐기되어 쓰지 않는다.
- 목록은 기관·월마다 전부 받아 월별 보도자료 건수(releases, 가짜 지표)를 정확히 센다.
- 본문 지표는 기관·월마다 고정 시드로 SAMPLE_K 건을 뽑아 계산한다(전수는 9만 건·십수 GB라 비현실적).
  계획(plan.yaml)의 '해당 월 전체'에서 바뀐 점이며 discussion.md 에 기록한다.
- 서술형 비율·표 수·중첩 표는 HWPX(XML)에서, 기계 판독 표 손상률은 같은 보도자료의 PDF 를
  pdfplumber(버전 고정)로 읽어 HWPX 표 셀과 대조해 센다. HWPX 가 없는(HWP 만 있는) 보도자료는 형식 지표에서 뺀다.
- 원문·첨부는 저장하지 않고 보도자료별 지표만 data/raw/releases.jsonl 에 캐시한다(커밋하지 않음).
  중간에 끊겨도 다시 실행하면 이어서 받는다.
- 반박 검정용으로 과학기술정보통신부를 뺀 패널(data/panel_no_msit.csv)도 만든다. 공통 실행기가
  drop_unit·placebo_outcome 을 아직 실행하지 않으므로 이 파일과 releases 열로 한 번 더 돌려 보고한다.

필요: pip install pdfplumber==0.11.4   (MIT 라이선스. 공통 의존성에는 넣지 않는다)
"""

from __future__ import annotations

import io
import json
import random
import re
import sys
import threading
import time
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from xml.etree import ElementTree as ET

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "panel.csv"
OUT_NO_MSIT = HERE / "data" / "panel_no_msit.csv"
RAW = HERE / "data" / "raw"
LISTS = RAW / "lists"
CACHE = RAW / "releases.jsonl"

BASE = "https://www.korea.kr"
HEADERS = {"User-Agent": "Mozilla/5.0 (policy-effect-analytics-agent; research)"}
ORIGIN = (2024, 1)  # month_idx 0
N_MONTHS = 33  # 0 = 2024-01 ... 32 = 2026-09
SAMPLE_K = 5
SEED = 20260301
WORKERS = 4
PAUSE = 0.3  # 요청 사이 쉬는 시간(초, 스레드마다)

TREATED = "A00031"  # 행정안전부
MSIT = "A00033"  # 과학기술정보통신부 (drop_unit)

# 정책브리핑 보도자료 검색의 '정부부처' 코드 (2026.11 목록 페이지 기준, 부·처·실·청)
ORGS = {
    "A00004": "국무조정실",
    "A00001": "고용노동부",
    "A00033": "과학기술정보통신부",
    "A00002": "교육부",
    "A00038": "국가데이터처",
    "A00037": "국가보훈부",
    "A00005": "국방부",
    "A00006": "국토교통부",
    "A00040": "기획예산처",
    "A00019": "기후에너지환경부",
    "A00008": "농림축산식품부",
    "A00009": "문화체육관광부",
    "A00010": "법무부",
    "A00011": "법제처",
    "A00012": "보건복지부",
    "A00015": "산업통상부",
    "A00013": "성평등가족부",
    "A00027": "식품의약품안전처",
    "A00014": "외교부",
    "A00030": "인사혁신처",
    "A00041": "재정경제부",
    "A00032": "중소벤처기업부",
    "A00039": "지식재산처",
    "A00017": "통일부",
    "A00023": "해양수산부",
    "A00031": "행정안전부",
    "B00002": "경찰청",
    "B00027": "공소청",
    "B00003": "관세청",
    "B00025": "국가유산청",
    "B00004": "국세청",
    "B00005": "기상청",
    "B00006": "농촌진흥청",
    "B00008": "방위사업청",
    "B00009": "병무청",
    "B00010": "산림청",
    "B00021": "새만금개발청",
    "B00022": "소방청",
    "B00026": "우주항공청",
    "B00024": "재외동포청",
    "B00013": "조달청",
    "B00028": "중대범죄수사청",
    "B00023": "질병관리청",
    "B00017": "해양경찰청",
    "B00018": "행정중심복합도시건설청",
}

# plan.yaml control 의 제외 규칙 (2)·(3). (1) 국가AI전략위원회는 '정부부처' 코드에 없다.
# 새로 생긴 기관(공소청 등)은 '모든 달 1건 이상' 규칙으로 자동으로 빠진다.
EXCLUDE = {
    "B00002": "행안부 소속 청 — 가이드라인 전파 가능",
    "B00022": "행안부 소속 청 — 가이드라인 전파 가능",
    "A00041": "조직 개편(기획재정부 분리)으로 기능이 바뀜",
    "A00040": "조직 개편(기획재정부 분리)으로 신설",
    "A00019": "조직 개편(에너지 기능 이관)으로 기능이 바뀜",
    "A00015": "조직 개편(에너지 기능 이관)으로 기능이 바뀜",
}

_local = threading.local()


def _session() -> requests.Session:
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
        _local.s.headers.update(HEADERS)
    return _local.s


def _get(url: str, params: dict | None = None, tries: int = 4) -> requests.Response:
    for i in range(tries):
        try:
            r = _session().get(url, params=params, timeout=60)
            r.raise_for_status()
            time.sleep(PAUSE)
            return r
        except requests.RequestException:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))
    raise RuntimeError("unreachable")


def month_of(idx: int) -> tuple[int, int]:
    y, m = divmod(ORIGIN[0] * 12 + ORIGIN[1] - 1 + idx, 12)
    return y, m + 1


# ---------------------------------------------------------------- 목록


def list_month(code: str, idx: int) -> list[str]:
    """기관·월의 보도자료 newsId 전부 (목록 페이지 20건씩). 결과는 data/raw/lists 에 캐시."""
    y, m = month_of(idx)
    path = LISTS / f"{code}_{y}{m:02d}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    last = pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0)
    ids: list[str] = []
    page = 1
    while True:
        params = {
            "pageIndex": page,
            "repCodeType": "",
            "repCode": code,
            "period": "direct",
            "startDate": f"{y}-{m:02d}-01",
            "endDate": last.strftime("%Y-%m-%d"),
            "srchWord": "",
        }
        h = _get(f"{BASE}/briefing/pressReleaseList.do", params).text
        # 페이지 옆 '최신 보도자료' 위젯도 같은 링크를 쓰므로 목록 영역만 읽는다
        start = h.find('<div class="list_type">')
        end = h.find("</ul>", start)
        block = h[start:end] if 0 <= start < end else ""
        found = re.findall(r"pressReleaseView\.do\?newsId=(\d+)", block)
        new = [i for i in dict.fromkeys(found) if i not in ids]
        if not new:
            break
        ids += new
        pages = [int(p) for p in re.findall(r"pageLink\((\d+)\)", h)]
        if not pages or page >= max(pages):
            break
        page += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ids), encoding="utf-8")
    return ids


def sample_ids(ids: list[str], code: str, idx: int) -> list[str]:
    ids = sorted(ids)
    return random.Random(f"{SEED}-{code}-{idx}").sample(ids, min(SAMPLE_K, len(ids)))


# ---------------------------------------------------------------- HWPX 지표

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
_SPLIT = re.compile(r"(?<=다\.)\s+|(?<=다\.[\"”’)])\s+")
_NARR = re.compile(r"다\.[\"”’)\]]*$")
_WS = re.compile(r"\s+")


def _text(el) -> str:
    return "".join(t for node in el.iter(f"{HP}t") for t in node.itertext())


def hwpx_metrics(blob: bytes) -> dict:
    """본문(표 밖) 문장·항목의 서술형 비율, 표 수, 중첩 표, 표 셀 텍스트(PDF 대조용)."""
    z = zipfile.ZipFile(io.BytesIO(blob))
    sections = sorted(n for n in z.namelist() if re.fullmatch(r"Contents/section\d+\.xml", n))
    units = narrative = tables = nested = 0
    cells: list[str] = []
    for name in sections:
        root = ET.fromstring(z.read(name))
        for p in root.findall(f"{HP}p"):  # 표 밖 최상위 문단
            body = []
            for run in p.findall(f"{HP}run"):
                for t in run.findall(f"{HP}t"):
                    body.append("".join(t.itertext()))
            for u in _SPLIT.split(_WS.sub(" ", "".join(body)).strip()):
                if len(u.replace(" ", "")) >= 5:
                    units += 1
                    narrative += bool(_NARR.search(u))
            for tbl in p.findall(f"{HP}run/{HP}tbl"):  # 최상위 표
                tables += 1
                inner = [t for t in tbl.iter(f"{HP}tbl") if t is not tbl]
                nested += bool(inner)
        for tc in root.iter(f"{HP}tc"):
            if tc.find(f".//{HP}tbl") is None:  # 가장 안쪽 셀만
                s = _WS.sub("", _text(tc))
                if s:
                    cells.append(s)
    return {
        "units": units,
        "narrative": narrative,
        "tables": tables,
        "has_nested": int(nested > 0),
        "cells": cells,
    }


def pdf_cell_loss(blob: bytes, hwpx_cells: list[str]) -> tuple[int, int]:
    """HWPX 표 셀 중 PDF 표 추출 결과에서 같은 셀로 나오지 않은 셀 수, 전체 셀 수."""
    import pdfplumber

    got: Counter = Counter()
    with pdfplumber.open(io.BytesIO(blob)) as pdf:
        for page in pdf.pages:
            for tb in page.extract_tables():
                for row in tb:
                    for c in row:
                        if c:
                            got[_WS.sub("", c)] += 1
    lost = 0
    for c in hwpx_cells:
        if got[c] > 0:
            got[c] -= 1
        else:
            lost += 1
    return lost, len(hwpx_cells)


# ---------------------------------------------------------------- 보도자료 1건

_ATT = re.compile(
    r'href="/common/download\.do\?fileId=(\d+)&amp;tblKey=(\w+)">\s*<img[^>]*>([^<]*?)\s*</a>'
)


def release(news_id: str) -> dict:
    h = _get(f"{BASE}/briefing/pressReleaseView.do", {"newsId": news_id}).text
    atts = [(f, k, n.strip()) for f, k, n in _ATT.findall(h)]
    exts = [n.rsplit(".", 1)[-1].lower() for _, _, n in atts if "." in n]
    rec: dict = {"newsId": news_id, "exts": exts, "md": int("md" in exts)}
    hwpx = next(((f, k) for f, k, n in atts if n.lower().endswith(".hwpx")), None)
    pdf = next(((f, k) for f, k, n in atts if n.lower().endswith(".pdf")), None)
    if hwpx:
        try:
            blob = _get(
                f"{BASE}/common/download.do", {"fileId": hwpx[0], "tblKey": hwpx[1]}
            ).content
            m = hwpx_metrics(blob)
        except (zipfile.BadZipFile, ET.ParseError, KeyError):
            m = None
        if m:
            cells = m.pop("cells")
            rec.update(m)
            if pdf:
                try:
                    pb = _get(
                        f"{BASE}/common/download.do", {"fileId": pdf[0], "tblKey": pdf[1]}
                    ).content
                    rec["cells_lost"], rec["cells"] = pdf_cell_loss(pb, cells)
                except Exception as e:  # 깨진 PDF 는 손상률에서만 뺀다
                    rec["pdf_error"] = type(e).__name__
    return rec


# ---------------------------------------------------------------- 패널


def _load_cache() -> dict[str, dict]:
    if not CACHE.exists():
        return {}
    out = {}
    for line in CACHE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out[r["newsId"]] = r
    return out


def build_panel() -> pd.DataFrame:
    cells = [(c, i) for c in ORGS for i in range(N_MONTHS)]
    with ThreadPoolExecutor(WORKERS) as ex:
        lists = dict(zip(cells, ex.map(lambda ci: list_month(*ci), cells), strict=True))
    print(f"[fetch] 목록 {len(cells)}칸, 보도자료 {sum(map(len, lists.values()))}건")

    keep = [c for c in ORGS if c not in EXCLUDE and all(lists[(c, i)] for i in range(N_MONTHS))]
    dropped = {ORGS[c]: EXCLUDE.get(c, "어떤 달에 보도자료가 없음") for c in ORGS if c not in keep}
    print(f"[fetch] 분석 기관 {len(keep)}곳, 제외 {dropped}")

    sampled = {(c, i): sample_ids(lists[(c, i)], c, i) for c in keep for i in range(N_MONTHS)}
    cache = _load_cache()
    todo = sorted({n for ids in sampled.values() for n in ids} - cache.keys())
    print(f"[fetch] 표본 {sum(map(len, sampled.values()))}건, 새로 받을 것 {len(todo)}건")
    lock = threading.Lock()
    CACHE.parent.mkdir(parents=True, exist_ok=True)

    def work(n: str) -> None:
        try:
            r = release(n)
        except requests.RequestException as e:
            r = {"newsId": n, "error": type(e).__name__}
        with lock, CACHE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            cache[n] = r
            if len(cache) % 200 == 0:
                print(f"[fetch] … {len(cache)}건", flush=True)

    with ThreadPoolExecutor(WORKERS) as ex:
        list(ex.map(work, todo))

    rows = []
    for (c, i), ids in sampled.items():
        recs = [cache[n] for n in ids if "error" not in cache[n]]
        fm = [r for r in recs if "units" in r]
        pm = [r for r in fm if "cells" in r]
        units = sum(r["units"] for r in fm)
        pc = sum(r["cells"] for r in pm)
        y, m = month_of(i)
        rows.append(
            {
                "org_id": c,
                "org_name": ORGS[c],
                "month": f"{y}-{m:02d}",
                "month_idx": i,
                "treated": int(c == TREATED),
                "releases": len(lists[(c, i)]),
                "n_sampled": len(recs),
                "n_hwpx": len(fm),
                "n_pdf": len(pm),
                "narrative_share": sum(r["narrative"] for r in fm) / units if units else None,
                "tables_per_release": sum(r["tables"] for r in fm) / len(fm) if fm else None,
                "nested_table_share": sum(r["has_nested"] for r in fm) / len(fm) if fm else None,
                "md_attach_share": sum(r["md"] for r in recs) / len(recs) if recs else None,
                "parse_table_loss": sum(r["cells_lost"] for r in pm) / pc if pc else None,
            }
        )
    return pd.DataFrame(rows).sort_values(["org_id", "month_idx"]).reset_index(drop=True)


def main() -> None:
    panel = build_panel()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(OUT, index=False)
    panel[panel["org_id"] != MSIT].to_csv(OUT_NO_MSIT, index=False)
    errors = sum("error" in r for r in _load_cache().values())
    print(f"[fetch] {len(panel)}행 → {OUT.relative_to(HERE)} (받기 실패 {errors}건)")
    if errors:
        sys.exit(
            "일부 보도자료를 받지 못했습니다. data/raw/releases.jsonl 의 error 줄을 지우고 다시 실행하세요."
        )


if __name__ == "__main__":
    main()
