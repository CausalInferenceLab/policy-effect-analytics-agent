"""매출 취득·진단 및 관측 행 탐색 패널. 전체매출 인과효과와 구분한다."""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import mkdtemp
from zipfile import BadZipFile

import numpy as np
import pandas as pd
import requests
import yaml
from characteristics_files import DOWNLOAD, FILE_SPECS, archive, file_query, inspect_territory
from fetch_characteristics import DISTRICTS, digest, dump, request_artifact, verified_bytes
from sales_panel import INDUSTRIES, build_observed_panels, build_panels

HERE = Path(__file__).resolve().parent
YEARS = (2021, 2022, 2023, 2024)
SALES_PAGE = "https://data.seoul.go.kr/dataList/OA-15572/S/1/datasetView.do"
COLUMNS = {
    "기준_년분기_코드": "period",
    "상권_구분_코드": "area_type",
    "상권_코드": "area_code",
    "서비스_업종_코드": "industry_code",
    "당월_매출_금액": "sales_krw",
}


def selected_districts():
    groups = yaml.safe_load((HERE / "comparison-groups.yaml").read_text())
    names = [*groups["treated"], *groups["controls"]]
    all_names = [*names, *groups["excluded"], *groups["held"]]
    if (
        groups["treated"] != ["동대문구"]
        or len(groups["controls"]) != 20
        or len(groups["excluded"]) != 3
        or len(groups["held"]) != 1
        or len(all_names) != 25
        or len(set(all_names)) != 25
        or set(all_names) != set(DISTRICTS)
    ):
        raise ValueError("사전 고정한 처치1/비교20/제외3/보류1 명단 불일치")
    return names


