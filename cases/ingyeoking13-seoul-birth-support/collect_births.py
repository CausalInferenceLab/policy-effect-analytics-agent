"""행정안전부 공개 CSV → 서울 자치구별 월별 출생등록. 인증키 불필요."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests

SOURCE_URL = "https://jumin.mois.go.kr/etcStatBirth.do"
DOWNLOAD_URL = "https://jumin.mois.go.kr/downloadCsvEtc.do"
DISTRICT_CODES = dict(
    zip(
        (
            "11110 11140 11170 11200 11215 11230 11260 11290 11305 11320 11350 "
            "11380 11410 11440 11470 11500 11530 11545 11560 11590 11620 11650 "
            "11680 11710 11740"
        ).split(),
        (
            "종로구 중구 용산구 성동구 광진구 동대문구 중랑구 성북구 강북구 도봉구 노원구 "
            "은평구 서대문구 마포구 양천구 강서구 구로구 금천구 영등포구 동작구 관악구 서초구 "
            "강남구 송파구 강동구"
        ).split(),
        strict=True,
    )
)


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def parse_birth_csv(content: bytes, year: int) -> pd.DataFrame:
    # 실제 응답은 Content-Type의 UTF-8 표기와 달리 CP949다.
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("cp949")
    rows = list(csv.reader(io.StringIO(text)))
    expected = ["행정구역"] + [
        f"{year}년{month:02}월_{sex}"
        for month in range(1, 13)
        for sex in ("남자인구수", "여자인구수", "계")
    ]
    if not rows or rows[0] != expected or len(rows) != 27:
        raise ValueError(f"{year}: 출생 CSV 헤더/26개 지역 행 불일치")
    all_counts = {}
    records = []
    for row in rows[1:]:
        if len(row) != len(expected):
            raise ValueError(f"{year}: 출생 CSV 열 수 불일치")
        match = re.fullmatch(r"서울특별시\s*(.*?)\s*\((\d{5})00000\)", row[0])
        if not match:
            raise ValueError(f"{year}: 서울시·자치구 합계 외 행 발견")
        district, code = match.groups()
        if (code == "11000" and district) or (
            code != "11000" and DISTRICT_CODES.get(code) != district
        ):
            raise ValueError(f"{year}: 행정구역명·코드 불일치")
        if code in all_counts:
            raise ValueError(f"{year}: 지역 중복")
        if any(not re.fullmatch(r"\d+|\d{1,3}(?:,\d{3})+", cell) for cell in row[1:]):
            raise ValueError(f"{year}: 결측·비공개·비정수 건수")
        values = [int(cell.replace(",", "")) for cell in row[1:]]
        totals = []
        for month in range(1, 13):
            male, female, total = values[(month - 1) * 3 : month * 3]
            if male + female != total:
                raise ValueError(f"{year}: 남녀 합계 불일치")
            totals.append(total)
            if code != "11000":
                records.append((district, year, month, total))
        all_counts[code] = totals
    if set(all_counts) != {"11000", *DISTRICT_CODES}:
        raise ValueError(f"{year}: 서울 25개 구 불완전")
    for month in range(12):
        if sum(all_counts[code][month] for code in DISTRICT_CODES) != all_counts["11000"][month]:
            raise ValueError(f"{year}: 25개 구 합과 서울시 총계 불일치")
    return pd.DataFrame(records, columns=["district", "year", "month", "births"])


def collect_births(case_dir: Path, *, offline: bool = False) -> dict:
    target = case_dir / "data" / "raw" / "births"
    target.mkdir(parents=True, exist_ok=True)
    frames, provenance = [], []
    with requests.Session() as session:
        for year in range(2018, 2025):
            path = target / f"mois-{year}.csv"
            meta_path = path.with_suffix(".source.json")
            params = {"searchYearMonth": "month", "xlsStats": "1"}
            form = {
                "sltOrgType": "2",
                "sltOrgLvl1": "1100000000",
                "sltOrgLvl2": "A",
                "searchYearStart": str(year),
                "searchMonthStart": "01",
                "searchYearEnd": str(year),
                "searchMonthEnd": "12",
                "sltOrderType": "1",
                "sltOrderValue": "ASC",
                "category": "birth",
                "state": "1",
            }
            if path.exists() and meta_path.exists():
                content = path.read_bytes()
                meta = json.loads(meta_path.read_text())
                if (
                    meta.get("sha256") != digest(content)
                    or meta.get("request") != {"params": params, "form": form}
                    or meta.get("download_url") != DOWNLOAD_URL
                ):
                    raise ValueError(f"{year}: 저장된 출생 원본/요청 기록 불일치")
            else:
                if offline:
                    raise ValueError(f"{year}: 오프라인 재현용 출생 원본/출처 기록 없음")
                try:
                    response = session.post(
                        DOWNLOAD_URL, params=params, data=form, timeout=(10, 60)
                    )
                    response.raise_for_status()
                except requests.RequestException as exc:
                    raise ValueError(f"{year}: 행정안전부 출생 CSV 다운로드 실패") from exc
                content = response.content
                # 오류 HTML·부분 자료는 완성 원본으로 저장하지 않는다.
                parse_birth_csv(content, year)
                meta = {
                    "url": SOURCE_URL,
                    "download_url": DOWNLOAD_URL,
                    "license": "other",
                    "license_note": "공공데이터포털 3033249: 이용허락범위 제한 없음",
                    "retrieved_at": datetime.now(UTC).isoformat(),
                    "request": {"params": params, "form": form},
                    "sha256": digest(content),
                }
                path.write_bytes(content)
                meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))
            frames.append(parse_birth_csv(content, year))
            provenance.append({"file": str(path.relative_to(case_dir)), **meta})
    births = pd.concat(frames, ignore_index=True).sort_values(["district", "year", "month"])
    path = target.parent / "births.csv"
    temp = path.with_suffix(".csv.tmp")
    births.to_csv(temp, index=False)
    temp.replace(path)
    meta = {
        "url": SOURCE_URL,
        "license": "other",
        "retrieved_at": max(item["retrieved_at"] for item in provenance),
        "sha256": digest(path.read_bytes()),
        "preparation": (
            "공식 폼 category=birth, 서울시·시군구, 각 연도 1~12월 CSV. "
            "CP949 디코딩, 자치구 코드·헤더·남녀 합·서울 총계=25개 구 합 검증 후 "
            "서울 총계와 성별 열 제외, 월별 계만 district/year/month/births로 변환."
        ),
        "rows": len(births),
        "files": provenance,
    }
    path.with_suffix(".source.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    return meta
