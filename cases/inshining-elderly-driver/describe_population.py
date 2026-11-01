"""부산 사고건수와 주민등록 고령인구 대비 빈도를 그리는 로컬 시안.

개인 운전 위험이나 정책 효과를 추정하지 않는다. 집계는 표준 라이브러리만
사용하고 matplotlib과 설치된 한글 폰트는 렌더링할 때만 불러온다.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shlex
import sys
import warnings
from pathlib import Path

from describe import (
    FONT_PATH,
    POLICY_NOTE,
    YEARS,
    _nonnegative_integer,
    _sha256,
    build_series,
)

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
FIELDS = (
    "year",
    "busan_count",
    "population_reference_date",
    "population_65plus",
    "population_total",
    "per_10000_65plus",
    "per_10000_total",
    "population_definition_break",
)
BUSAN_CODE = "2600000000"
BUSAN_NAME = "부산광역시"
FIGURE_NAME = "03_busan_counts_and_population.png"
TITLE = "부산 사고 증가, 고령인구 규모를 고려하면?"
SUBTITLE = "65세 이상 가해운전자 사고 · 2014~2019년 연간 집계"
PANEL_TITLES = ("사고건수", "고령인구 대비 사고건수")
Y_LABELS = ("사고건수 (건)", "65세 이상 인구 1만 명당 사고건수 (건)")
DEFINITION_NOTE = "2016년부터 재외국민 포함 분모"
DENOMINATOR_NOTE = "분모: 직전 12월 말 65세 이상 주민등록인구"
INTERPRETATION_NOTE = "주민인구 대비 빈도이며 개인 운전 위험이나 정책 효과 추정이 아닙니다"
SOURCE_NOTE = "출처: TAAS · 행정안전부 · 기존 자료 수집일: 2026-10-27 · 로컬 시안"
KNOWN_LIMITS = [
    "65세 이상 가해운전자(1당사자) 교통사고 건수이며 사망자 수가 아니다.",
    "직전 12월 말 주민등록인구는 면허소지자·운전자·실제 운전량 분모가 아니다.",
    "사고 발생지역과 운전자 거주지역이 같다고 보장할 수 없다.",
    "전체인구 1만 명당 빈도의 분자도 65세 이상 가해운전자 사고이며 전 연령 사고가 아니다.",
    "재외국민 포함 정의 변경은 2015년 12월 분모부터, 이 연결에서는 2016년 사고연도부터 반영된다.",
    "정의 변경의 규모나 연령별 기여분은 분리하지 않았으며 경계 전후 증가분으로 해석하지 않는다.",
    "2018년은 7월 정책 시작으로 시행 전·후가 혼재한 연간 집계다.",
    "2019년 11월 안전속도 5030 등 동시 정책의 영향을 분리하지 않았다.",
    "대조군과 정책이 없었을 반사실을 검증하거나 추정하지 않았다.",
    "65세 미만 사고 분자가 없으며 전 연령에서 65세 이상을 빼도 미상연령 처리가 없으면 65세 미만이 아니다.",
    "정책의 성공·실패·무의미함 또는 통계적 유의성을 판단하지 않는다.",
    "TAAS·인구 자료 이용조건과 외부 공개 검토가 끝나지 않은 로컬 시안이다.",
]


def build_population_series(accident_rows, population_rows):
    """부산 광역 합계와 직전 12월 분모를 검증해 2014~2019년 빈도를 반환한다."""
    accidents = build_series(accident_rows)
    population = {}
    expected_hierarchy = {
        "region_code": BUSAN_CODE,
        "region_name": BUSAN_NAME,
        "province_code": BUSAN_CODE,
        "province_name": BUSAN_NAME,
        "is_province_total": "True",
        "is_aggregate": "True",
        "overlapping_city_total": "False",
    }
    for row in population_rows:
        # 두 식별자 중 하나라도 광역 합계를 가리키면 잘못된 짝도 거부한다.
        if row.get("region_code") != BUSAN_CODE and row.get("region_name") != BUSAN_NAME:
            continue
        if any(row.get(field) != value for field, value in expected_hierarchy.items()):
            raise ValueError("부산 인구의 코드·명칭·광역 합계 계층이 일치하지 않습니다")
        year = _nonnegative_integer(row.get("outcome_year"), "인구 연결 사고연도")
        if year not in YEARS:
            raise ValueError("부산 인구 연결 사고연도는 2014~2019년이어야 합니다")
        if year in population:
            raise ValueError(f"부산 {year}년 인구 광역 합계 중복")
        reference_year = _nonnegative_integer(row.get("reference_year"), "인구 기준연도")
        reference_date = f"{year - 1}-12-31"
        if reference_year != year - 1 or row.get("reference_date") != reference_date:
            raise ValueError(f"부산 {year}년 분모는 직전 12월 31일 인구여야 합니다")
        older = _nonnegative_integer(row.get("population_65plus"), "65세 이상 인구")
        total = _nonnegative_integer(row.get("population"), "전체 인구")
        if not 0 < older <= total:
            raise ValueError("인구 분모는 양수이며 65세 이상 인구가 전체보다 클 수 없습니다")
        population[year] = (reference_date, older, total)
    if set(population) != set(YEARS):
        raise ValueError("부산 2014~2019년 인구 광역 합계 누락")
    result = []
    for accident in accidents:
        year, count = accident["year"], accident["busan_count"]
        reference_date, older, total = population[year]
        result.append(
            {
                "year": year,
                "busan_count": count,
                "population_reference_date": reference_date,
                "population_65plus": older,
                "population_total": total,
                "per_10000_65plus": count / older * 10000,
                "per_10000_total": count / total * 10000,
                "population_definition_break": year == 2016,
            }
        )
    return result


def _relative(path):
    """심볼릭 링크 해석 없이 실제 호출 경로를 프로젝트 상대경로로 보존한다."""
    return Path(os.path.relpath(os.path.abspath(path), PROJECT_ROOT)).as_posix()


def _command(raw_arguments):
    arguments = []
    path_follows = False
    for argument in raw_arguments:
        if path_follows:
            arguments.append(_relative(argument))
            path_follows = False
        elif argument.startswith("--") and "=" in argument:
            flag, value = argument.split("=", 1)
            arguments.append(flag + "=" + _relative(value))
        else:
            arguments.append(argument)
            path_follows = argument in {
                "--accidents",
                "--population",
                "--output-dir",
                "--series-output",
                "--manifest-output",
            }
    # resolve()하면 venv symlink가 패키지 없는 기반 Python으로 바뀔 수 있다.
    return shlex.join([_relative(sys.executable), _relative(__file__), *arguments])


def _validate_output_paths(inputs, outputs):
    """쓰기 전에 기존 case 파일과 출력 상호 별칭을 거부한다."""
    owned = {
        HERE / "figures" / FIGURE_NAME,
        HERE / "data/population-descriptive-series.csv",
        HERE / "population-descriptive-manifest.json",
    }
    # 호출자가 지정한 outputs는 예외 목록이 아니다. 이 CLI 소유의 고정 경로만
    # 재생성할 수 있고, 그 경로도 다른 파일의 링크이면 덮어쓰지 않는다.
    protected = [*inputs, FONT_PATH]
    for path in HERE.rglob("*"):
        if path.is_file() and (path not in owned or path.is_symlink() or path.stat().st_nlink != 1):
            protected.append(path)
    resolved_outputs = [path.resolve() for path in outputs]
    for output, resolved in zip(outputs, resolved_outputs, strict=False):
        if any(
            resolved == source.resolve()
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
        raise ValueError("설치된 한글 폰트를 찾을 수 없습니다; 다운로드하지 않습니다")
    font = ft2font.FT2Font(str(FONT_PATH))
    chart_text = "".join(
        (
            TITLE,
            SUBTITLE,
            *PANEL_TITLES,
            *Y_LABELS,
            POLICY_NOTE,
            DEFINITION_NOTE,
            DENOMINATOR_NOTE,
            INTERPRETATION_NOTE,
            SOURCE_NOTE,
            "연도 (연간)0123456789,.?=~",
        )
    )
    missing = sorted(
        {
            character
            for character in chart_text
            if not character.isspace() and ord(character) not in font.get_charmap()
        }
    )
    if missing:
        raise ValueError("한글 폰트 glyph 누락: " + "".join(missing))
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
    blue = "#1768B2"
    years = [row["year"] for row in series]
    with plt.rc_context(style), warnings.catch_warnings():
        warnings.filterwarnings("error", message=r"Glyph .* missing from font.*")
        fig, axes = plt.subplots(1, 2, figsize=(16, 10.5), dpi=160)
        fig.subplots_adjust(left=0.08, right=0.965, bottom=0.315, top=0.745, wspace=0.27)
        fig.text(0.065, 0.945, TITLE, fontsize=29, va="top")
        fig.text(0.065, 0.882, SUBTITLE, fontsize=17, color="#526276")
        for index, ax in enumerate(axes):
            field = "busan_count" if index == 0 else "per_10000_65plus"
            values = [row[field] for row in series]
            ax.set_title(PANEL_TITLES[index], loc="left", fontsize=22, pad=25)
            ax.axvspan(2017.55, 2018.45, color="#E7EBF0", alpha=0.8, zorder=0)
            ax.text(
                2018,
                0.975,
                POLICY_NOTE,
                transform=ax.get_xaxis_transform(),
                ha="center",
                va="top",
                fontsize=12,
                color="#526276",
            )
            segments = ((0, len(series)),) if index == 0 else ((0, 2), (2, len(series)))
            for start, stop in segments:
                ax.plot(
                    years[start:stop],
                    values[start:stop],
                    color=blue,
                    linewidth=3.2,
                    marker="o",
                    markersize=8,
                    zorder=3,
                )
            for year, value in zip(years, values, strict=False):
                label = f"{value:,}" if index == 0 else f"{value:.1f}"
                ax.annotate(
                    label,
                    (year, value),
                    xytext=(0, 13),
                    textcoords="offset points",
                    ha="center",
                    fontsize=16,
                    color=blue,
                )
            if index == 1:
                ax.axvline(2015.5, color="#8C95A2", linewidth=1.2, linestyle=":", zorder=1)
            unit = 200 if index == 0 else 4
            ymax = math.ceil(max(values) * 1.33 / unit) * unit
            ax.set_ylim(0, ymax)
            ax.set_xlim(2013.6, 2019.4)
            ax.set_ylabel(Y_LABELS[index], fontsize=15, labelpad=15)
            ax.set_xticks(years)
            ax.set_xlabel("연도 (연간)", labelpad=13)
            ax.yaxis.set_major_locator(ticker.MaxNLocator(nbins=6, integer=True))
            ax.yaxis.set_major_formatter(ticker.StrMethodFormatter("{x:,.0f}"))
            ax.grid(axis="y", color="#DCE1E7", linewidth=0.8, zorder=0)
            ax.tick_params(axis="both", labelsize=15, length=0, pad=9)
        fig.text(0.575, 0.225, DEFINITION_NOTE, fontsize=14, color="#526276")
        fig.text(0.065, 0.166, DENOMINATOR_NOTE, fontsize=15, color="#344457")
        fig.text(0.065, 0.119, INTERPRETATION_NOTE, fontsize=16, color="#344457")
        fig.text(0.065, 0.065, SOURCE_NOTE, fontsize=12, color="#526276")
        try:
            fig.savefig(
                path, dpi=160, metadata={"Software": "TAAS population descriptive local draft"}
            )
        finally:
            plt.close(fig)
    return {
        "matplotlib_version": matplotlib.__version__,
        "font_name": font_name,
        "font_file": FONT_PATH.name,
        "font_file_sha256": _sha256(FONT_PATH),
        "font_glyph_check": "all chart characters present; missing glyph warnings are errors",
        "image_size_pixels": [2560, 1680],
        "backend": "Agg",
        "right_line_segments": [[2014, 2015], [2016, 2017, 2018, 2019]],
        "zero_based_y_axes": True,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accidents", type=Path, default=HERE / "data/taas-national.csv")
    parser.add_argument("--population", type=Path, default=HERE / "data/population.csv")
    parser.add_argument("--output-dir", type=Path, default=HERE / "figures")
    parser.add_argument(
        "--series-output", type=Path, default=HERE / "data/population-descriptive-series.csv"
    )
    parser.add_argument(
        "--manifest-output", type=Path, default=HERE / "population-descriptive-manifest.json"
    )
    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(raw_arguments)
    figure = args.output_dir / FIGURE_NAME
    inputs = [args.accidents, args.population]
    outputs = [figure, args.series_output, args.manifest_output]
    try:
        _validate_output_paths(inputs, outputs)
        input_hashes = [_sha256(path) for path in inputs]
        with (
            args.accidents.open(encoding="utf-8-sig", newline="") as accident_source,
            args.population.open(encoding="utf-8-sig", newline="") as population_source,
        ):
            series = build_population_series(
                csv.DictReader(accident_source), csv.DictReader(population_source)
            )
        for path in outputs:
            path.parent.mkdir(parents=True, exist_ok=True)
        rendering = _render(series, figure)
        with args.series_output.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(series)
        if [_sha256(path) for path in inputs] != input_hashes:
            raise ValueError("실행 중 입력 SHA256가 변경되었습니다")
        manifest = {
            "schema_version": 1,
            "status": "local_draft",
            "descriptive_only": True,
            "analysis_approved": False,
            "publication_approved": False,
            "inputs": [
                {"path": _relative(path), "sha256": digest, "collected_on": "2026-10-27"}
                for path, digest in zip(inputs, input_hashes, strict=False)
            ],
            "code": {"path": _relative(__file__), "sha256": _sha256(Path(__file__))},
            "dependencies": [
                {"path": _relative(path), "sha256": _sha256(path)}
                for path in (HERE / "describe.py", HERE / "population-qc.json")
            ],
            "command": _command(raw_arguments),
            "command_working_directory": "project root",
            "years": list(YEARS),
            "population_reference_dates": [row["population_reference_date"] for row in series],
            "frequency_scale": 10000,
            "metric": "65세 이상 가해운전자(1당사자) 교통사고 연간 건수 및 주민인구 대비 빈도",
            "geography": {
                "accidents": "taas_province=부산 AND taas_district=합계",
                "population": "region_code=2600000000 AND region_name=부산광역시 AND is_province_total=True",
                "hierarchy": "부산 광역 합계 1행/연도만 사용; 하위 지역 재합산 없음",
            },
            "formulas": {
                "per_10000_65plus": "busan_count / population_65plus * 10000",
                "per_10000_total": "busan_count / population_total * 10000",
                "total_population_rate_numerator": "65세 이상 가해운전자 사고; 전 연령 사고 아님",
            },
            "population_definition": "직전 12월 말 주민등록인구, 남녀계, 외국인 제외; 기존 수집 정의 사용",
            "population_definition_break": {
                "first_reference_date": "2015-12-31",
                "first_outcome_year": 2016,
                "definition": "재외국민 포함",
                "size_separately_identified": False,
                "rendering": "2015년과 2016년 사이 선을 연결하지 않고 경계를 표시",
            },
            "known_limits": KNOWN_LIMITS,
            "rendering": rendering,
            "outputs": [
                {"path": _relative(path), "sha256": _sha256(path)}
                for path in (figure, args.series_output)
            ],
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
                    "input_sha256": input_hashes,
                    "outputs": [_relative(path) for path in outputs],
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (OSError, ValueError, RuntimeError, Warning) as error:
        print(f"인구 대비 관측 그래프 생성 실패: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
