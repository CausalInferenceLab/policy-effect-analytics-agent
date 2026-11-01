"""기존 TAAS 연간 합계로 두 관측 그래프를 만드는 로컬 시안 CLI.

정책 효과를 추정하지 않는다. 집계 함수는 표준 라이브러리만 사용하며,
matplotlib과 설치된 한글 폰트는 렌더링할 때만 불러온다.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shlex
import sys
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
YEARS = tuple(range(2014, 2020))
BASE_YEAR = 2017
FIELDS = ("year", "busan_count", "national_count", "rest_count", "busan_index", "rest_index")
FIGURE_NAMES = ("01_busan_counts.png", "02_busan_vs_rest_counts.png")
FONT_PATH = Path("/System/Library/Fonts/Supplemental/AppleGothic.ttf")
TITLES = (
    "부산의 고령운전자 사고건수는 어떻게 변했나?",
    "부산과 다른 지역은 같은 방향으로 움직였나?",
)
SUBTITLES = (
    "65세 이상 가해운전자 사고 · 2014~2019년 연간 집계",
    "65세 이상 가해운전자 사고건수 지수 · 각 지역의 2017년=100",
)
POLICY_NOTE = "정책 시작: 2018년 7월\n2018년은 시행 전·후 혼재"
NORMALIZATION_NOTE = "2017년=100은 규모를 맞춘 값 · 인구·운전량 미보정"
OBSERVATION_NOTE = "관측 변화이며 정책 효과 추정이 아닙니다"
COMPARISON_NOTE = "다른 지역에도 관련 정책이 포함될 수 있어 대조군이 아닙니다"
SOURCE_NOTE = "출처: TAAS 65세 이상 가해운전자 사고 · 기존 자료 수집일: 2026-10-27 · 로컬 시안"
REST_LABEL = "전국에서 부산을 제외한 지역"
KNOWN_LIMITS = [
    "사고건수는 사망자 수가 아니며 사망자 35→18 보도를 검증하거나 반증하지 않는다.",
    "인구·운전자 수·운전량으로 보정하지 않은 연간 사고건수다.",
    "2017년=100은 각 계열의 크기를 맞추는 정규화이며 정책 효과 지수가 아니다.",
    "다른 지역의 관련 정책 시행 여부를 검증하지 않았으며 미처치·대조군이 아니다.",
    "2018년은 7월 정책 시작으로 시행 전·후가 혼재한 연간 집계이며 월별 효과를 구분할 수 없다.",
    "2019년 11월 안전속도 5030 등 동시 정책의 영향을 분리하지 않았다.",
    "정책이 없었을 반사실과 인과효과를 추정하지 않았다.",
    "TAAS 자료 이용조건 및 공개 전 검토가 끝나지 않은 로컬 시안이다.",
]


def _nonnegative_integer(value, label):
    if not isinstance(value, str) or re.fullmatch(r"[0-9]+", value) is None:
        raise ValueError(f"{label}: 음수·비정수·누락 값은 허용하지 않습니다")
    return int(value)


def build_series(rows, base_year=2017):
    """정확한 전국·부산 합계 6행씩만 골라 연도순 관측 계열을 반환한다."""
    if type(base_year) is not int or base_year != BASE_YEAR:
        raise ValueError("기준연도는 정수 2017로 고정합니다")
    aggregates = {"합계": {}, "부산": {}}
    for row in rows:
        province = row.get("taas_province")
        if province not in aggregates or row.get("taas_district") != "합계":
            continue
        year = _nonnegative_integer(row.get("year"), f"{province} 연도")
        if year not in YEARS:
            raise ValueError(f"{province}: 2014~2019년 밖의 합계행 {year}")
        if year in aggregates[province]:
            raise ValueError(f"{province}: {year}년 합계행 중복")
        aggregates[province][year] = _nonnegative_integer(
            row.get("older_accidents"), f"{province} {year}년 사고건수"
        )
    for province, values in aggregates.items():
        if set(values) != set(YEARS):
            raise ValueError(f"{province}: 2014~2019년 합계행 누락")

    busan = aggregates["부산"]
    national = aggregates["합계"]
    if any(national[year] < busan[year] for year in YEARS):
        raise ValueError("전국 사고건수는 부산 사고건수보다 작을 수 없습니다")
    rest = {year: national[year] - busan[year] for year in YEARS}
    if busan[base_year] == 0 or rest[base_year] == 0:
        raise ValueError("2017년 지수의 기준 사고건수는 0일 수 없습니다")
    return [
        {
            "year": year,
            "busan_count": busan[year],
            "national_count": national[year],
            "rest_count": rest[year],
            "busan_index": busan[year] / busan[base_year] * 100,
            "rest_index": rest[year] / rest[base_year] * 100,
        }
        for year in YEARS
    ]


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(path):
    """Manifest 경로는 프로젝트 루트 기준 상대경로로만 기록한다."""
    return Path(os.path.relpath(path.resolve(), PROJECT_ROOT)).as_posix()


def _command(raw_arguments):
    arguments = []
    path_follows = False
    for argument in raw_arguments:
        if path_follows:
            arguments.append(_relative(Path(argument)))
            path_follows = False
        elif argument.startswith("--") and "=" in argument:
            flag, value = argument.split("=", 1)
            arguments.append(flag + "=" + _relative(Path(value)))
        else:
            arguments.append(argument)
            path_follows = argument in {
                "--input",
                "--output-dir",
                "--series-output",
                "--manifest-output",
            }
    # 가상환경의 symlink를 resolve하면 패키지가 없는 기반 Python으로 바뀐다.
    interpreter = Path(os.path.relpath(sys.executable, PROJECT_ROOT)).as_posix()
    return shlex.join([interpreter, _relative(Path(__file__)), *arguments])


def _render(series, output_paths):
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import font_manager, ft2font, ticker
    from matplotlib import pyplot as plt

    if not FONT_PATH.is_file():
        raise ValueError("설치된 한글 폰트를 찾을 수 없습니다; 다운로드하지 않습니다")
    font = ft2font.FT2Font(str(FONT_PATH))
    chart_text = "".join(
        (
            *TITLES,
            *SUBTITLES,
            POLICY_NOTE,
            OBSERVATION_NOTE,
            COMPARISON_NOTE,
            NORMALIZATION_NOTE,
            SOURCE_NOTE,
            REST_LABEL,
            "부산연도(연간)사고건수(건)사고건수 지수 (2017년=100)",
            "0123456789,.?=~",
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
    blue, other = "#1768B2", "#A66A16"
    years = [row["year"] for row in series]
    with plt.rc_context(style), warnings.catch_warnings():
        warnings.filterwarnings("error", message=r"Glyph .* missing from font.*")
        for index, path in enumerate(output_paths):
            fig, ax = plt.subplots(figsize=(16, 10), dpi=140)
            fig.subplots_adjust(left=0.105, right=0.95, bottom=0.265, top=0.765)
            fig.text(0.085, 0.925, TITLES[index], fontsize=27, va="top")
            fig.text(0.085, 0.866, SUBTITLES[index], fontsize=17, color="#526276")
            if index == 1:
                fig.text(0.085, 0.815, NORMALIZATION_NOTE, fontsize=15, color="#526276")
            ax.axvspan(2017.55, 2018.45, color="#E7EBF0", alpha=0.8, zorder=0)
            ax.text(
                2018,
                0.965,
                POLICY_NOTE,
                transform=ax.get_xaxis_transform(),
                ha="center",
                va="top",
                fontsize=14,
                color="#526276",
            )
            if index == 0:
                values = [row["busan_count"] for row in series]
                ax.plot(
                    years, values, color=blue, linewidth=3.2, marker="o", markersize=9, zorder=3
                )
                ymax = math.ceil(max(values) * 1.24 / 200) * 200
                for year, value in zip(years, values, strict=False):
                    ax.annotate(
                        f"{value:,}",
                        (year, value),
                        xytext=(0, 14),
                        textcoords="offset points",
                        ha="center",
                        fontsize=17,
                        color=blue,
                    )
                ax.set_ylabel("사고건수 (건)", labelpad=15)
                ax.yaxis.set_major_formatter(ticker.StrMethodFormatter("{x:,.0f}"))
            else:
                busan = [row["busan_index"] for row in series]
                rest = [row["rest_index"] for row in series]
                ax.axhline(100, color="#909CAB", linewidth=1.2, linestyle=":", zorder=1)
                ax.plot(
                    years,
                    busan,
                    color=blue,
                    linewidth=3.2,
                    marker="o",
                    markersize=9,
                    label="부산",
                    zorder=3,
                )
                ax.plot(
                    years,
                    rest,
                    color=other,
                    linewidth=2.8,
                    marker="s",
                    markersize=8,
                    linestyle="--",
                    label=REST_LABEL,
                    zorder=2,
                )
                ymax = math.ceil(max(*busan, *rest) * 1.32 / 20) * 20
                ax.set_ylabel("사고건수 지수 (2017년=100)", labelpad=15)
                ax.legend(
                    loc="upper left",
                    frameon=False,
                    fontsize=15,
                    handlelength=2.7,
                    borderaxespad=0.4,
                )
            ax.set_ylim(0, ymax)
            ax.set_xlim(2013.65, 2019.35)
            ax.set_xticks(years)
            ax.set_xlabel("연도 (연간)", labelpad=15)
            ax.yaxis.set_major_locator(ticker.MaxNLocator(nbins=6, integer=True))
            ax.grid(axis="y", color="#DCE1E7", linewidth=0.8, zorder=0)
            ax.tick_params(axis="both", labelsize=16, length=0, pad=10)
            fig.text(0.085, 0.155, OBSERVATION_NOTE, fontsize=16, color="#344457")
            if index == 1:
                fig.text(0.085, 0.111, COMPARISON_NOTE, fontsize=14, color="#526276")
            fig.text(0.085, 0.065, SOURCE_NOTE, fontsize=12, color="#526276")
            try:
                fig.savefig(path, dpi=140, metadata={"Software": "TAAS descriptive local draft"})
            finally:
                plt.close(fig)
    return {
        "matplotlib_version": matplotlib.__version__,
        "font_name": font_name,
        "font_file": FONT_PATH.name,
        "font_file_sha256": _sha256(FONT_PATH),
        "font_glyph_check": "all chart characters present",
        "image_size_pixels": [2240, 1400],
        "backend": "Agg",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=HERE / "data/taas-national.csv")
    parser.add_argument("--output-dir", type=Path, default=HERE / "figures")
    parser.add_argument("--series-output", type=Path, default=HERE / "data/descriptive-series.csv")
    parser.add_argument("--manifest-output", type=Path, default=HERE / "descriptive-manifest.json")
    raw_arguments = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(raw_arguments)
    figure_paths = [args.output_dir / name for name in FIGURE_NAMES]
    outputs = [*figure_paths, args.series_output, args.manifest_output]
    try:
        resolved_outputs = [path.resolve() for path in outputs]
        if args.input.resolve() in resolved_outputs or any(
            path.exists() and path.samefile(args.input) for path in outputs
        ):
            raise ValueError("입력 원본을 출력으로 덮어쓸 수 없습니다")
        if len(set(resolved_outputs)) != len(outputs):
            raise ValueError("출력 파일 경로는 서로 달라야 합니다")
        input_hash = _sha256(args.input)
        with args.input.open(encoding="utf-8-sig", newline="") as source:
            series = build_series(csv.DictReader(source))
        for path in outputs:
            path.parent.mkdir(parents=True, exist_ok=True)
        render_metadata = _render(series, figure_paths)
        with args.series_output.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(series)
        if _sha256(args.input) != input_hash:
            raise ValueError("실행 중 입력 SHA256가 변경되었습니다")
        manifest = {
            "schema_version": 1,
            "status": "local_draft",
            "descriptive_only": True,
            "analysis_approved": False,
            "publication_approved": False,
            "input": {
                "path": _relative(args.input),
                "sha256": input_hash,
                "collected_on": "2026-10-27",
            },
            "code": {"path": _relative(Path(__file__)), "sha256": _sha256(Path(__file__))},
            "command": _command(raw_arguments),
            "command_working_directory": "project root",
            "years": list(YEARS),
            "base_year": BASE_YEAR,
            "metric": "65세 이상 가해운전자(1당사자) 교통사고 연간 건수",
            "geography": {
                "busan": "taas_province=부산 AND taas_district=합계",
                "national": "taas_province=합계 AND taas_district=합계",
                "rest": "전국 합계 - 부산 합계; 하위 지역 재합산 없음",
            },
            "index_definition": "각 계열의 해당 연도 건수 / 같은 계열의 2017년 건수 × 100",
            "known_limits": KNOWN_LIMITS,
            "rendering": render_metadata,
            "outputs": [
                {"path": _relative(path), "sha256": _sha256(path)}
                for path in [*figure_paths, args.series_output]
            ],
            "manifest_hash_note": "자기 참조 해시는 포함하지 않으며 독립 실행 증거에 별도 기록한다.",
        }
        args.manifest_output.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "status": "local_draft",
                    "rows": len(series),
                    "input_sha256": input_hash,
                    "outputs": [_relative(path) for path in outputs],
                },
                ensure_ascii=False,
            )
        )
        return 0
    except (OSError, ValueError, RuntimeError, Warning) as error:
        print(f"관측 그래프 생성 실패: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
