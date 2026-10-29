"""고정 도로 집단의 주별 궤적과 2024년 전체 개별 링크의 전환을 그린다."""

import json

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import TwoSlopeNorm  # noqa: E402

from .common import CASE, sha256, write_json  # noqa: E402
from .deepening_transition import MANIFEST, OUT  # noqa: E402
from .overnight_operations_plots import style  # noqa: E402


def run():
    style()
    audit = json.loads((OUT / "audit.json").read_text())
    if sha256(OUT / "weekly.csv") != audit["outputs"]["weekly.csv"] or sha256(MANIFEST) != audit["input_manifest_sha256"]:
        raise ValueError("전환 그림 입력 해시 변경")
    weekly = pd.read_csv(OUT / "weekly.csv", dtype={"link_id": str})
    groups = [("bridge_south", "양재천 주변 남행"), ("bridge_north", "양재천 주변 북행"),
              ("core_south", "강남역 핵심 남행"), ("core_north", "강남역 핵심 북행")]
    fig, axes = plt.subplots(2, 2, figsize=(12.8, 8.6), sharex=True, sharey=True)
    for ax, (group, title) in zip(axes.flat, groups, strict=True):
        for year, color, width in [(2023, "#8a989c", 1.3), (2025, "#3f80a0", 1.5), (2024, "#bd6c36", 2.3)]:
            data = weekly[(weekly.scope == "group") & (weekly.band == "evening") & (weekly.method == "fixed_length_arithmetic")
                          & (weekly.group == group) & (weekly.year == year)].sort_values("relative_week")
            ax.plot(data.relative_week, data.change_from_pre_pct, marker="o", markersize=4, linewidth=width, color=color, label=str(year))
        ax.axhline(0, color="#777", linewidth=.8)
        ax.axvline(-.5, color="#777", linestyle="--", linewidth=1)
        ax.set(title=title, ylabel="같은 해 사전 평균 대비 속도 (%)", xticks=np.arange(-6, 7),
            xlabel="6월 29일 이후 첫 월요일이 속한 주 = 0")
        ax.grid(alpha=.13)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(.5, .945), ncol=3, frameon=False)
    fig.suptitle("전환 주간을 포함한 일반도로 저녁 속도", fontsize=16, y=.985)
    fig.text(.02, .015, "5월 20일~8월 16일 평일·공휴일 제외, 같은 해 5월 20일~6월 28일 평균을 기준. 고정 길이 가중 산술 평균, 주별 관측 3일 미만은 표시하지 않음.\n"
        "주 0은 2023-07-03 / 2024-07-01 / 2025-06-30. 2023년 주 -1에는 6월 29일 이후 이틀도 포함. 다른 연도는 무처치 대조군이 아님.", fontsize=9)
    fig.tight_layout(rect=(0, .085, 1, .90))
    first = OUT / "weekly_group_evening.png"
    fig.savefig(first, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    source = CASE / "results/deepening/road_context/selected_cells.csv"
    parent = json.loads((source.parent / "audit.json").read_text())
    metadata_source = source.parent / "metadata_check.csv"
    for path in [source, metadata_source]:
        if sha256(path) != parent["outputs"][path.name]:
            raise ValueError("전환 그림의 고정 링크 명칭 해시 변경")
    cells = pd.read_csv(source, dtype={"link_id": str})
    columns = ["link_id", "시점명", "종점명"]
    recorded = pd.read_csv(metadata_source, dtype={"link_id": str}).rename(columns={"시점명_original": "시점명", "종점명_original": "종점명"})
    metadata = recorded[columns].drop_duplicates().set_index("link_id")
    if metadata.index.has_duplicates:
        raise ValueError("그림의 원래 링크 명칭 중복")
    data = weekly[(weekly.scope == "link") & (weekly.year == 2024)]
    link_order = [link for group, _ in groups for link in cells[cells.group.eq(group)].link_id.drop_duplicates()]
    weeks = sorted(data.week_start.unique())
    matrix = data.pivot(index="link_id", columns="week_start", values="change_from_pre_pct").reindex(index=link_order, columns=weeks)
    if matrix.shape != (14, 13) or not np.isfinite(matrix).all().all():
        raise ValueError("2024년 전체 링크·주 그림 표본 오류")
    labels = [f"{link} | {metadata.loc[link, '시점명']} → {metadata.loc[link, '종점명']}" for link in link_order]
    limit = max(10, float(np.ceil(np.abs(matrix.to_numpy()).max() / 10) * 10))
    fig, ax = plt.subplots(figsize=(15.8, 8.5))
    im = ax.imshow(matrix.to_numpy(), aspect="auto", cmap="RdBu", norm=TwoSlopeNorm(vmin=-limit, vcenter=0, vmax=limit))
    for row in range(14):
        for col in range(13):
            value = matrix.iloc[row, col]
            ax.text(col, row, f"{value:+.0f}", ha="center", va="center", fontsize=8,
                color="white" if abs(value) > .6 * limit else "#222")
    ax.axvline(5.5, color="#222", linestyle="--", linewidth=1.3)
    for end in [3.5, 7.5, 10.5]:
        ax.axhline(end, color="#fff", linewidth=2)
    ax.set(xticks=np.arange(13), xticklabels=[date[5:] for date in weeks], yticks=np.arange(14), yticklabels=labels,
        xlabel="2024년 주 시작일 · 점선 오른쪽은 7월 1일부터")
    ax.tick_params(axis="y", labelsize=8)
    fig.colorbar(im, ax=ax, pad=.02, label="같은 링크의 사전 저녁 평균 대비 속도 (%)")
    fig.suptitle("주변 도로 내부에서도 변화 방향은 같지 않다", fontsize=16)
    fig.text(.02, .02, "위에서부터 주변 남행 4개 / 주변 북행 4개 / 핵심 남행 3개 / 핵심 북행 3개. 17~19시 같은 셀의 평균, 모든 14개 링크를 공개.\n"
        "수치는 주 평균의 기술적 차이이며 공사 노출·정책 효과의 추정이 아니다. 월별 명칭·길이 일치는 실제 신호·검지 경계 불변을 보장하지 않는다.", fontsize=9)
    fig.tight_layout(rect=(0, .085, 1, .95))
    second = OUT / "weekly_all_links_2024.png"
    fig.savefig(second, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    write_json(OUT / "figures.json", dict(code_sha256=sha256(__file__),
        inputs={"weekly.csv": sha256(OUT / "weekly.csv"), "selected_cells.csv": sha256(source), "metadata_check.csv": sha256(metadata_source)},
        outputs={path.name: sha256(path) for path in [first, second]}))
