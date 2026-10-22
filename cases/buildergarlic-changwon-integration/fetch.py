"""② 수집 — KOSIS OpenAPI 세 통계표를 받아 '통합 경계로 재구성한 기초 시 × 연도' 패널을 만듭니다.

    python fetch.py                 # KOSIS_API_KEY 필요(.env, 무료 발급). 원자료는 data/raw/ 에 저장(커밋 안 됨)
    python fetch.py --simulate      # 키 없이 파이프라인만 점검하는 합성 패널 — 실데이터 아님, 결과 해석 금지
    python fetch.py --list-fiscal   # 재정자립도 통계표 ID 후보를 KOSIS 통계표 검색으로 보여줌

한 행 = 기초 시 × 연도(1998~2023, 2010 제외). plan.yaml 의 열(region_id, year, treated,
log_population, net_migration_rate, fiscal_independence)을 만듭니다.

행정경계 변경 처리(이 케이스의 핵심)
- 통합 전(≤2009) 마산시·창원시·진해시 값을 합산해 통합 창원시와 같은 경계로 맞춥니다.
  인구·전입·전출은 합계, 재정자립도(비율)는 인구 가중 평균(근사치, discussion.md 에 한계 기록).
- 2010년은 7월에 통합된 전환연도라 모든 단위에서 제외합니다(균형 패널 유지).
- 1998~2023 사이 통합·분리·승격이 있었던 시와 창원과 접한 김해·밀양은 대조군에서 뺍니다(DONOR_CITIES).

주의: data/ 아래 파일은 git 에 올라가지 않습니다. KOSIS 가공본은 재배포하지 않고 각자 받습니다.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))

from core.adapters.base import MissingAPIKey  # noqa: E402
from core.adapters.kosis import KosisAdapter  # noqa: E402

OUT = HERE / "data" / "panel.csv"
RAW = HERE / "data" / "raw"

START, END = 1998, 2023
MERGE_YEAR = 2010  # 2010-07-01 통합 → 반년만 통합된 전환연도, 패널에서 제외
TREAT_TIME = 2011  # 첫 완전 사후연도 (plan.yaml treatment.treat_time 과 같아야 함)
MERGED = "창원시"
PRE_MERGER = ("마산시", "창원시", "진해시")  # 통합 전 3개 시 → 합산

# KOSIS 통계표 (plan.yaml data_sources 와 같아야 함; 테스트가 확인)
POP_TBL = "DT_1B040A3"  # 행정구역(시군구)별 성별 인구수 — 총인구수 T20, 1992~
MIG_TBL = "DT_1B26001_A01"  # 시군구별 이동자수 — 총전입 T10, 총전출 T20
FIS_TBL = "DT_1YL20921"  # e-지방지표 재정자립도(시도/시/군/구) — ID 미확인: 오류 나면 --list-fiscal

# 대조군: 1998~2023 사이 행정구역 통합·분리·승격이 없었던 기초 시 62곳.
# 제외(이유): 청주(2014 청원 통합)·공주(2012 세종 분할)·논산·계룡(2003 분리)·제주·서귀포(2006 군 통합)·
#   화성·광주·양주·포천(2001~03 군→시)·당진(2012)·여주(2013)·울산(1997 광역시)·세종(2012)·
#   김해·밀양(창원과 접함 → 파급 오염 우려).
DONOR_CITIES = (
    # 경기 23
    "수원시", "성남시", "의정부시", "안양시", "부천시", "광명시", "평택시", "동두천시", "안산시",
    "고양시", "과천시", "구리시", "남양주시", "오산시", "시흥시", "군포시", "의왕시", "하남시",
    "용인시", "파주시", "이천시", "안성시", "김포시",
    # 강원 7
    "춘천시", "원주시", "강릉시", "동해시", "태백시", "속초시", "삼척시",
    # 충북 2 · 충남 4
    "충주시", "제천시", "천안시", "보령시", "아산시", "서산시",
    # 전북 6 · 전남 5
    "전주시", "군산시", "익산시", "정읍시", "남원시", "김제시",
    "목포시", "여수시", "순천시", "나주시", "광양시",
    # 경북 10 · 경남 5
    "포항시", "경주시", "김천시", "안동시", "구미시", "영주시", "영천시", "상주시", "문경시", "경산시",
    "진주시", "통영시", "사천시", "거제시", "양산시",
)  # fmt: skip

YEARS = tuple(y for y in range(START, END + 1) if y != MERGE_YEAR)
UNITS = (MERGED, *DONOR_CITIES)


# ── 순수 함수 (테스트 대상) ───────────────────────────────────────────────────────────────────
def city_rows(long: pd.DataFrame) -> pd.DataFrame:
    """KOSIS 롱포맷(region_code, region, item, period, value)에서 기초자치단체 행만 남긴다.

    코드가 5자리이고 끝자리가 0 인 행 = 시·군·자치구 (일반구 48121 의창구 같은 행과 시도·전국은 제외).
    지역 이름은 마지막 어절만 쓴다('경상남도 창원시' → '창원시').
    """
    d = long.copy()
    code = d["region_code"].astype(str).str.strip()
    keep = code.str.fullmatch(r"\d{5}").fillna(False) & code.str.endswith("0")
    d = d.loc[keep].copy()
    d["region"] = d["region"].astype(str).str.strip().str.split().str[-1]
    d["year"] = pd.to_numeric(d["period"].astype(str).str[:4], errors="coerce")
    d = d.dropna(subset=["year"])
    d["year"] = d["year"].astype(int)
    d["value"] = pd.to_numeric(d["value"], errors="coerce")
    return d[["region", "year", "item", "value"]]


def pick_item(d: pd.DataFrame, keyword: str, exclude: str | None = None) -> pd.DataFrame:
    """항목 이름에 keyword 가 들어간 행. 후보가 여럿이면 이름이 가장 짧은 항목 하나."""
    items = [i for i in d["item"].astype(str).unique() if keyword in i]
    if exclude:
        items = [i for i in items if exclude not in i] or items
    if not items:
        raise ValueError(
            f"'{keyword}' 항목이 없습니다. 있는 항목: {sorted(d['item'].astype(str).unique())}"
        )
    chosen = min(items, key=len)
    return d[d["item"] == chosen].drop(columns="item").assign(item=chosen)


def reconstruct(
    d: pd.DataFrame, how: str = "sum", weights: pd.DataFrame | None = None
) -> pd.DataFrame:
    """region×year×value → 통합 경계 재구성 (region, year, value).

    - 통합 전(year < MERGE_YEAR): 마산·창원·진해를 합산(how='sum') 또는 가중 평균(how='wmean',
      weights = region×year×value 인구표)해 '창원시' 한 행으로.
    - MERGE_YEAR 는 전체 제외. 통합 후에 마산시·진해시 값이 남아 있으면 오류(이중 계산 방지).
    - 대조군은 DONOR_CITIES 만 남긴다.
    """
    x = d[["region", "year", "value"]].copy()
    x = x[x["region"].isin(PRE_MERGER) | x["region"].isin(DONOR_CITIES)]
    x = x[x["year"] != MERGE_YEAR]
    pre = x["year"] < MERGE_YEAR
    old = x[pre & x["region"].isin(PRE_MERGER)].dropna(subset=["value"])
    for y in sorted(x.loc[pre, "year"].unique()):
        have = set(old.loc[old["year"] == y, "region"])
        if have != set(PRE_MERGER):
            raise ValueError(
                f"{y}년 통합 전 3개 시 자료가 빠졌습니다 (없음: {sorted(set(PRE_MERGER) - have)}). "
                "부분 합계로 대체하지 않습니다."
            )
    late = x[~pre & x["region"].isin(("마산시", "진해시"))].dropna(subset=["value"])
    if len(late):
        raise ValueError(
            f"통합 후에도 마산시·진해시 값이 있습니다: {sorted(late['year'].unique())}"
        )
    if how == "sum":
        agg = old.groupby("year", as_index=False)["value"].sum()
    elif how == "wmean":
        if weights is None:
            raise ValueError("how='wmean' 은 weights(인구표)가 필요합니다")
        w = weights[["region", "year", "value"]].rename(columns={"value": "w"})
        m = old.merge(w, on=["region", "year"], how="left")
        if m["w"].isna().any():
            raise ValueError("가중 평균용 인구가 없는 연도·시가 있습니다")
        agg = (
            m.assign(vw=m["value"] * m["w"])
            .groupby("year")
            .apply(lambda g: g["vw"].sum() / g["w"].sum(), include_groups=False)
            .rename("value")
            .reset_index()
        )
    else:
        raise ValueError(f"알 수 없는 how={how}")
    agg["region"] = MERGED
    rest = x[~(pre & x["region"].isin(PRE_MERGER)) & ~x["region"].isin(("마산시", "진해시"))]
    return (
        pd.concat([rest, agg[["region", "year", "value"]]], ignore_index=True)
        .sort_values(["region", "year"])
        .reset_index(drop=True)
    )


def assemble(pop: pd.DataFrame, mig: pd.DataFrame, fis: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """세 KOSIS 롱포맷 → 분석 패널. 반환: (panel, 선택한 항목 이름)."""
    p = pick_item(city_rows(pop), "인구")
    m = city_rows(mig)
    mi, mo = pick_item(m, "전입"), pick_item(m, "전출")
    f = pick_item(city_rows(fis), "재정자립도")
    chosen = {
        "population": p["item"].iloc[0],
        "in_moves": mi["item"].iloc[0],
        "out_moves": mo["item"].iloc[0],
        "fiscal": f["item"].iloc[0],
    }
    pop_r = reconstruct(p, "sum")
    parts = {
        "population": pop_r,
        "in_moves": reconstruct(mi, "sum"),
        "out_moves": reconstruct(mo, "sum"),
        "fiscal_independence": reconstruct(f, "wmean", weights=p),
    }
    panel = None
    for col, part in parts.items():
        part = part.rename(columns={"value": col})
        panel = part if panel is None else panel.merge(part, on=["region", "year"], how="outer")
    return finalize(panel), chosen


def finalize(panel: pd.DataFrame) -> pd.DataFrame:
    """결과 열 계산 + 균형 패널 검증. 결측은 채우지 않고 멈춘다."""
    d = panel.copy()
    d = d[d["region"].isin(UNITS) & d["year"].isin(YEARS)]
    need = ["population", "in_moves", "out_moves", "fiscal_independence"]
    miss = d[d[need].isna().any(axis=1)]
    if len(miss):
        ex = miss[["region", "year"]].head(8).to_dict("records")
        raise ValueError(f"결측 {len(miss)}행 — 0 으로 채우지 않습니다. 예: {ex}")
    expected = pd.MultiIndex.from_product([UNITS, YEARS], names=["region", "year"])
    present = pd.MultiIndex.from_frame(d[["region", "year"]])
    gap = expected.difference(present)
    if len(gap):
        raise ValueError(
            f"{len(UNITS)}개 시 × {len(YEARS)}년 균형 패널이 아닙니다. 빠진 예: {list(gap[:8])}. "
            "이름이 다르면 DONOR_CITIES 와 KOSIS 지역명을 맞추세요."
        )
    if d.duplicated(["region", "year"]).any():
        raise ValueError("시×연도 중복 행이 있습니다")
    if (d["population"] <= 0).any():
        raise ValueError("인구가 0 이하인 행이 있어 로그를 계산할 수 없습니다")
    d["region_id"] = d["region"]
    d["treated"] = (d["region"] == MERGED).astype(int)
    d["log_population"] = np.log(d["population"])
    d["net_migration_rate"] = (d["in_moves"] - d["out_moves"]) / d["population"] * 1000
    cols = [
        "region_id", "region", "year", "treated", "population", "in_moves", "out_moves",
        "log_population", "net_migration_rate", "fiscal_independence",
    ]  # fmt: skip
    return d[cols].sort_values(["region_id", "year"]).reset_index(drop=True)


# ── 합성 패널 (키 없이 파이프라인 점검용) ───────────────────────────────────────────────────────
def simulate(seed: int = 20100701, effect_log_pop: float = -0.03, effect_fiscal: float = -4.0):
    """실데이터 아님. 단위 고정효과 + 공통 연도 충격 + 단위별 완만한 추세 + 임의 효과.
    효과 크기(effect_*)는 파이프라인이 심은 값을 되찾는지 보기 위한 임의 값이다."""
    rng = np.random.default_rng(seed)
    n = len(UNITS)
    base = rng.normal(np.log(200_000), 0.7, n)
    base[0] = np.log(1_050_000)
    slope = rng.normal(0.003, 0.006, n)
    common = np.cumsum(rng.normal(0.004, 0.004, len(YEARS)))
    fis_base = np.clip(rng.normal(38, 12, n), 10, 80)
    fis_common = np.cumsum(rng.normal(-0.6, 0.5, len(YEARS)))
    rows = []
    for i, u in enumerate(UNITS):
        shock = 0.0
        for j, y in enumerate(YEARS):
            d = int(i == 0 and y >= TREAT_TIME)
            shock = 0.6 * shock + rng.normal(0, 0.006)
            lp = base[i] + slope[i] * (y - START) + common[j] + shock + effect_log_pop * d
            pop = float(np.exp(lp))
            net = (slope[i] + (common[j] - common[j - 1] if j else 0) + shock) * pop
            out = pop * rng.uniform(0.08, 0.14)
            fis = fis_base[i] + fis_common[j] + rng.normal(0, 1.5) + effect_fiscal * d
            fis = float(np.clip(fis, 3, 95))
            rows.append((u, u, y, int(i == 0), round(pop), round(out + net), round(out), fis))
    cols = ["region_id", "region", "year", "treated", "population", "in_moves", "out_moves",
            "fiscal_independence"]  # fmt: skip
    return finalize(pd.DataFrame(rows, columns=cols))


# ── KOSIS 실수집 ───────────────────────────────────────────────────────────────────────────────
def _year_chunks(start: int, end: int, size: int = 6):
    y = start
    while y <= end:
        yield y, min(y + size - 1, end)
        y += size


def fetch_real() -> tuple[pd.DataFrame, dict]:
    plan = yaml.safe_load((HERE / "plan.yaml").read_text(encoding="utf-8"))
    sources = {d["query"]["tblId"]: d for d in plan["data_sources"] if d.get("adapter") == "kosis"}
    for tbl in (POP_TBL, MIG_TBL, FIS_TBL):
        if tbl not in sources:
            raise ValueError(f"plan.yaml data_sources 에 {tbl} 이 없습니다")
    ad = KosisAdapter()
    raw, prov = {}, {}
    for tbl in (POP_TBL, MIG_TBL, FIS_TBL):
        q = dict(sources[tbl]["query"])
        s, e = int(q.pop("startPrdDe")), int(q.pop("endPrdDe"))
        frames = []
        try:
            for a, b in _year_chunks(s, e):
                frames.append(ad.fetch(**q, startPrdDe=str(a), endPrdDe=str(b)))
        except RuntimeError as err:
            hint = (
                " → python fetch.py --list-fiscal 로 통계표 ID 후보를 확인해 FIS_TBL·plan.yaml 을 고치세요"
                if tbl == FIS_TBL
                else ""
            )  # noqa: E501
            raise RuntimeError(f"{tbl} 수집 실패: {err}{hint}") from err
        df = pd.concat(frames, ignore_index=True)
        RAW.mkdir(parents=True, exist_ok=True)
        ad.save(df, RAW / f"{tbl}.csv", sources[tbl]["query"])
        raw[tbl] = df
        prov[tbl] = {
            "rows": int(len(df)),
            "name": sources[tbl]["name"],
            "url": sources[tbl].get("url"),
        }
    panel, chosen = assemble(raw[POP_TBL], raw[MIG_TBL], raw[FIS_TBL])
    meta = {
        "synthetic_data": False,
        "tables": prov,
        "items": chosen,
        "aggregation": "통합 전(≤2009) 마산·창원·진해 합산(재정자립도는 인구 가중 평균), 2010 제외",
        "donor_cities": list(DONOR_CITIES),
    }
    return panel, meta


def list_fiscal_candidates(keyword: str = "재정자립도") -> list[dict]:
    """KOSIS 통계표 검색 API로 후보 통계표를 보여준다 (키 필요)."""
    url = "https://kosis.kr/openapi/statisticsSearch.do"
    r = requests.get(
        url,
        params={
            "method": "getList",
            "apiKey": KosisAdapter().api_key(),
            "format": "json",
            "jsonVD": "Y",
            "searchNm": keyword,
        },
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict):
        raise RuntimeError(f"KOSIS 오류 {data.get('err')}: {data.get('errMsg')}")
    rows = [{k: x.get(k) for k in ("ORG_ID", "TBL_ID", "TBL_NM", "STAT_NM")} for x in data]
    for x in rows:
        print(f"{x['ORG_ID']}\t{x['TBL_ID']}\t{x['TBL_NM']}\t({x['STAT_NM']})")
    return rows


def write(panel: pd.DataFrame, meta: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(OUT, index=False)
    meta = {
        **meta,
        "rows": int(len(panel)),
        "units": int(panel["region_id"].nunique()),
        "years": [int(panel["year"].min()), int(panel["year"].max())],
        "excluded_year": MERGE_YEAR,
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    OUT.with_suffix(".source.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), "utf-8"
    )
    flag = " (합성 — 실데이터 아님)" if meta.get("synthetic_data") else ""
    print(f"[fetch] {len(panel)}행, {meta['units']}개 시 → {OUT.relative_to(HERE)}{flag}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--simulate", action="store_true", help="키 없이 합성 패널 생성(실데이터 아님)")
    ap.add_argument("--list-fiscal", action="store_true", help="재정자립도 통계표 ID 후보 검색")
    a = ap.parse_args(argv)
    if a.list_fiscal:
        list_fiscal_candidates()
        return
    if a.simulate:
        write(
            simulate(),
            {
                "synthetic_data": True,
                "license": "synthetic",
                "note": "fetch.py --simulate 로 만든 합성 패널. 파이프라인 점검용이며 결과를 해석하지 않는다",
            },
        )
        return
    try:
        panel, meta = fetch_real()
    except MissingAPIKey as e:
        sys.exit(
            f"{e}\nKOSIS 공유서비스(https://kosis.kr/openapi)에서 무료 발급 후 .env 의 KOSIS_API_KEY 에 넣으세요. "
            "키 없이 파이프라인만 점검하려면: python fetch.py --simulate (합성 데이터, 결과 해석 금지)"
        )
    write(panel, meta)


if __name__ == "__main__":
    main()