def download():
    parent = HERE / "data/raw/sales"
    parent.mkdir(parents=True, exist_ok=True)
    folder = Path(mkdtemp(prefix=datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-"), dir=parent))
    with requests.Session() as session:
        for year in [*YEARS, "territory"]:
            spec = (
                FILE_SPECS["territory"]
                if year == "territory"
                else {
                    "id": "OA-15572",
                    "page": SALES_PAGE,
                    "filename": f"서울시{' ' if year == 2024 else '_'}상권분석서비스(추정매출-상권)_{year}년.zip",
                }
            )
            target = folder / str(year)
            target.mkdir()
            record = {
                "artifacts": {},
                "dataset_id": spec["id"],
                "status": "failed",
                "original_filename": spec["filename"],
                "license": "KOGL-1",
            }
            try:
                page = request_artifact(
                    session, target, record, "metadata", spec["page"], {}, "GET"
                )
                if "공공누리 1유형" not in page.decode("utf-8"):
                    raise ValueError("이용 조건 확인 실패")
                raw = request_artifact(
                    session,
                    target,
                    record,
                    "data",
                    DOWNLOAD,
                    file_query(page.decode("utf-8"), spec),
                    extension=".zip",
                )
                with archive(raw) as z:
                    record["members"] = z.namelist()
                record["status"] = "downloaded"
            finally:
                dump(target / "source.json", record)
    print(folder)
    return folder


def read_sales(raw, year):
    """원본 금액은 합계로 확정하지 않고 진단용으로만 읽는다."""
    with archive(raw) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError("연간 ZIP에 CSV 한 개가 필요합니다")
        data = z.read(names[0])
    encoding = "utf-8-sig"
    try:
        text = data.decode(encoding)
    except UnicodeDecodeError:
        encoding = "cp949"
        text = data.decode(encoding)
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    if len(header) != len(set(header)) or not set(COLUMNS) <= set(header):
        raise ValueError("매출 CSV 열 정의 불일치/중복")
    if any(len(row) != len(header) for row in reader):
        raise ValueError("매출 CSV 행 길이 불일치")
    frame = pd.read_csv(
        io.StringIO(text), dtype=str, keep_default_na=False, usecols=list(COLUMNS)
    ).rename(columns=COLUMNS)
    if not frame.period.isin([f"{year}{q}" for q in range(1, 5)]).all():
        raise ValueError("연간 파일의 분기 범위 불일치")
    if set(frame.period) != {f"{year}{q}" for q in range(1, 5)}:
        raise ValueError("연간 파일 분기 누락")
    chosen = frame.loc[frame.area_type.eq("A") & frame.industry_code.isin(INDUSTRIES)].copy()
    if chosen.empty or chosen.area_code.eq("").any():
        raise ValueError("골목상권·4업종 행/코드 누락")
    if chosen.duplicated(["period", "area_code", "industry_code"]).any():
        raise ValueError("분기×상권×업종 중복")
    if not chosen.sales_krw.str.fullmatch(r"[0-9]+").all():
        raise ValueError("빈칸·비공개·음수·비정상 매출; 0으로 대체하지 않습니다")
    chosen["sales_krw"] = chosen.sales_krw.map(int)
    chosen["quarter_idx"] = (year - 2021) * 4 + chosen.period.str[-1].astype(int) - 1
    return chosen, {
        "year": year,
        "rows": len(frame),
        "selected_rows": len(chosen),
        "encoding": encoding,
        "member": names[0],
        "columns": header,
    }


def observation_diagnostics(selected, names):
    """관측 행만의 금액과 관측 집합 변화. 전체 매출 합계·정책 효과가 아니다."""
    rows = []
    for gu in names:
        for industry in INDUSTRIES:
            subset = selected.loc[selected.gu_name.eq(gu) & selected.industry_code.eq(industry)]
            sets = {q: set(subset.loc[subset.quarter_idx.eq(q), "area_code"]) for q in range(16)}
            stable = set.intersection(*sets.values())
            for q in range(16):
                current = subset.loc[subset.quarter_idx.eq(q)]
                previous = sets[q - 1] if q else None
                rows.append(
                    {
                        "gu_name": gu,
                        "industry_code": industry,
                        "quarter_idx": q,
                        "observed_areas": len(sets[q]),
                        "observed_raw_amount_krw": (
                            sum(current.sales_krw.map(int)) if len(current) else None
                        ),
                        "entered_observation": len(sets[q] - previous)
                        if previous is not None
                        else None,
                        "left_observation": len(previous - sets[q])
                        if previous is not None
                        else None,
                        "observed_all_16_quarters": len(stable),
                    }
                )
    result = pd.DataFrame(rows)
    for column in ["observed_raw_amount_krw", "entered_observation", "left_observation"]:
        result[column] = pd.array([row[column] for row in rows], dtype="Int64")
    return result


def audit(snapshot, output, *, observed=False):
    """모든 입력 해시를 검증하고 관측 범위를 기록. 실제 부재와 결측을 구분하지 않는다."""
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "status": "blocked",
        "synthetic_data": False,
        "snapshot": str(snapshot.resolve()),
        "sources": {},
        "files": [],
        "blockers": [],
        "panel_written": False,
        "analysis_ready": False,
        "requirements": {
            "spatial_compatibility": {
                "status": "unresolved",
                "required_evidence": "2021~2024 매출과 영역 ZIP의 경계 적용 기간·코드 대응 근거",
            },
            "absent_rows": {
                "status": "unresolved",
                "required_evidence": "행 생략 기준과 실제 업종 부재·비공개·누락의 구분 근거",
            },
            "amount_period": {
                "status": "partial",
                "evidence": "공식 월평균 설명과 2024년 한 관광특구 네 분기 수치 일치",
                "required_evidence": "2021~2023 적용 범위와 원본 보존·분기 환산 규칙의 검토 기록",
            },
        },
    }
    existing_panel = HERE / "data/panel.csv"
    report["existing_panel"] = existing_panel.exists()
    if existing_panel.exists():
        report["blockers"].append(
            "기존 data/panel.csv 존재: 공통 flow는 이를 재사용하므로 실행 금지; 출처 별도 확인 필요"
        )
    try:
        blobs = {}
        for key in [*(str(y) for y in YEARS), "territory"]:
            folder = snapshot / key
            record = json.loads((folder / "source.json").read_text())
            if record.get("dataset_id") != ("OA-15560" if key == "territory" else "OA-15572"):
                raise ValueError(f"자료원 ID 불일치: {key}")
            if record["status"] != "downloaded":
                raise ValueError(f"다운로드 미완료: {key}")
            verified_bytes(folder, record, "metadata")
            blobs[key] = verified_bytes(folder, record, "data")
            report["sources"][key] = record
        mapping, territory = inspect_territory(blobs["territory"], DISTRICTS)
        report["territory"] = territory
        frames = []
        for year in YEARS:
            frame, info = read_sales(blobs[str(year)], year)
            frames.append(frame)
            report["files"].append(info)
        sales = pd.concat(frames, ignore_index=True)
        sales["gu_name"] = sales.area_code.map(mapping)
        unmatched = sorted(set(sales.loc[sales.gu_name.isna(), "area_code"]))
        report["unmatched_area_codes"] = unmatched
        if unmatched:
            raise ValueError("영역 코드에 연결되지 않는 매출 상권 존재")
        names = selected_districts()
        selected = sales.loc[sales.gu_name.isin(names)].copy()
        # 영역×4업종×16분기는 관측 공백 진단용 격자이며 실제 영업 조합이라는 뜻이 아니다.
        areas = sorted(a for a, gu in mapping.items() if gu in names)
        expected = pd.MultiIndex.from_product(
            [areas, range(16), INDUSTRIES], names=["area_code", "quarter_idx", "industry_code"]
        )
        observed_keys = pd.MultiIndex.from_frame(selected[list(expected.names)])
        absent = expected.difference(observed_keys).to_frame(index=False)
        absent["gu_name"] = absent.area_code.map(mapping)
        absent.to_csv(output / "absent-combinations.csv", index=False)
        coverage = (
            selected.groupby(["gu_name", "quarter_idx", "industry_code"])
            .agg(
                observed_areas=("area_code", "nunique"),
                explicit_zero_rows=("sales_krw", lambda x: int(x.eq(0).sum())),
            )
            .reindex(
                pd.MultiIndex.from_product(
                    [names, range(16), INDUSTRIES],
                    names=["gu_name", "quarter_idx", "industry_code"],
                ),
                fill_value=0,
            )
            .reset_index()
        )
        coverage.to_csv(output / "coverage.csv", index=False)
        observation_diagnostics(selected, names).to_csv(
            output / "observation-diagnostics.csv", index=False
        )
        report.update(
            selected_rows=len(selected),
            selected_areas=len(areas),
            absent_combinations=len(absent),
            empty_district_quarter_industries=int(coverage.observed_areas.eq(0).sum()),
            explicit_zero_rows=int(selected.sales_krw.eq(0).sum()),
            estimation_empty_district_quarter_industries=int(
                (coverage.quarter_idx.ne(12) & coverage.observed_areas.eq(0)).sum()
            ),
        )
        report["blockers"] += [
            "2023 영역 ZIP과 재제공 2021~2024 매출의 경계·버전 호환성 미확인",
            "월평균 해석의 공식 근거·2024 수치 대조 확보; 전 기간 적용과 분기 총액 환산 규칙 보완 필요",
        ]
        if len(absent):
            report["blockers"].append(
                "행 부재가 실제 업종 부재·비공개·자료 누락 중 무엇인지 미확인; 0 보충 금지"
            )
        if observed:
            config = yaml.safe_load((HERE / "plan.yaml").read_text())
            if config["outcomes"][0]["col"] != "log_observed_sales":
                raise ValueError("관측 매출 탐색 계획을 먼저 기록해야 합니다")
            full, panel = build_observed_panels(selected, names)
            # 검사가 모두 끝난 입력만 발행. 기존 산출물은 성공한 재생성으로 교체한다.
            target = HERE / "data"
            target.mkdir(exist_ok=True)
            full.to_csv(target / "observed-full.csv", index=False)
            panel.to_csv(target / "panel.csv.tmp", index=False)
            (target / "panel.csv.tmp").replace(target / "panel.csv")
            report.update(
                status="conditional",
                analysis_ready=True,
                panel_written=True,
                analysis_scope="observed_rows_only_exploratory",
                causal_identification="not_identified",
                full_rows=len(full),
                panel_rows=len(panel),
                panel_sha256=digest((target / "panel.csv").read_bytes()),
                limitations=[
                    b for b in report["blockers"] if not b.startswith("기존 data/panel.csv")
                ],
                blockers=[],
            )
    except (ValueError, KeyError, OSError, BadZipFile, csv.Error) as exc:
        report["blockers"].append(f"{type(exc).__name__}: {exc}")
    report["code_sha256"] = {
        p: digest((HERE / p).read_bytes())
        for p in [
            "fetch.py",
            "sales_panel.py",
            "characteristics_files.py",
            "fetch_characteristics.py",
        ]
    }
    report["plan_sha256"] = digest((HERE / "plan.yaml").read_bytes())
    report["groups_sha256"] = digest((HERE / "comparison-groups.yaml").read_bytes())
    dump(output / "quality.json", report)
    if report["panel_written"]:
        dump(HERE / "data/panel.source.json", report)
    return report


def simulate():
    """분리된 합성 입력으로 336/315행 변환과 공통 분석 흐름을 실행한다."""
    sys.path.insert(0, str(HERE.parents[1]))
    from core.agent.graph import run_flow

    parent = HERE / "data/simulation"
    parent.mkdir(parents=True, exist_ok=True)
    folder = Path(mkdtemp(prefix="sales-", dir=parent))
    rng = np.random.default_rng(20261021)
    names = [f"synthetic-{i:02}" for i in range(21)]
    rows = []
    for i, name in enumerate(names):
        for q in range(16):
            total = np.exp(
                15 + i * 0.02 + q * 0.01 + rng.normal(0, 0.03) + (0.1 if i == 0 and q >= 13 else 0)
            )
            rows.extend(
                (name, q, industry, total * share)
                for industry, share in zip(INDUSTRIES, [0.1, 0.2, 0.3, 0.4], strict=True)
            )
    full, panel = build_panels(
        pd.DataFrame(rows, columns=["gu_code", "quarter_idx", "industry_code", "sales_krw"]),
        treated_code=names[0],
        control_codes=names[1:],
    )
    assert (len(full), len(panel)) == (336, 315)
    (folder / "data").mkdir()
    full.to_csv(folder / "data/full.csv", index=False)
    panel = panel.rename(columns={"log_sales": "log_observed_sales"})
    panel.to_csv(folder / "data/panel.csv", index=False)
    config = yaml.safe_load((HERE / "plan.yaml").read_text())
    config.update(
        case_id=folder.name,
        title="합성 입력 실행 검사 — 실제 정책 효과 아님",
        synthetic_data=True,
        question="합성 패널로 실행 흐름이 끝까지 동작하는가?",
    )
    config["treatment"]["definition"] = "합성 지역 synthetic-00; 실제 동대문구 자료 아님"
    config["control"] = {"definition": "합성 지역 synthetic-01~20", "rationale": "코드 검증 전용"}
    config["data_sources"] = [
        {
            "name": "고정 seed 합성 입력",
            "provider": "사례 코드",
            "license": "synthetic",
            "path": "data/panel.csv",
        }
    ]
    (folder / "plan.yaml").write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False))
    state = run_flow(folder, allow_uncommitted=True)
    dump(
        folder / "simulation-check.json",
        {
            "synthetic_data": True,
            "seed": 20261021,
            "full_rows": len(full),
            "panel_rows": len(panel),
            "status": state.status,
            "steps": [{"step": s.step, "status": s.status} for s in state.steps],
        },
    )
    print(folder, state.status)
    return 0 if state.status in {"ok", "warn"} else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        nargs="?",
        default="build-observed",
        choices=["fetch", "build", "build-observed", "simulate"],
    )
    parser.add_argument("--snapshot", type=Path)
    args = parser.parse_args()
    if args.command == "simulate":
        return simulate()
    snapshot = download() if args.command == "fetch" else args.snapshot
    if snapshot is None:
        candidates = sorted((HERE / "data/raw/sales").glob("*"))
        if not candidates:
            sys.exit("매출 스냅샷 없음. fetch.py fetch로 원본을 취득하세요.")
        snapshot = candidates[-1]
    report = audit(
        snapshot,
        HERE / "data/sales-audit" / snapshot.name,
        observed=args.command in {"fetch", "build-observed"},
    )
    print(
        json.dumps(
            {k: report[k] for k in ["status", "blockers", "panel_written"]}, ensure_ascii=False
        )
    )
    if report["panel_written"]:
        print("관측 행 탐색 패널 발행; 전체 매출·인과효과 판단 불가", file=sys.stderr)
        return 0
    print("실자료 패널 발행 보류: " + "; ".join(report["blockers"]), file=sys.stderr)
    return 2  # 확인 공백을 해결하기 전에는 data/panel.csv를 만들지 않는다.


if __name__ == "__main__":
    sys.exit(main())
