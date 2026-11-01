"""검토된 로컬 관측자료를 대사하고 보고서를 재생성한다. 네트워크·효과 추정 없음."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
OWNED_OUTPUTS = ("report.md", "flow_log.json", "run_manifest.json")
COMMAND = "python3 cases/inshining-elderly-driver/run_descriptive.py"
COLUMNS = (
    ("year", "연도", "년"),
    ("busan_count", "부산 65세 이상 가해운전자 사고", "건"),
    ("national_count", "전국 65세 이상 가해운전자 사고", "건"),
    ("rest_count", "전국에서 부산을 뺀 65세 이상 사고", "건"),
    ("population_65plus", "직전 12월 말 부산 65세 이상 주민", "명"),
    ("population_total", "직전 12월 말 부산 전체 주민", "명"),
    ("per_10000_65plus", "부산 65세 이상 주민 1만 명당 사고", "건/주민 1만 명"),
    ("under65_count", "부산 연령 확인 65세 미만 사고", "건"),
    ("unknown_count", "부산 운전자 연령 불명 사고", "건"),
    ("under65_population", "직전 12월 말 부산 65세 미만 주민", "명"),
    ("under65_per_10000", "부산 65세 미만 주민 1만 명당 사고", "건/주민 1만 명"),
)
SOURCES = [
    {
        "name": "TAAS 가해운전자(1당사자) 연령별 교통사고",
        "url": "https://taas.koroad.or.kr/OBIP25/analysis/TypicalAnalysis.jsp",
        "provider": "한국도로교통공단 교통사고분석시스템",
        "license": "other",
        "notes": "2014~2019 연간 사고[건], 부산·전국 합계. 65+ 취득 2026-10-27, 연령표 취득 2026-11-01. 자체 집계; 이용 범위는 source-use-notes.md 참조.",
    },
    {
        "name": "행정안전부 주민등록 인구통계 연령별 인구현황",
        "url": "https://jumin.mois.go.kr/ageStatMonth.do",
        "provider": "행정안전부",
        "license": "other",
        "notes": "2013~2018년 12월 말, 부산 광역 합계, 남녀계·외국인 제외. 취득 2026-10-27. 보유 CSV와 현재 이용허락 메타데이터의 파일·버전 연결 미확인.",
    },
]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _safe_path(root, value):
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("근거 경로는 저장소 내부 상대경로여야 합니다")
    target = root / relative
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("근거 경로가 저장소 밖을 가리킵니다")
    return target


def validate_outputs(case, inputs, outputs):
    """모든 출력 검사를 쓰기 전에 끝낸다; 고정 소유 3개만 기존 파일 갱신 가능."""
    case = Path(case).absolute()
    owned = {case / name for name in OWNED_OUTPUTS}
    outputs = [Path(p).absolute() for p in outputs]
    protected = [Path(p) for p in inputs]
    protected.extend(p for p in case.rglob("*") if p.is_file() and p not in owned)
    for output in outputs:
        for node in (output, *output.parents):
            if node != output and node.is_file():
                raise ValueError("출력 상위 경로가 파일입니다")
            if node not in case.parents and node.is_symlink():
                raise ValueError("출력과 출력 상위 디렉터리의 심볼릭 링크는 허용하지 않습니다")
        if output.exists() and (
            output not in owned or not output.is_file() or output.stat().st_nlink != 1
        ):
            raise ValueError("기존 입력·산출물·복수 하드링크를 덮어쓸 수 없습니다")
        if any(
            output.resolve() == source.resolve()
            or (output.exists() and source.exists() and output.samefile(source))
            for source in protected
        ):
            raise ValueError("입력과 출력이 충돌합니다")
    if any(
        a.resolve() in b.resolve().parents or b.resolve() in a.resolve().parents
        for i, a in enumerate(outputs)
        for b in outputs[i + 1 :]
    ):
        raise ValueError("출력 파일을 다른 출력의 상위 경로로 사용할 수 없습니다")
    if len({p.resolve() for p in outputs}) != len(outputs):
        raise ValueError("출력 경로가 서로 충돌합니다")
    if any(
        a.exists() and b.exists() and a.samefile(b)
        for i, a in enumerate(outputs)
        for b in outputs[i + 1 :]
    ):
        raise ValueError("출력 파일이 링크로 서로 충돌합니다")


def verify_manifest(root, path, required_outputs):
    """생성 provenance와 필수 실제 산출물의 정확 바이트를 확인한다."""
    root, path = Path(root), Path(path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if (
        manifest.get("descriptive_only") is not True
        or manifest.get("analysis_approved") is not False
    ):
        raise ValueError("관측 전용 provenance 상태가 아닙니다")
    entries = list(manifest.get("inputs", [])) + list(manifest.get("dependencies", []))
    entries += [manifest[key] for key in ("input", "code") if key in manifest]
    outputs = manifest.get("outputs", [])
    actual_outputs = {_safe_path(root, e["path"]).resolve() for e in outputs}
    if not {Path(p).resolve() for p in required_outputs} <= actual_outputs:
        raise ValueError("필수 그림 또는 CSV의 provenance가 누락되었습니다")
    checked = []
    for entry in [*entries, *outputs]:
        target = _safe_path(root, entry["path"])
        if not target.is_file() or sha256(target) != entry["sha256"]:
            raise ValueError("파일 누락 또는 SHA256 불일치: " + entry["path"])
        checked.append(target)
    return checked


def verify_csv(path, expected):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        if not expected or reader.fieldnames != list(expected[0]):
            raise ValueError("CSV 필드가 재계산 결과와 다릅니다")
    if len(rows) != len(expected):
        raise ValueError("CSV 행 수가 재계산 결과와 다릅니다")
    for actual, recalculated in zip(rows, expected, strict=False):
        for key, value in recalculated.items():
            cell = actual[key]
            if type(value) is float:
                try:
                    matched = math.isfinite(float(cell)) and math.isclose(
                        float(cell), value, rel_tol=1e-12, abs_tol=1e-12
                    )
                except ValueError:
                    matched = False
            else:
                matched = cell == str(value)
            if not matched:
                raise ValueError(f"CSV 재계산 불일치: {key}")


def verify_study():
    """이미 생성된 네 그림을 검증하고 승인 모듈 순수 함수로 집계를 다시 계산한다."""
    from describe import build_series
    from describe_age import build_age_series, load_age_sources
    from describe_population import build_population_series

    root = HERE.parents[1]
    inputs = []
    manifests = []
    for name, output_names in (
        (
            "descriptive-manifest.json",
            (
                "figures/01_busan_counts.png",
                "figures/02_busan_vs_rest_counts.png",
                "data/descriptive-series.csv",
            ),
        ),
        (
            "population-descriptive-manifest.json",
            (
                "figures/03_busan_counts_and_population.png",
                "data/population-descriptive-series.csv",
            ),
        ),
        (
            "age-descriptive-manifest.json",
            ("figures/04_busan_age_comparison.png", "data/age-descriptive-series.csv"),
        ),
    ):
        path = HERE / name
        inputs.extend(verify_manifest(root, path, [HERE / p for p in output_names]))
        inputs.append(path)
        manifests.append(path)
    for name, source_field in (
        ("taas-qc.json", "file"),
        ("population-qc.json", "path"),
    ):
        path = HERE / name
        qc = json.loads(path.read_text(encoding="utf-8"))
        for source in qc["sources"]:
            target = _safe_path(HERE, source[source_field])
            if sha256(target) != source["sha256"]:
                raise ValueError("원자료 SHA256 불일치: " + source[source_field])
            inputs.append(target)
        records = qc.get("outputs_sha256", {qc.get("output", ""): qc.get("output_sha256", "")})
        for name, digest in records.items():
            target = _safe_path(HERE, name)
            if sha256(target) != digest:
                raise ValueError("원자료 집계 출력 SHA256 불일치: " + name)
            inputs.append(target)
        inputs.append(path)
    accidents_path, population_path = HERE / "data/taas-national.csv", HERE / "data/population.csv"
    with accidents_path.open(encoding="utf-8-sig", newline="") as stream:
        accidents = list(csv.DictReader(stream))
    with population_path.open(encoding="utf-8-sig", newline="") as stream:
        population = list(csv.DictReader(stream))
    counts = build_series(accidents)
    denominators = build_population_series(accidents, population)
    age = build_age_series(load_age_sources(HERE / "data/raw-age"), accidents, population)
    for name, values in (
        ("descriptive-series.csv", counts),
        ("population-descriptive-series.csv", denominators),
        ("age-descriptive-series.csv", age),
    ):
        verify_csv(HERE / "data" / name, values)
    rows = []
    for count, denominator, ages in zip(counts, denominators, age, strict=False):
        row = {**count, **denominator, **ages}
        rows.append({key: row[key] for key, _, _ in COLUMNS})
    payload = make_descriptive(rows)
    validate_descriptive(payload)
    for name in (
        "age-source-manifest.json",
        "run_descriptive.py",
        "README.md",
        "discussion.md",
        "source-use-notes.md",
        "comparison-feasibility.md",
        "data/README.md",
        "plan.yaml",
    ):
        inputs.append(HERE / name)
    inputs.extend(sorted((HERE / "evidence/policy-sources").glob("*.txt")))
    unique = sorted(set(inputs))
    return {
        "rows": rows,
        "descriptive": payload,
        "inputs": unique,
        "manifests": manifests,
        "verification": [
            "source/raw/code/figure/CSV SHA256 match",
            "three pure aggregation functions recalculated",
            "three series CSVs match recalculation",
            "six numeric years; unknown age preserved separately",
        ],
    }


def make_descriptive(rows):
    return {
        "columns": [{"key": key, "label": label, "unit": unit} for key, label, unit in COLUMNS],
        "rows": [{key: row[key] for key, _, _ in COLUMNS} for row in rows],
        "definitions": {key: label + " (" + unit + ")" for key, label, unit in COLUMNS}
        | {
            "population_reference": "사고연도의 직전 12월 말 주민등록인구. 2016년 사고연도부터 재외국민 포함 정의 경계.",
            "unknown_count": "연령 불명 사고는 65세 미만·이상 어느 집단에도 배분하지 않는다.",
            "interpretation": "사고 발생지 기준 주민인구 대비 빈도. 운전 노출·면허 보유·개인 위험·정책효과가 아니다.",
        },
        "sources": SOURCES,
        "reproduction": {
            "command": COMMAND,
            "mode": "offline retained-snapshot replay; no network",
            "prerequisites": [
                "검토된 raw XML/CSV와 세 집계 CSV·네 PNG 및 provenance manifest",
                "원자료는 data/README.md의 획득 절차로 별도 확보; Git에 포함되지 않음",
                "Python 3.10 이상; 기존 그림 검증·보고서 생성은 표준 라이브러리만 사용",
            ],
        },
    }


def validate_descriptive(payload):
    keys = [key for key, _, _ in COLUMNS]
    rows = payload["rows"]
    if len(rows) != 6 or [row.get("year") for row in rows] != list(range(2014, 2020)):
        raise ValueError("2014~2019 여섯 개년이 필요합니다")
    for row in rows:
        if set(row) != set(keys) or type(row["year"]) is not int:
            raise ValueError("효과·문자 필드를 숫자 관측행에 넣을 수 없습니다")
        if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in row.values()):
            raise ValueError("관측값은 유한한 비음수 숫자여야 합니다")
        if row["national_count"] != row["busan_count"] + row["rest_count"]:
            raise ValueError("전국=부산+부산외 합계 불일치")
        if row["population_total"] != row["population_65plus"] + row["under65_population"]:
            raise ValueError("연령별 인구 분모 합계 불일치")
        for numerator, denominator, rate in (
            ("busan_count", "population_65plus", "per_10000_65plus"),
            ("under65_count", "under65_population", "under65_per_10000"),
        ):
            if row[denominator] <= 0 or not math.isclose(
                row[rate], row[numerator] / row[denominator] * 10000, rel_tol=1e-12
            ):
                raise ValueError("연령별 사고 빈도 계산 불일치")


def make_flow(payload, timestamp):
    return {
        "schema_version": 1,
        "case_id": "inshining-elderly-driver",
        "generated_at": timestamp,
        "status": "completed",
        "execution_kind": "descriptive_only",
        "causal_estimation": "not_run",
        "verdict": "not_identified",
        "analysis_approved": False,
        "results": [],
        "steps": [
            {"step": name, "status": "completed"}
            for name in (
                "verify_saved_provenance",
                "recalculate_observations",
                "write_descriptive_report",
            )
        ],
        "descriptive": payload,
        "judgment": "관측 비교를 완료했다. 검증된 반사실·비교군이 없어 정책의 예방효과는 식별하지 못했다.",
    }


def render_report(rows):
    old, new = rows[3], rows[5]

    def change(key):
        return (new[key] / old[key] - 1) * 100

    table = "\n".join(
        f"| {r['year']} | {r['busan_count']:,} | {r['population_65plus']:,} | {r['per_10000_65plus']:.2f} | {r['under65_count']:,} | {r['unknown_count']:,} | {r['under65_per_10000']:.2f} |"
        for r in rows
    )
    return f"""# 면허 반납 지원은 고령운전자 사고를 줄였는가?

