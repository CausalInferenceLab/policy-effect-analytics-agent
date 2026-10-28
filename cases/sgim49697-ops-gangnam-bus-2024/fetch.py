"""월별 자료를 수집하고 검증된 설정으로 정책 패널 또는 ML 시간 자료를 만든다."""

from __future__ import annotations

import argparse

import pandas as pd
from gangnam.common import (
    CASE,
    digest,
    holiday_dates,
    read_yaml,
    real_data_gate,
    sha256,
    write_json,
)
from gangnam.policy import build_panel
from gangnam.topis import check_metadata, download, list_months, parse_month, read_hourly, session


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scope", choices=["policy", "ml"], default="policy")
    p.add_argument("--metadata-only", action="store_true", help="속도값을 해석하지 않고 원본·메타데이터만 보관")
    args = p.parse_args()
    cfg, contract = read_yaml("corridors.yaml"), read_yaml("data_contract.yaml")
    if not args.metadata_only:
        real_data_gate()
    first = "2024-04" if args.scope == "policy" else "2023-01"
    months = pd.period_range(first, "2024-08", freq="M")
    raw, processed = CASE / "data/raw", CASE / "data/processed"
    processed.mkdir(parents=True, exist_ok=True)
    summaries, catalog = [], {}
    rules = None if args.metadata_only else contract["checks"]["missing_values"]["value"]
    with session() as s:
        for month in months:
            if month.year not in catalog:
                catalog[month.year] = list_months(s, month.year)
            if month.month not in catalog[month.year]:
                raise ValueError(f"TOPIS 목록에 {month} 파일이 없습니다")
            path, manifest = download(s, catalog[month.year][month.month], str(month), raw)
            frame, meta = parse_month(path, str(month), cfg["candidate_roads"], rules)
            meta["source_sha256"] = manifest["sha256"]
            write_json(CASE / f"data/metadata/{month}.json", meta)
            summaries.append(meta)
            if not args.metadata_only:
                check_metadata(summaries, contract.get("metadata_policy"))
                frame = frame[~frame.link_id.isin(contract.get("metadata_policy", {}).get("excluded_links", []))]
                target = processed / f"{month}.parquet"
                temp = target.with_suffix(".parquet.tmp")
                frame.to_parquet(temp, index=False)
                temp.replace(target)
                write_json(processed / f"{month}.json", {"rows": len(frame), "source_sha256": manifest["sha256"],
                           "contract_hash": digest(contract), "road_selection_hash": digest(cfg["candidate_roads"]),
                           "parquet_sha256": sha256(target)})
            print(f"{month}: 원본 해시·헤더 확인, 선택 도로 메타데이터 {len(meta['metadata'])}개", flush=True)
    if args.metadata_only:
        print("메타데이터 수집 완료. 속도 수치·효과·모델 점수는 계산하지 않았습니다.")
        return
    check_metadata(summaries, contract.get("metadata_policy"))
    if args.scope == "policy":
        days = holiday_dates(cfg["pre"][0], cfg["post"][1])
        panel, quality = build_panel(read_hourly(processed, verify=True), cfg, days)
        write_json(CASE / "data/policy_quality.json", quality)
        target = CASE / ("data/panel.csv" if quality["comparative"] else "data/descriptive.csv")
        panel.to_csv(target, index=False)
        if not quality["comparative"]:
            (CASE / "data/panel.csv").unlink(missing_ok=True)
            print("비교 분석 기준 미달: 기술통계용 data/descriptive.csv만 작성했습니다.")


if __name__ == "__main__":
    main()
