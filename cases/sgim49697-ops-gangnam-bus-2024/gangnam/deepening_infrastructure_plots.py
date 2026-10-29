"""품질 실패한 작은 노선군까지 포함해 공식 안내군별 변화를 표시한다."""

import json

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .common import sha256, utcnow, write_json  # noqa: E402
from .deepening_infrastructure import OUT  # noqa: E402
from .overnight_operations_plots import style  # noqa: E402


def run():
    style()
    path = OUT / "group_comparisons.csv"
    audit = json.loads((OUT / "group_audit.json").read_text())
    if sha256(path) != audit["outputs"][path.name]:
        raise ValueError("안내군 그림의 원본 집계 해시 변경")
    frame = pd.read_csv(path)
    frame = frame[frame.date_rule.eq("common_partition_dates")]
    groups = ["announced_central", "announced_curb", "not_in_selected_notice_rows", "reference_all13"]
    labels = ["신설 중앙 안내 7개", "가로변 안내 4개", "해당 행 미수록 2개*", "기존 전체 13개"]
    colors = ["#2464a0", "#8d4e91", "#999999", "#222222"]
    fig, axes = plt.subplots(2, 2, figsize=(12, 7), sharex="row")
    for ri, segment in enumerate(["south", "north"]):
        for ci, (comparison, label) in enumerate([("summer2024", "2024년 사전 → 여름"), ("post2025_from_pre2024", "2024년 사전 → 2025년 여름")]):
            ax = axes[ri, ci]
            part = frame[frame.segment.eq(segment) & frame.comparison.eq(comparison)].set_index("group").loc[groups]
            for i, (_, row) in enumerate(part.iterrows()):
                ax.plot([row.week_bootstrap_low, row.week_bootstrap_high], [i, i], color=colors[i], linewidth=2, linestyle="-" if row.quality_pass else "--")
                ax.scatter(row.change_pct, i, marker="o" if row.quality_pass else "x", color=colors[i], s=42, zorder=3)
                ax.annotate(f"{row.change_pct:+.2f}%", (row.change_pct, i), xytext=(0, 9), textcoords="offset points", ha="center", fontsize=9)
            ax.axvline(0, color="#bbbbbb", linewidth=1)
            ax.set_yticks(range(4), labels if ci == 0 else [""] * 4)
            ax.set_ylim(3.6, -.6)
            ax.set_xlim((-65, 3) if segment == "south" else (-3, 80))
            ax.set_title(("남행" if segment == "south" else "북행") + " · " + label)
            ax.set_xlabel("노선·시간별 기준값으로 정규화한 기록의 변화율 (%)")
            ax.grid(axis="x", alpha=.2)
    fig.suptitle("공식 2025년 정류소 안내군으로 다시 본 방향별 변화", fontsize=15)
    fig.text(.5, .02, "같은 관측 날짜 · 주 재표집 기술 구간, 인과 효과·다중비교 보정 아님\n*2개 노선군은 최소 3개 노선 조건 실패. 안내는 실제 경로 노출의 확인이 아님.", ha="center", fontsize=10)
    fig.tight_layout(rect=(0, .08, 1, .94))
    output = OUT / "route_group_changes.png"
    fig.savefig(output, dpi=160)
    plt.close(fig)
    write_json(OUT / "figures.json", dict(created_at=utcnow(), code_sha256=sha256(__file__),
        inputs={path.name: sha256(path)}, outputs={output.name: sha256(output)}))