**짧은 답:** 부산의 관측 사고건수와 고령인구 대비 사고 빈도는 증가했다. 현재 비교자료로 면허반납 지원의 예방효과 방향·크기는 식별하지 못했다. 관측 연구는 완료했으며 인과 추정은 실행하지 않았다(`not_identified`).

부산은 2018년 7월 지원을 시작했다. [부산시 2019-02-18 공식 보도자료](https://www.busan.go.kr/nbtnews/1361473)는 시행 시점을 설명한다. 도입 직전인 2017년과 2019년을 비교하면 65세 이상 가해운전자 사고가 {old["busan_count"]:,}→{new["busan_count"]:,}건으로 **{change("busan_count"):.1f}% 증가**했다. 같은 연결 기준의 65세 이상 주민은 {old["population_65plus"]:,}→{new["population_65plus"]:,}명({change("population_65plus"):.1f}%) 증가했고, 주민 1만 명당 사고 빈도는 {old["per_10000_65plus"]:.2f}→{new["per_10000_65plus"]:.2f}건(**{change("per_10000_65plus"):.1f}% 증가**)이다. 주민인구 분모만으로 증가가 사라지지는 않는다. 이는 면허 보유·실제 운전 노출을 보정한 개인 위험이나 정책 실패의 증거가 아니다.

> 안전하게 인용할 문장: “2014~2019년 공개자료를 대사한 결과, 부산의 65세 이상 가해운전자 사고는 2017~2019년 건수와 주민인구 대비 빈도 모두 증가했다. 면허반납 지원이 없었을 경우와의 차이는 추정하지 못했다.”

부산 보도의 사망자 35→18명은 이 표의 **사고건수와 다른 결과**다. 여기서는 그 사망자 감소를 재현·반증하거나 사고와 같은 지표로 비교하지 않았다.

## 관측값: 부산 변화에서 비교의 한계까지

분자는 해당 연도 부산에서 발생한 가해운전자(1당사자) 사고, 분모는 직전 12월 말 부산 주민등록인구다. 표의 65세 미만은 확인된 여섯 연령구간을 직접 합산했으며, 연령 불명은 어느 집단에도 배분하지 않았다.

| 연도 | 65+ 사고(건) | 65+ 주민(명) | 65+ 주민 1만 명당(건) | 65세 미만 사고(건) | 연령 불명(건) | 65세 미만 주민 1만 명당(건) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
{table}

![부산 65세 이상 가해운전자 사고건수](figures/01_busan_counts.png)

![부산과 전국에서 부산을 뺀 사고건수 비교](figures/02_busan_vs_rest_counts.png)

전국에서 부산을 뺀 계열은 규모와 전국적 추세를 읽는 **참고선**이다. 서울·경기 등 2019년 지원 지역을 포함하므로 미처치 대조군이 아니다. 2017년=100은 각 계열의 크기를 맞춘 지수이며 정책효과가 아니다. 전주·군산도 2019년 입법 신호와 2020년 제공 기록이 공존한다. 선행 지원·예고 반응·경계·분모·사전 추세 검증을 마치지 않아 후보의 분석 적격성은 보류한다. 두 도시의 새로운 숫자는 집계하지 않았다. [비교 적격성 근거](comparison-feasibility.md).

![고령 사고건수와 고령 주민인구 대비 빈도](figures/03_busan_counts_and_population.png)

![부산 65세 미만·이상의 각 연령 주민인구 대비 사고 빈도](figures/04_busan_age_comparison.png)

2017~2019년 65세 미만 주민인구 대비 빈도도 {change("under65_per_10000"):.1f}% 증가했다. 두 집단의 변화율 차이는 정책효과가 아니다. 도입 전인 2016→2017년에도 고령선은 상승하고 비고령선은 하락한다. 이 구간은 2015→2016 분모 정의 경계를 넘지 않는다. 이는 비고령선을 그대로 고령집단의 반사실로 볼 수 없는 관측상 주의점이며, 사전추세의 통계적 검정을 실행하거나 기각했다는 뜻이 아니다.

연령 비교는 다른 분모의 두 관측 계열이다. 65세 미만 주민에는 아동·비운전자도 포함되며 두 연령집단의 운전 노출과 면허 보유가 다르다. 고령선의 수준이 낮다는 이유로 고령 개인의 운전 위험이 더 낮다고 해석할 수도 없다. 65세 미만을 확정 미처치·위약 대조군으로 사용하지 않았다. 2016년 사고연도부터 연결된 인구에 재외국민 포함 정의 경계가 있어 두 선을 2015→2016에서 끊었다. 그 정의 변화의 크기나 연령별 기여분은 분리하지 않았다.

## 인과판단을 막는 근거

- 부산 한 광역 정책군집과 2014~2017년 사전 네 해, 2018년 부분 노출, 2019년 한 온전한 사후 연도다. 구군 수가 독립 정책군집 수를 늘리지 않는다.
- [부산 안전속도 5030](https://www.busan.go.kr/depart/5030safe01)은 2019-11-11 도심 전역 시행, 본격 단속은 2020-05-12다. 2019년 늦은 시점의 혼입 가능성을 분리하지 않았다. 부산 고유 정책은 연도 효과만으로 제거되지 않는다.
- [국민권익위원회2019-420호(2019-09-23 의결),6~7쪽](https://m.acrc.go.kr/boardDownload.es?bid=1013&list_no=30601&seq=1)은 2019년1월부터75세 이상 면허 발급·갱신 대상자의 의무교육과3년 갱신주기를 설명한다. 모든75세 이상 주민이 동시에 교육받는 제도가 아니다. 갱신 대상 비중·연령 구성에 따른 차등 노출과 운전 노출·면허 보유·교통수단·지역 추세를 조정하지 않았다.
- 사고 발생지와 운전자 거주지는 다를 수 있다. 주민인구 분모는 실제 운전자·주행거리 분모가 아니다. 정책 대상 연령과 65+ 결과의 연령 경계도 완전히 같지 않다.
- 전주·군산의 후보 지위는 확정 미처치가 아니며 hold/unknown을 0으로 바꾸지 않았다. 검증된 비교군·반사실이 없다.

따라서 관측 증가가 정책의 실패·효과 없음·개인 위험 증가를 뜻하지 않는다. 효과가 감소 방향이었어도 다른 요인의 증가를 상쇄했을 가능성과 반대 가능성을 구별할 수 없다. **효과값·신뢰구간·p값을 계산하지 않았고 estimator/estimate/refute 단계도 실행하지 않았다.** 한계의 열거는 교란 제거·평행추세 입증·인과 식별이 아니다.

## 자료·공개 범위와 재현

출처: 한국도로교통공단 [TAAS](https://taas.koroad.or.kr/OBIP25/analysis/TypicalAnalysis.jsp), 2014~2019년 가해운전자 사고건수(기존65+ 취득2026-10-27, 연령표 취득2026-11-01); 행정안전부 [주민등록 인구통계](https://jumin.mois.go.kr/ageStatMonth.do), 2013~2018년12월(취득2026-10-27). 자체 집계·시각화다. 사실 집계/새 차트와 원표·화면·DB 재배포, 자동 접근을 구별한다. 보유 인구 CSV의 파일·버전 이용조건 연결 등은 [출처·이용조건](source-use-notes.md)에 남겼다. 불확실성은 전면 공개 금지나 전면 허가를 뜻하지 않는다. 원자료·가공 CSV/XML은 기존 data ignore에 따라 배포물에서 제외한다.

프로젝트 루트에서 `{COMMAND}`를 실행한다. 기본 네트워크 요청은 0이며 세 집계 순수 함수, 원자료·코드·네 그림·세 CSV의 해시·숫자를 검증하고 `report.md`, `flow_log.json`, `run_manifest.json`만 갱신한다. 그림 재생성은 각 describe 모듈의 별도 명령이다. 누락·변조는 실패하고 보고서를 완료로 쓰지 않는다. 원자료 없는 새 clone의 획득·동일 바이트와 새 다운로드 구별은 [데이터 안내](data/README.md)를 따른다. 실행 시각 파일은 바뀔 수 있고 수치·그림은 대사 대상이다.

계획 작성 전 보도와 선행연구 결과를 알고 있었고 이후 원자료·결과를 열람했다. 이번 사례는 탐색적 관측 분석이며 사전등록 완료라고 주장하지 않는다. 계획의 인과 추정 설계는 미실행 초안으로 보존했다. [토론](discussion.md), [실행 로그](flow_log.json), [실행 manifest](run_manifest.json).
"""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-output", type=Path, default=HERE / "report.md")
    parser.add_argument("--flow-output", type=Path, default=HERE / "flow_log.json")
    parser.add_argument("--manifest-output", type=Path, default=HERE / "run_manifest.json")
    arguments = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(arguments)
    outputs = [
        path.absolute() for path in (args.report_output, args.flow_output, args.manifest_output)
    ]
    try:
        validate_outputs(HERE, [], outputs)
        study = verify_study()
        validate_outputs(HERE, study["inputs"], outputs)
        inputs = {p: sha256(p) for p in study["inputs"]}
        timestamp = datetime.now(timezone.utc).isoformat()  # noqa: UP017 - Python 3.10 replay support
        report = render_report(study["rows"])
        flow = make_flow(study["descriptive"], timestamp)
        bodies = [report, json.dumps(flow, ensure_ascii=False, indent=2) + "\n"]
        root = HERE.parents[1]

        def label(p):
            return str(p.relative_to(root)) if p.is_relative_to(root) else p.name

        redacted = False
        invocation_arguments = []
        for argument in arguments:
            if argument.startswith("--") and "=" not in argument:
                invocation_arguments.append(argument)
                continue
            flag, value = argument.split("=", 1) if argument.startswith("--") else ("", argument)
            path = Path(value).absolute()
            if path.is_relative_to(root):
                value = str(path.relative_to(root))
            else:
                value = "<external-output>/" + path.name
                redacted = True
            invocation_arguments.append(flag + "=" + value if flag else value)
        actual_command = shlex.join(
            ["python3", "cases/inshining-elderly-driver/run_descriptive.py", *invocation_arguments]
        )
        manifest = {
            "schema_version": 1,
            "generated_at": timestamp,
            "execution_kind": "descriptive_only",
            "status": "completed",
            "causal_estimation": "not_run",
            "verdict": "not_identified",
            "analysis_approved": False,
            "publication_approved": False,
            "command": actual_command,
            "canonical_reproduction_command": COMMAND,
            "invocation": {
                "arguments": invocation_arguments,
                "external_output_paths_redacted": redacted,
                "working_directory": "project root after output path normalization",
                "path_note": "외부 절대 출력 경로는 <external-output>/파일명으로 가림; 정확 argv는 로컬 실행 증거에 보관",
            },
            "python_version": platform.python_version(),
            "scope": "부산2014~2019 관측 비교; 효과 추정·반증검정 미실행",
            "inputs": [{"path": label(p), "sha256": digest} for p, digest in inputs.items()],
            "verification": study["verification"],
            "network_requests": 0,
            "outputs": [
                {"path": label(p), "sha256": hashlib.sha256(body.encode()).hexdigest()}
                for p, body in zip(outputs[:2], bodies, strict=False)
            ],
            "sources": SOURCES,
            "stability": "generated_at는 실행마다 변경; 수치·그림 바이트는 별도 manifest로 대사",
            "manifest_hash_note": "자기 참조 해시 제외; 독립 실행 증거에서 별도 해시 기록",
            "git_revision": None,
            "git_revision_note": "현재 작업 루트의 Git commit을 확인·기록하지 않음",
        }
        bodies.append(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        if inputs != {p: sha256(p) for p in study["inputs"]}:
            raise ValueError("검증 중 입력이 변경되었습니다")
        validate_outputs(HERE, study["inputs"], outputs)
        for path, body in zip(outputs, bodies, strict=False):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        print(
            json.dumps(
                {
                    "status": "completed",
                    "execution_kind": "descriptive_only",
                    "verdict": "not_identified",
                    "rows": len(study["rows"]),
                    "network_requests": 0,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
        print(
            "오프라인 재현 중단: "
            + str(error)
            + "\n원자료·그림이 없으면 data/README.md의 별도 획득·생성 절차를 확인하세요.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
