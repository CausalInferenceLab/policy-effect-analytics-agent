"""구간별 지속성의 위치와 단일 사전 단위 제외 민감도 범위를 표시한다."""

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .common import CASE, sha256, write_json  # noqa: E402
from .overnight_operations_plots import style  # noqa: E402

OUT = CASE / "results/overnight/persistence_segments"
COMPARISONS = ["summer2024", "pre_year_over_year", "post2025_from_pre2024"]
LABELS = ["2024 여름", "2025 사전", "2025 여름"]


def save(fig, name, note):
    fig.text(.02, .02, note, fontsize=9, va="bottom")
    fig.tight_layout(rect=(0, .12, 1, .92))
    fig.savefig(OUT / name, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot():
    style()
    source = OUT / "segment_comparisons.csv"
    data = pd.read_csv(source, dtype={"from_ars": str, "to_ars": str})
    data = data[data.band.eq("evening")]
    fig, axes = plt.subplots(1, 2, figsize=(14, 7.3))
    palette = plt.get_cmap("RdBu_r").copy()
    palette.set_bad("#ddd")
    for ax, group, title in zip(axes, ["central_south", "central_north"], ["남행 인접 구간", "북행 인접 구간"], strict=True):
        part = data[data.group.eq(group)].copy()
        part["shown"] = part.change_pct.where(part.quality_pass)
        matrix = part.pivot(index="from_order", columns="comparison", values="shown").reindex(columns=COMPARISONS).sort_index()
        meta = part.drop_duplicates("from_order").set_index("from_order").reindex(matrix.index)
        ax.imshow(matrix, cmap=palette, vmin=-50, vmax=50, aspect="auto")
        for (i, j), value in np.ndenumerate(matrix.to_numpy()):
            ax.text(j, i, "보류" if pd.isna(value) else f"{value:+.1f}%", ha="center", va="center",
                    color="white" if pd.notna(value) and abs(value) > 30 else "#17252e", fontsize=11)
        labels = [f"{row.from_ars}→{row.to_ars} ({row.selected_routes} ID)" for row in meta.itertuples()]
        ax.set(title=title, xticks=np.arange(3), xticklabels=LABELS, yticks=np.arange(len(matrix)), yticklabels=labels,
               xlabel="모두 같은 2024년 사전 기간 대비")
    fig.suptitle("신분당선강남역으로 향하는 두 방향의 구간은 반대 변화가 지속", fontsize=15)
    save(fig, "segment_levels.png", "정책 후보 밖 인접 구간·고정 사전 셀, 17~19시. 괄호는 사전 선택 노선 ID 수. 빨강은 기록 시간 증가, 파랑은 감소.\n"
         "ARS 22011→22009는 남행 지하철2호선강남역→신분당선강남역, 22008→22010은 북행 래미안아파트·파이낸셜뉴스→신분당선강남역.\n"
         "실제 정차·대기 성분 또는 정책의 인과 효과를 식별한 결과는 아님.")

    influence_path = OUT / "leave_one_out.csv"
    influence = pd.read_csv(influence_path)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.7), sharex=True, sharey=True)
    for ax, group, title in zip(axes, ["central_south", "central_north"], ["남행 500개 셀", "북행 451개 셀"], strict=True):
        part = influence[influence.group.eq(group)]
        for i, comparison in enumerate(COMPARISONS):
            d = part[part.comparison.eq(comparison)]
            full = d[d.omitted_unit.eq("none")].iloc[0]
            ax.scatter(full.change_pct, i, color="#202b33", marker="D", zorder=4, label="전체 인접 표본" if i == 0 else None)
            for unit, offset, color, label in [("segment", -.15, "#397b91", "구간 하나씩 제외한 범위"),
                                                ("route", .15, "#cc784a", "노선 ID 하나씩 제외한 범위")]:
                removed = d[d.omitted_unit.eq(unit)]
                if not removed.quality_pass.all():
                    raise ValueError("제외 민감도 그림 대상에 관측 조건 실패가 있습니다")
                low, high = removed.change_pct.min(), removed.change_pct.max()
                ax.hlines(i + offset, low, high, color=color, lw=4, label=label if i == 0 else None)
                ax.scatter([low, high], [i + offset] * 2, color=color, s=20)
        ax.axvline(0, color="#777", lw=.8)
        ax.set(title=title, yticks=np.arange(3), yticklabels=LABELS, xlabel="2024년 사전 대비 기록 시간 지수 변화 (%)", xlim=(-12, 22), ylim=(2.6, -.6))
    axes[1].legend(loc="lower left", fontsize=9)
    fig.suptitle("단일 구간·노선 ID를 제외해도 같은 기준 대비 방향별 부호 유지", fontsize=15)
    save(fig, "leave_one_out.png", "선은 각 단위를 한 번씩 제외한 결과의 최소~최대이며 신뢰구간이 아님. 모든 표시 민감도가 기존 관측 조건 통과.\n"
         "구간 제외는 남행 크기에 영향을 주지만 부호는 남음. 제외된 단위의 인과 기여·처치 효과로 해석하지 않음.")
    write_json(OUT / "figures.json", {"code_sha256": sha256(Path(__file__)),
                                      "inputs": {p.name: sha256(p) for p in [source, influence_path]},
                                      "outputs": {name: sha256(OUT / name) for name in ["segment_levels.png", "leave_one_out.png"]}})
