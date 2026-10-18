"""검증된 정책 검토표와 공개 통계 CSV로 분석 패널을 만든다.

현재는 수동 다운로드 입력 방식이다. 자동 다운로드와 실데이터 재현은 미완료다.
입력 형식·출처 기록: collection-plan.md. 미확인 정책을 0원으로 대체하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DISTRICTS = tuple(
    "종로구 중구 용산구 성동구 광진구 동대문구 중랑구 성북구 강북구 도봉구 노원구 "
    "은평구 서대문구 마포구 양천구 강서구 구로구 금천구 영등포구 동작구 관악구 서초구 "
    "강남구 송파구 강동구".split()
)
YEARS = tuple(range(2018, 2025))


def policy_groups(review: list[dict]) -> tuple[dict[str, int], dict[str, str]]:
    """결과값을 읽기 전에 25개 구의 포함·제외를 확정한다."""
    if not isinstance(review, list) or any(not isinstance(row, dict) for row in review):
        raise ValueError("policy_review.yaml은 구별 검토 기록의 목록이어야 합니다")
    names = [row.get("district") for row in review]
    if len(names) != 25 or set(names) != set(DISTRICTS):
        raise ValueError("정책 검토표에 서울 25개 구가 중복 없이 모두 있어야 합니다")
    groups, excluded = {}, {}
    for row in review:
        district, status = row["district"], row.get("status")
        if status == "excluded":
            if not str(row.get("reason") or "").strip():
                raise ValueError(f"{district}: 제외 사유가 필요합니다")
            excluded[district] = row["reason"]
            continue
        if status != "verified":
            raise ValueError(
                f"{district}: 정책 이력이 미확인입니다. 결과 조회 전 검증·제외를 확정하세요"
            )
        if row.get("history_start") != "2022-01-01" or row.get("history_end") != "2024-12-31":
            raise ValueError(f"{district}: 2022~2024년 전체 정책 이력 검증이 필요합니다")
        if not str(row.get("evidence_note") or "").strip():
            raise ValueError(f"{district}: 기간·금액·조건을 확인한 근거 설명이 필요합니다")
        sources = row.get("sources")
        if not isinstance(sources, list) or not sources:
            raise ValueError(f"{district}: 공식 출처와 이용 조건이 필요합니다")
        for source in sources:
            if not isinstance(source, dict) or not all(
                str(source.get(key) or "").strip() for key in ("url", "license", "checked_on")
            ):
                raise ValueError(f"{district}: 각 출처의 url, license, checked_on을 기록하세요")
        amounts = row.get("first_child_won", {})
        values = [amounts.get(str(year)) for year in (2022, 2023, 2024)]
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError(f"{district}: 연도별 첫째아 금액을 확인된 0 이상의 정수로 기록하세요")
        if row.get("conditions_unchanged") is not True:
            raise ValueError(f"{district}: 지급조건 변경 여부를 확인하고 변경된 경우 제외하세요")
        before, after, last = values
        if before == after == last and row.get("change_date") is None:
            groups[district] = 0
        elif before < after == last and row.get("change_date") == "2023-01-01":
            groups[district] = 1
        else:
            raise ValueError(
                f"{district}: 사전 계획과 다른 변경입니다. 근거를 적고 excluded로 분류하세요"
            )
    if set(groups.values()) != {0, 1}:
        raise ValueError("검증된 증액 구와 유지 구가 모두 필요합니다")
    return groups, excluded


def build_panel(births: pd.DataFrame, groups: dict[str, int]) -> pd.DataFrame:
    """구×월 합계만 받는다. 월 누락·중복·비공개 값으로 연간 합계를 만들지 않는다."""
    columns = ["district", "year", "month", "births"]
    if not set(columns).issubset(births.columns):
        raise ValueError(f"출생 CSV 필수 열: {', '.join(columns)}")
    df = births[columns].copy()
    if not df["district"].isin(DISTRICTS).all():
        raise ValueError(
            "자치구 합계 행만 입력하세요. 서울시 총계·동별 행·알 수 없는 구는 허용하지 않습니다"
        )
    for col in ("year", "month", "births"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
        values = df[col].to_numpy(dtype=float)
        if not np.isfinite(values).all() or (values != np.floor(values)).any():
            raise ValueError(f"{col}: 결측·비공개·비수치·소수 값은 허용하지 않습니다")
    if not df["year"].isin(YEARS).all() or not df["month"].between(1, 12).all():
        raise ValueError("분석 기간은 2018~2024년, 월은 1~12입니다")
    if (df["births"] < 0).any():
        raise ValueError("출생등록 건수는 음수일 수 없습니다")
    keys = ["district", "year", "month"]
    if df.duplicated(keys).any():
        raise ValueError(
            "자치구×연도×월 중복: 남녀 합계와 성별·동별 행의 중복 합산 여부를 확인하세요"
        )
    expected = pd.MultiIndex.from_product([DISTRICTS, YEARS, range(1, 13)], names=keys)
    present = pd.MultiIndex.from_frame(df[keys])
    if not expected.difference(present).empty:
        raise ValueError(
            "25개 구 × 7년 × 12개월의 완전한 자료가 필요합니다. 누락을 0으로 채우지 마세요"
        )
    panel = df.groupby(["district", "year"], as_index=False)["births"].sum()
    if (panel["births"] <= 0).any():
        raise ValueError("연간 출생등록이 0인 구가 있어 로그를 계산할 수 없습니다")
    panel = panel[panel["district"].isin(groups)].copy()
    panel["treated"] = panel["district"].map(groups).astype(int)
    panel["year"] = panel["year"].astype(int)
    panel["log_births"] = np.log(panel["births"])
    return panel.sort_values(["district", "year"]).reset_index(drop=True)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(case_dir: Path = HERE) -> dict:
    plan_path = case_dir / "plan.yaml"
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(plan_path)],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    clean = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", str(plan_path)],
        cwd=ROOT,
        check=False,
    )
    if tracked.returncode or clean.returncode:
        raise ValueError("plan.yaml을 결과 조회 전에 먼저 커밋하세요")
    plan = yaml.safe_load(plan_path.read_text())
    raw = case_dir / "data" / "raw"
    review_path = raw / "policy_review.yaml"
    if not review_path.exists():
        raise ValueError(
            "data/raw/policy_review.yaml이 없습니다. collection-plan.md에 따라 25개 구를 먼저 검증하세요"
        )
    review = yaml.safe_load(review_path.read_text())
    groups, excluded = policy_groups(review)
    declared = {source["url"]: source["license"] for source in plan["data_sources"]}
    for row in review:
        if row.get("status") == "verified":
            for source in row["sources"]:
                if declared.get(source["url"]) != source["license"]:
                    raise ValueError(
                        "정책 근거의 URL·라이선스를 plan.yaml data_sources에 추가하고 먼저 커밋하세요"
                    )
    births_path, source_path = raw / "births.csv", raw / "births.source.json"
    if not births_path.exists() or not source_path.exists():
        raise ValueError(
            "공식 출생 CSV와 출처 기록이 필요합니다: data/raw/births.csv, births.source.json"
        )
    source = json.loads(source_path.read_text())
    primary = plan["data_sources"][0]
    if source.get("url") != primary["url"] or source.get("license") != primary["license"]:
        raise ValueError("출생 자료의 출처·라이선스가 사전 계획과 다릅니다")
    if source.get("sha256") != sha256(births_path):
        raise ValueError("출생 CSV의 해시가 출처 기록과 다릅니다")
    if (
        not str(source.get("retrieved_at") or "").strip()
        or not str(source.get("preparation") or "").strip()
    ):
        raise ValueError("출생 자료의 다운로드 일시와 열 변환·추출 절차를 기록하세요")
    panel = build_panel(pd.read_csv(births_path), groups)
    meta = {
        "synthetic_data": False,
        "plan_sha256": sha256(plan_path),
        "policy_review_sha256": sha256(review_path),
        "births_sha256": sha256(births_path),
        "source": source,
        "groups": groups,
        "excluded": excluded,
        "rows": len(panel),
        "units": len(groups),
    }
    target = case_dir / "data" / "panel.csv"
    temp = target.with_suffix(".csv.tmp")
    panel.to_csv(temp, index=False)
    temp.replace(target)
    target.with_suffix(".source.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    return meta


def main() -> int:
    try:
        meta = prepare()
    except (ValueError, OSError, yaml.YAMLError) as exc:
        print(f"[중단] {exc}", file=sys.stderr)
        return 1
    print(f"[완료] 검증된 {meta['units']}개 구, {meta['rows']}행 → data/panel.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
