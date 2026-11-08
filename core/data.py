"""데이터 연동 — 카탈로그(datasets.yaml)의 데이터를 '어떻게 받나'를 한 곳에서.

데이터셋마다 연결 방식을 하나 정한다 (위에서부터 먼저 맞는 것):
    adapter  레포에 수집기가 있다       → python -m core.data fetch <id>  (키는 .env 의 환경변수)
    case     참여자가 이미 받아 본 코드  → cases/<케이스>/fetch.py 를 복사해 쓴다
    api_key  오픈API — 포털에서 키 발급  → 포털 페이지의 요청 주소·인자로 직접 호출
    file     파일 내려받기               → 포털 페이지에서 내려받아 data/raw/ 에
    manual   웹 조회·신청                → 안내대로 받은 뒤 data/raw/ 에

    python -m core.data show 15126468            # 연결 방식·코드
    python -m core.data issue seoul-ltp-1015-2025  # 이슈 하나에 필요한 데이터 전부
    python -m core.data fetch DT_1B040A3 --start 2015 --end 2024 -o data/raw/pop.csv

원자료·키는 커밋하지 않는다(data/ 는 .gitignore). 받은 날짜와 주소는 출력에 함께 남긴다.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

KIND_KO = {
    "adapter": "자동 수집",
    "case": "참여자 수집 코드",
    "api_key": "API 키 필요",
    "file": "파일 내려받기",
    "manual": "웹 조회·신청",
}
MOLIT = {"15126468", "15126469"}
PRD = {"연": "Y", "반기": "H", "분기": "Q", "월": "M", "일": "D"}
KEY_HELP = {
    "KOSIS_API_KEY": "https://kosis.kr/openapi/ 에서 인증키 신청(즉시)",
    "DATA_GO_KR_API_KEY": "공공데이터포털 데이터 페이지의 '활용신청' → 마이페이지 인증키(Decoding)",
}


def _kosis_ids(url: str) -> tuple[str, str] | None:
    q = parse_qs(urlparse(url).query)
    if "orgId" in q and "tblId" in q:
        return q["orgId"][0], q["tblId"][0]
    return None


def connector(d, users: dict[str, list[str]] | None = None) -> dict:
    """데이터셋 하나 → {kind, label, env, code, steps, auto}."""
    users = users or {}
    did = d.id
    if d.portal == "kosis" and (ids := _kosis_ids(d.url)):
        org, tbl = ids
        prd = PRD.get(d.time, "Y")
        return {
            "kind": "adapter",
            "label": "자동 수집 · KOSIS",
            "env": "KOSIS_API_KEY",
            "auto": True,
            "code": f"python -m core.data fetch {did} --start 2015 --end 2024 -o data/raw/{did}.csv",
            "python": (
                "from core.adapters.kosis import KosisAdapter\n"
                f'df = KosisAdapter().fetch(orgId="{org}", tblId="{tbl}", prdSe="{prd}", startPrdDe="2015", endPrdDe="2024")'
            ),
            "steps": [KEY_HELP["KOSIS_API_KEY"], ".env 에 KOSIS_API_KEY=... (커밋 금지)"],
        }
    if did in MOLIT:
        return {
            "kind": "adapter",
            "label": "자동 수집 · 국토부 실거래가",
            "env": "DATA_GO_KR_API_KEY",
            "auto": True,
            "code": f"python -m core.data fetch {did} --start 2024-01 --end 2024-12 -o data/raw/apt_trades.csv",
            "python": (
                "from core.adapters.molit import MolitAptTradeAdapter\n"
                'df = MolitAptTradeAdapter().fetch(start="2024-01", end="2024-12")  # 기본: 서울 25개 구'
            ),
            "steps": [KEY_HELP["DATA_GO_KR_API_KEY"], ".env 에 DATA_GO_KR_API_KEY=... (커밋 금지)"],
        }
    if did == "OA-12914":
        return {
            "kind": "adapter",
            "label": "자동 수집 · 서울 지하철",
            "env": None,
            "auto": True,
            "code": f"python -m core.data fetch {did} --start 2024-01 --end 2024-12 -o data/raw/subway.csv",
            "python": (
                "from core.adapters.seoul_subway import SeoulSubwayDailyAdapter\n"
                'df = SeoulSubwayDailyAdapter().fetch(start="2024-01", end="2024-12", cache_dir="data/raw/subway")'
            ),
            "steps": ["키 필요 없음 — 월별 파일을 내려받아 합칩니다"],
        }
    if users.get(did):
        case = users[did][0]
        return {
            "kind": "case",
            "label": f"참여자 수집 코드 · {case}",
            "env": None,
            "auto": False,
            "code": f"cp cases/{case}/fetch.py cases/<내ID>-<주제>/fetch.py   # 이 데이터를 실제로 받아 본 코드",
            "python": f"# cases/{case}/fetch.py 를 열어 이 데이터를 받는 부분을 가져다 쓰세요",
            "steps": [f"cases/{case}/fetch.py 와 plan.yaml 의 data_sources 를 보세요", d.url],
        }
    if d.access == "open_api":
        env = "DATA_GO_KR_API_KEY" if d.portal == "data.go.kr" else None
        return {
            "kind": "api_key",
            "label": "API 키 필요",
            "env": env,
            "auto": False,
            "code": f"# {d.url} 의 '요청주소'와 '요청변수'로 호출 — 키는 os.environ['{env or 'API_KEY'}']",
            "python": (
                "import os, requests\n"
                f"r = requests.get('<요청주소>', params={{'serviceKey': os.environ['{env or 'API_KEY'}'], 'type': 'json'}})"
            ),
            "steps": [KEY_HELP.get(env or "", f"{d.url} 에서 활용신청"), f"승인: {d.approval}"],
        }
    if d.access == "file":
        return {
            "kind": "file",
            "label": "파일 내려받기",
            "env": None,
            "auto": False,
            "code": f"# {d.url} 에서 내려받아 data/raw/ 에 두고: pd.read_csv('data/raw/<파일>', dtype=str)",
            "python": "import pandas as pd\ndf = pd.read_csv('data/raw/<파일>.csv', dtype=str)  # 코드 열은 문자로",
            "steps": [d.url, "받은 날짜와 파일명을 fetch.py 주석에 기록"],
        }
    return {
        "kind": "manual",
        "label": "웹 조회·신청",
        "env": None,
        "auto": False,
        "code": f"# {d.url} 에서 조회·내려받기 (자동 수집 불가)",
        "python": "",
        "steps": [d.url, d.approval],
    }


def fetch(d, start: str | None = None, end: str | None = None):
    """adapter 연결만 실제로 받는다. 나머지는 ValueError 로 안내."""
    c = connector(d)
    if not c["auto"]:
        raise ValueError(
            f"{d.id}: 자동 수집기가 없습니다 ({c['label']}). python -m core.data show {d.id}"
        )
    if d.portal == "kosis":
        from core.adapters.kosis import KosisAdapter

        org, tbl = _kosis_ids(d.url)
        return KosisAdapter().fetch(
            orgId=org, tblId=tbl, prdSe=PRD.get(d.time, "Y"), startPrdDe=start, endPrdDe=end
        )
    if d.id in MOLIT:
        from core.adapters.molit import MolitAptTradeAdapter

        return MolitAptTradeAdapter().fetch(start=start or "2024-01", end=end or "2024-12")
    if d.id == "OA-12914":
        from core.adapters.seoul_subway import SeoulSubwayDailyAdapter

        return SeoulSubwayDailyAdapter().fetch(start=start or "2024-01", end=end or "2024-12")
    raise ValueError(d.id)


def _show(d, users) -> str:
    c = connector(d, users)
    lines = [
        f"{d.id} · {d.name}",
        f"  연결: {c['label']}" + (f" (환경변수 {c['env']})" if c["env"] else ""),
    ]
    lines += [f"  - {s}" for s in c["steps"] if s]
    lines.append(f"  $ {c['code']}")
    if c["python"]:
        lines += ["  " + ln for ln in c["python"].splitlines()]
    return "\n".join(lines)


def main(argv=None) -> int:
    from core.discovery.links import dataset_users
    from core.discovery.ontology import load_datasets, load_issues

    ap = argparse.ArgumentParser(description="카탈로그 데이터 연동")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show")
    s.add_argument("id")
    i = sub.add_parser("issue")
    i.add_argument("id")
    f = sub.add_parser("fetch")
    f.add_argument("id")
    f.add_argument("--start")
    f.add_argument("--end")
    f.add_argument("-o", "--out")
    sub.add_parser("list")
    a = ap.parse_args(argv)
    ds = {d.id: d for d in load_datasets()}
    users = dataset_users(list(ds.values()))
    if a.cmd == "list":
        for d in ds.values():
            print(f"{d.id:<18} {connector(d, users)['label']:<28} {d.name}")
        return 0
    if a.cmd == "show":
        if a.id not in ds:
            print(f"카탈로그에 없는 id: {a.id}", file=sys.stderr)
            return 1
        print(_show(ds[a.id], users))
        return 0
    if a.cmd == "issue":
        iss = {x.id: x for x in load_issues()}.get(a.id)
        if not iss:
            print(f"issues.yaml 에 없는 이슈: {a.id}", file=sys.stderr)
            return 1
        print(f"[{iss.name}] 시행 {iss.effective} · 근거 {iss.source}")
        for did in iss.datasets:
            print(_show(ds[did], users) if did in ds else f"{did} · 카탈로그에 없음")
        return 0
    d = ds.get(a.id)
    if d is None:
        print(f"카탈로그에 없는 id: {a.id}", file=sys.stderr)
        return 1
    df = fetch(d, a.start, a.end)
    out = Path(a.out or f"data/raw/{re.sub(r'[^A-Za-z0-9_-]', '_', d.id)}.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"{len(df)}행 → {out}  (받은 날 {date.today()}, 출처 {d.url}, 이용 조건 {d.license})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
