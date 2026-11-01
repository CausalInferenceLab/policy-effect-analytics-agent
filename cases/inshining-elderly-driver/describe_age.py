"""부산 두 연령집단의 주민인구 대비 사고 빈도를 오프라인으로 재현한다.

연령 불명은 별도로 보존한다. 개인 운전 위험·정책 효과·대조군을 추정하지 않는다.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shlex
import sys
import warnings
import xml.etree.ElementTree as ET
from pathlib import Path

from describe import FONT_PATH, POLICY_NOTE, YEARS, _sha256, build_series
from describe_population import _relative, build_population_series

HERE = Path(__file__).resolve().parent
FIGURE_NAME = "04_busan_age_comparison.png"
FIELDS = (
    "year",
    "all_age_count",
    "under65_count",
    "age65plus_count",
    "unknown_count",
    "population_reference_date",
    "under65_population",
    "age65plus_population",
    "under65_per_10000",
    "age65plus_per_10000",
    "population_definition_break",
)
UNDER65 = ("19세 이하", "20-29세", "30-39세", "40-49세", "50-59세", "60-64세")
AGE_LABELS = ("합계", *UNDER65, "65세 이상", "불명")
TITLE = "65세 이상과 미만, 인구 대비 사고는 어떻게 달랐을까?"
SUBTITLE = "부산 · 가해운전자(1당사자) 연령별 사고건수 · 2014~2019년 연간 집계"
Y_LABEL = "각 연령 주민인구 1만 명당 가해운전자 사고건수 (건)"
DEFINITION_NOTE = "2016년부터 재외국민 포함 분모"
FOOTER = (
    "연령 불명 사고는 두 집단에서 제외 · 분모: 직전 12월 말 각 연령 주민등록인구",
    "65세 미만 분모는 아동·비운전자 포함 · 사고 발생지와 운전자 거주지는 다를 수 있음",
    "운전 노출 미보정 · 개인 운전 위험이나 정책 효과 추정이 아닙니다",
    "출처: TAAS 연령표 취득 2026-11-01 · 기존 사고·행안부 인구 취득 2026-10-27 · 로컬 시안",
)
KNOWN_LIMITS = [
    "연령 불명 사고는 두 집단 모두에서 제외하며 65세 미만은 알려진 앞 6구간의 직접 합이다.",
    "사고건수는 사망자 수가 아니며 뉴스의 사망자 35→18을 검증하거나 반증하지 않는다.",
    "각 집단 주민인구는 면허소지자·실제 운전자·주행거리·운전시간 분모가 아니다.",
    "65세 미만 인구는 아동·비운전자도 포함하므로 개인 운전 위험률이 아니다.",
    "사고 발생지와 운전자 거주지가 같다고 보장할 수 없다.",
    "직전 12월 말 주민등록인구를 연결하며 2016년부터 재외국민 포함 정의 경계가 있다.",
    "두 선을 2015→2016에서 끊으며 정의 변경의 규모나 연령별 기여분은 분리하지 않았다.",
    "2018년은 7월 정책 시작 전후가 혼재한 연간 값이며 월별 효과를 구분할 수 없다.",
    "2019년 11월 안전속도 5030 등 동시 정책의 영향을 분리하지 않았다.",
    "65세 미만은 관측 비교 계열이며 확정 미처치 대조군·위약 효과가 아니다.",
    "연령 구성·면허 보유·실제 운전 노출·교란을 조정하지 않았고 반사실을 추정하지 않았다.",
    "한계 기재가 교란 제거·인과 식별을 뜻하지 않으며 성공·실패·유의성을 판단하지 않는다.",
    "자료 이용조건·라이선스·외부 공개 검토는 미완료이고 분석·공개 승인은 false다.",
]


def parse_age_xml(raw, years):
    """공개 안전 투영표의 9연령행·연도·합계를 검증한다; 지역은 여기서 추론하지 않는다."""
    years = tuple(years)
    if not years or years != tuple(sorted(set(years))) or any(y not in YEARS for y in years):
        raise ValueError("요청 연도가 잘못되었습니다")
    if re.search(
        rb"<!DOCTYPE|<!ENTITY|JSESSIONID|clientIP\s*[=:]|wasIP\s*[=:]|rsaPublicKey",
        raw,
        re.IGNORECASE,
    ):
        raise ValueError("안전한 공개 XML 투영본만 허용합니다")
    try:
        root = ET.fromstring(raw)
        allowed = {
            "OCTAGONDATA": {"PAGE", "TITLE", "GRID", "GRIDCOMMENT", "ERROR"},
            "PAGE": {"TOTALPAGE", "CURRENTPAGE", "TOTALPAGEX", "TOTALPAGEY"},
            "GRID": {"LABELSESSION", "COLSESSION", "ROWSESSION", "DATASESSION", "HASUNIT", "SIZE"},
            "GRIDCOMMENT": {"PATTERNCOMMENT"},
        }
        if root.tag != "OCTAGONDATA":
            raise ValueError("공개 XML 루트 불일치")
        for node in root.iter():
            tags = [child.tag for child in node]
            if len(tags) != len(set(tags)) or set(tags) - allowed.get(node.tag, set()):
                raise ValueError("허용 범위 밖 또는 중복 XML 컨테이너")
        if {child.tag for child in root} != allowed["OCTAGONDATA"]:
            raise ValueError("공개 XML 필수 컨테이너 누락")
        if root.findtext("ERROR", "").strip() or root.findtext("TITLE", "").strip():
            raise ValueError("오류 응답 또는 검토되지 않은 제목")
        if any(root.findtext("./PAGE/" + tag) != "1" for tag in ("TOTALPAGE", "CURRENTPAGE")):
            raise ValueError("연령표는 PAGE 1/1이어야 합니다")

        def table(name):
            value = root.findtext("./GRID/" + name)
            if not value:
                raise ValueError("연령표 필수 테이블 누락")
            result = ET.fromstring(value.replace("&nbsp;", " "))
            if result.tag != "TABLE" or any(
                node.tag not in {"TABLE", "TR", "TD", "nobr"} for node in result.iter()
            ):
                raise ValueError("허용 범위 밖 테이블 구조")
            if any(child.tag != "TR" for child in result) or any(
                child.tag != "TD" for tr in result for child in tr
            ):
                raise ValueError("테이블 행·열 구조 오류")
            return list(result)

        columns = [td.get("code") for tr in table("COLSESSION") for td in tr]
        total_column = columns[:1] == ["합계"]
        if columns[int(total_column) :] != [str(y) for y in years]:
            raise ValueError("연도 열 누락·중복·순서 또는 요청기간 불일치")
        labels, data = table("ROWSESSION"), table("DATASESSION")
        if len(labels) != len(data) or len(labels) != 9:
            raise ValueError("정확한 9개 연령행이 필요합니다")
        rows = {}
        for label, values in zip(labels, data, strict=False):
            if len(label) != 1 or len(values) != len(columns):
                raise ValueError("연령행·연도 셀 수 불일치")
            name = label[0].get("code")
            if name in rows or name not in AGE_LABELS:
                raise ValueError("연령 경계 누락·중복·미확인 구간")
            if "".join(label[0].itertext()).strip() != name:
                raise ValueError("연령 코드·표시명 불일치")
            cells = ["".join(td.itertext()).strip() for td in values]
            if any(
                re.fullmatch(r"(?:[0-9]+|[1-9][0-9]{0,2}(?:,[0-9]{3})+)", v) is None for v in cells
            ):
                raise ValueError("사고건수는 음수·소수·억제기호 없는 정수여야 합니다")
            numbers = [int(v.replace(",", "")) for v in cells]
            if total_column and numbers[0] != sum(numbers[1:]):
                raise ValueError("다년 합계 불일치")
            rows[name] = numbers[int(total_column) :]
        if set(rows) != set(AGE_LABELS):
            raise ValueError("연령 구간 누락")
        result = []
        for index, year in enumerate(years):
            record = {
                "year": year,
                "all_age_count": rows["합계"][index],
                "under65_count": sum(rows[name][index] for name in UNDER65),
                "age65plus_count": rows["65세 이상"][index],
                "unknown_count": rows["불명"][index],
            }
            if record["all_age_count"] != sum(
                record[k] for k in ("under65_count", "age65plus_count", "unknown_count")
            ):
                raise ValueError("전체=65미만+65이상+불명 합계 불일치")
            result.append(record)
        return result
    except ET.ParseError as error:
        raise ValueError("공개 XML 파싱 실패") from error


def load_age_sources(raw_dir):
    """지역·지표가 내재하지 않은 XML을 검토된 요청 메타데이터와 정확 해시로 결합한다."""
    manifest = json.loads((HERE / "age-source-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("source_review_status") != "pass":
        raise ValueError("연령 source 독립 승인 누락")
    result = {"national": [], "busan": []}
    seen = set()
    for source in manifest["sources"]:
        area, years, request = source["area"], tuple(source["years"]), source["request"]
        key = (area, years)
        expected_condition = "" if area == "national" else "D906@|@P01 S01 #OTE![부산]!#;|;"
        if (
            area not in result
            or key in seen
            or years not in (YEARS[:5], YEARS[5:])
            or source["file"] != f"source-query-{area}-{years[0]}-{years[-1]}.xml"
            or request
            != {
                "row_dimension_id": 2736,
                "column_dimension_id": 888,
                "measure_id": 334,
                "measure_name": "사고[건]",
                "measure_physical_name": "ACC_CNT",
                "subject_id": 131,
                "pattern_id": 7125,
                "geography_dimension_id": 906,
                "area_condition": expected_condition,
                "start_month": f"{years[0]}01",
                "end_month": f"{years[-1]}12",
            }
        ):
            raise ValueError("검토된 지역·연령·사고건 지표·기간 조건 불일치")
        # XML TITLE is empty: never infer geography/measure from filename or values.
        path = Path(raw_dir) / source["file"]
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise ValueError("검토된 요청에 결합된 XML SHA256 불일치")
        result[area].extend(parse_age_xml(raw, years))
        seen.add(key)
    if len(seen) != 4:
        raise ValueError("전국·부산 두 기간 source 누락")
    return result


def build_age_series(sources, accident_rows, population_rows):
    """전국·부산 기존 65+를 대사하고 부산 각 연령집단의 동일 연령 분모를 연결한다."""
    accident_rows = list(accident_rows)
    existing = build_series(accident_rows)
    population = build_population_series(accident_rows, population_rows)
    selected = {}
    if set(sources) != {"national", "busan"}:
        raise ValueError("전국·부산 source가 필요합니다")
    for area, rows in sources.items():
        by_year = {}
        for row in rows:
            if (
                set(row)
                != {"year", "all_age_count", "under65_count", "age65plus_count", "unknown_count"}
                or any(type(v) is not int or v < 0 for v in row.values())
                or row["year"] in by_year
            ):
                raise ValueError("연령 집계 필드·정수·중복 오류")
            if (
                row["all_age_count"]
                != row["under65_count"] + row["age65plus_count"] + row["unknown_count"]
            ):
                raise ValueError("연령 집계 합계 불일치")
            by_year[row["year"]] = row
        if set(by_year) != set(YEARS):
            raise ValueError("2014~2019 연령 source 누락")
        for old in existing:
            expected = old["national_count" if area == "national" else "busan_count"]
            if by_year[old["year"]]["age65plus_count"] != expected:
                raise ValueError("기존 CSV의 65세 이상 사고건수와 불일치")
        selected[area] = by_year
    result = []
    for denominator in population:
        year = denominator["year"]
        row = selected["busan"][year]
        younger = denominator["population_total"] - denominator["population_65plus"]
        if younger <= 0:
            raise ValueError("65세 미만 인구 분모는 양수여야 합니다")
        older = denominator["population_65plus"]
        result.append(
            {
                **row,
                "population_reference_date": denominator["population_reference_date"],
                "under65_population": younger,
                "age65plus_population": older,
                "under65_per_10000": row["under65_count"] / younger * 10000,
                "age65plus_per_10000": row["age65plus_count"] / older * 10000,
                "population_definition_break": denominator["population_definition_break"],
            }
        )
    return result


def _validate_output_paths(inputs, outputs):
    owned = {
        HERE / "figures" / FIGURE_NAME,
        HERE / "data/age-descriptive-series.csv",
        HERE / "age-descriptive-manifest.json",
    }
    protected = [*inputs, FONT_PATH]
    for path in HERE.rglob("*"):
        if path.is_file() and (path not in owned or path.is_symlink() or path.stat().st_nlink != 1):
            protected.append(path)
    for output in outputs:
        owned_output = output.absolute() in owned
        if (
            output.is_symlink()
            or (owned_output and output.resolve() != output.absolute())
            or (output.exists() and (not owned_output or output.stat().st_nlink != 1))
        ):
            raise ValueError("기존 파일은 고정 소유 출력만 링크 없이 재생성할 수 있습니다")
        if any(
            output.resolve() == source.resolve()
            or (output.exists() and source.exists() and output.samefile(source))
            for source in protected
        ):
            raise ValueError("입력·코드·기존 산출물을 출력으로 덮어쓸 수 없습니다")
    for index, output in enumerate(outputs):
        for other in outputs[index + 1 :]:
            if output.resolve() == other.resolve() or (
                output.exists() and other.exists() and output.samefile(other)
            ):
                raise ValueError("출력 파일 경로는 링크를 포함해 서로 달라야 합니다")


def _render(series, path):
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import font_manager, ft2font, ticker
    from matplotlib import pyplot as plt

    if not FONT_PATH.is_file():
        raise ValueError("설치된 한글 폰트를 찾을 수 없습니다")
    font = ft2font.FT2Font(str(FONT_PATH))
    labels = ("65세 이상", "65세 미만 (연령 확인)")
    text = "".join(
        (
            TITLE,
            SUBTITLE,
            Y_LABEL,
            POLICY_NOTE,
            DEFINITION_NOTE,
            *FOOTER,
            *labels,
            "연도 (연간)0123456789,.",
        )
    )
    missing = {c for c in text if not c.isspace() and ord(c) not in font.get_charmap()}
    if missing:
        raise ValueError("한글 폰트 glyph 누락: " + "".join(sorted(missing)))
    font_manager.fontManager.addfont(str(FONT_PATH))
    font_name = font_manager.FontProperties(fname=FONT_PATH).get_name()
    style = {
        "font.family": font_name,
        "font.size": 16,
        "axes.unicode_minus": False,
        "figure.facecolor": "#FCFCFA",
        "axes.facecolor": "#FCFCFA",
        "text.color": "#202B38",
        "axes.labelcolor": "#344457",
        "xtick.color": "#344457",
        "ytick.color": "#344457",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.edgecolor": "#BAC3CD",
        "savefig.facecolor": "#FCFCFA",
    }
    with plt.rc_context(style), warnings.catch_warnings():
        warnings.filterwarnings("error", message=r"Glyph .* missing from font.*")
        fig, ax = plt.subplots(figsize=(17, 11), dpi=160)
        fig.subplots_adjust(left=0.105, right=0.955, bottom=0.32, top=0.745)
        fig.text(0.065, 0.95, TITLE, fontsize=29, va="top")
        fig.text(0.065, 0.89, SUBTITLE, fontsize=17, color="#526276")
        ax.axvspan(2017.55, 2018.45, color="#E7EBF0", alpha=0.8, zorder=0)
        ax.text(
            2018,
            0.985,
            POLICY_NOTE,
            transform=ax.get_xaxis_transform(),
            ha="center",
            va="top",
            fontsize=13,
            color="#526276",
        )
        ax.axvline(2015.5, color="#8C95A2", linewidth=1.2, linestyle=":", zorder=1)
        years = [r["year"] for r in series]
        for field, color, label, dy in [
            ("age65plus_per_10000", "#1768B2", labels[0], -25),
            ("under65_per_10000", "#D87922", labels[1], 13),
        ]:
            values = [r[field] for r in series]
            for start, stop in ((0, 2), (2, 6)):
                ax.plot(
                    years[start:stop],
                    values[start:stop],
                    color=color,
                    linewidth=3.2,
                    marker="o",
                    markersize=9,
                    label=label if start == 0 else None,
                    zorder=3,
                )
            for year, value in zip(years, values, strict=False):
                ax.annotate(
                    f"{value:.1f}",
                    (year, value),
                    xytext=(0, dy),
                    textcoords="offset points",
                    ha="center",
                    fontsize=17,
                    color=color,
                )
        maximum = max(r[f] for r in series for f in ("age65plus_per_10000", "under65_per_10000"))
        ax.set_ylim(0, math.ceil(maximum * 1.32 / 5) * 5)
        ax.set_xlim(2013.65, 2019.35)
        ax.set_xticks(years)
        ax.set_xlabel("연도 (연간)", labelpad=15)
        ax.set_ylabel(Y_LABEL, fontsize=15, labelpad=20)
        ax.yaxis.set_major_locator(ticker.MultipleLocator(10))
        ax.yaxis.set_major_formatter(ticker.StrMethodFormatter("{x:,.0f}"))
        ax.tick_params(axis="both", labelsize=16, length=0, pad=10)
        ax.grid(axis="y", color="#DCE1E7", linewidth=0.8, zorder=0)
        ax.legend(loc="upper left", frameon=False, ncol=2, fontsize=17, bbox_to_anchor=(0, 1.14))
        fig.text(0.105, 0.235, DEFINITION_NOTE, fontsize=14, color="#526276")
        for y, line in zip((0.176, 0.132, 0.088, 0.044), FOOTER, strict=False):
            fig.text(0.065, y, line, fontsize=14 if y > 0.05 else 12, color="#344457")
        try:
            fig.savefig(path, dpi=160, metadata={"Software": "TAAS age descriptive local draft"})
        finally:
            plt.close(fig)
    return {
        "matplotlib_version": matplotlib.__version__,
        "font_name": font_name,
        "font_file": FONT_PATH.name,
        "font_file_sha256": _sha256(FONT_PATH),
        "font_glyph_check": "all chart characters present; missing glyph warnings are errors",
        "backend": "Agg",
        "image_size_pixels": [2720, 1760],
        "zero_based_y_axis": True,
        "both_line_segments": [[2014, 2015], [2016, 2017, 2018, 2019]],
        "labeled_points_per_group": 6,
    }


def _command(arguments):
    result = []
    for argument in arguments:
        if argument.startswith("--") and "=" in argument:
            flag, value = argument.split("=", 1)
            result.append(flag + "=" + _relative(value))
        elif argument.startswith("--"):
            result.append(argument)
        else:
            result.append(_relative(argument))
    return shlex.join([_relative(sys.executable), _relative(__file__), *result])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=HERE / "data/raw-age")
    parser.add_argument("--accidents", type=Path, default=HERE / "data/taas-national.csv")
    parser.add_argument("--population", type=Path, default=HERE / "data/population.csv")
    parser.add_argument("--output-dir", type=Path, default=HERE / "figures")
    parser.add_argument(
        "--series-output", type=Path, default=HERE / "data/age-descriptive-series.csv"
    )
    parser.add_argument(
        "--manifest-output", type=Path, default=HERE / "age-descriptive-manifest.json"
    )
    arguments = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(arguments)
    figure = args.output_dir / FIGURE_NAME
    outputs = [figure, args.series_output, args.manifest_output]
    inputs = [
        args.accidents,
        args.population,
        HERE / "age-source-manifest.json",
        *sorted(args.raw_dir.glob("*.xml")),
    ]
    try:
        _validate_output_paths(inputs, outputs)
        input_hashes = [_sha256(p) for p in inputs]
        sources = load_age_sources(args.raw_dir)
        with (
            args.accidents.open(encoding="utf-8-sig", newline="") as accidents,
            args.population.open(encoding="utf-8-sig", newline="") as population,
        ):
            series = build_age_series(
                sources, csv.DictReader(accidents), csv.DictReader(population)
            )
        for output in outputs:
            output.parent.mkdir(parents=True, exist_ok=True)
        rendering = _render(series, figure)
        with args.series_output.open("w", encoding="utf-8", newline="") as destination:
            writer = csv.DictWriter(destination, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(series)
        if input_hashes != [_sha256(p) for p in inputs]:
            raise ValueError("실행 중 입력 SHA256 변경")
        manifest = {
            "schema_version": 1,
            "status": "local_draft",
            "descriptive_only": True,
            "analysis_approved": False,
            "publication_approved": False,
            "command": _command(arguments),
            "command_working_directory": "project root",
            "mode": "offline replay of reviewed retained XML; no new network request",
            "python_version": sys.version.split()[0],
            "inputs": [
                {"path": _relative(p), "sha256": digest}
                for p, digest in zip(inputs, input_hashes, strict=False)
            ],
            "code": {"path": _relative(__file__), "sha256": _sha256(Path(__file__))},
            "dependencies": [
                {"path": _relative(p), "sha256": _sha256(p)}
                for p in (
                    HERE / "describe.py",
                    HERE / "describe_population.py",
                    HERE / "population-qc.json",
                )
            ],
            "years": list(YEARS),
            "geography": "부산 광역 합계; 인구 코드 2600000000; 하위지역 재합산 없음",
            "reconciliation": "전국·부산 12개 지역연도 65+가 기존 CSV와 정확 일치",
            "formulas": {
                "under65_count": "sum(19세 이하,20-29세,30-39세,40-49세,50-59세,60-64세)",
                "partition": "all_age_count = under65_count + age65plus_count + unknown_count",
                "under65_population": "population_total - population_65plus > 0",
                "under65_per_10000": "under65_count / under65_population * 10000",
                "age65plus_per_10000": "age65plus_count / age65plus_population * 10000",
            },
            "population_reference_dates": [r["population_reference_date"] for r in series],
            "population_definition": "직전 12월 말 주민등록인구, 남녀계, 외국인 제외; 기존 수집 정의 사용",
            "population_definition_break": {
                "first_reference_date": "2015-12-31",
                "first_outcome_year": 2016,
                "definition": "재외국민 포함",
                "size_separately_identified": False,
            },
            "known_limits": KNOWN_LIMITS,
            "rendering": rendering,
            "outputs": [{"path": _relative(p), "sha256": _sha256(p)} for p in outputs[:2]],
            "manifest_hash_note": "자기 참조 해시는 독립 실행 증거에 별도 기록한다.",
        }
        args.manifest_output.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "status": "local_draft",
                    "rows": len(series),
                    "series": series,
                    "input_sha256": input_hashes,
                    "outputs": [_relative(p) for p in outputs],
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (OSError, ValueError, RuntimeError, Warning, KeyError, TypeError) as error:
        print(f"연령별 관측 그래프 생성 실패: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
