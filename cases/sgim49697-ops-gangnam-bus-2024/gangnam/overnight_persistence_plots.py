"""2024년 고정 셀의 2025년 수준·계절 변화와 관측 유지율을 그린다."""

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .common import CASE, sha256, write_json  # noqa: E402
from .overnight_operations_plots import style  # noqa: E402

OUT = CASE / "results/overnight/persistence"


def save(fig, name, note):
    fig.text(.02, .02, note, fontsize=9, va="bottom")
    fig.tight_layout(rect=(0, .12, 1, .92))
    fig.savefig(OUT / name, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot():
    style()
    source = OUT / "comparisons.csv"
    all_rows = pd.read_csv(source)
    data = all_rows[all_rows.band.eq("evening") & all_rows.cohort.eq("frozen_pre2023_pre2024")
                    & all_rows.subset.eq("other_or_unclassified") & all_rows.aggregation.eq("equal_cells")]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.6))
    for group, label, color in [("central_south", "남행 503개 셀", "#397b91"), ("central_north", "북행 454개 셀", "#cc784a")]:
        d = data[data.group.eq(group)].set_index("comparison")
        values = [d.loc["summer2024", "before_mean"], d.loc["summer2024", "after_mean"],
                  d.loc["summer2025", "before_mean"], d.loc["summer2025", "after_mean"]]
        axes[0].plot(np.arange(4), values, marker="o", color=color, lw=2, label=label)
        for x, value in enumerate(values):
            axes[0].text(x, value + (1.4 if group == "central_north" else -2.2), f"{value:.1f}", ha="center", fontsize=9, color=color)
        offset = -.12 if group == "central_south" else .12
        for i, period in enumerate(["summer2024", "summer2025"]):
            row = d.loc[period]
            axes[1].errorbar(i + offset, row.change_pct,
                            yerr=[[row.change_pct - row.week_bootstrap_low], [row.week_bootstrap_high - row.change_pct]],
                            fmt="o", color=color, capsize=4, label=label if i == 0 else None)
    axes[0].set(title="같은 2024년 셀 기준의 수준", ylabel="기록 시간 지수", xticks=np.arange(4),
                xticklabels=["2024 사전", "2024 여름", "2025 사전", "2025 여름"], ylim=(87, 123))
    axes[0].axhline(100, color="#888", ls="--", lw=1)
    axes[0].legend(loc="upper left", fontsize=9)
    axes[1].set(title="각 연도의 사전→여름 변화", ylabel="변화율 (%)", xticks=[0, 1], xticklabels=["2024년", "2025년"],
                xlim=(-.5, 1.5), ylim=(-12, 17))
    axes[1].axhline(0, color="#888", lw=1)
    axes[1].legend(loc="upper right", fontsize=9)
    fig.suptitle("2025년에도 방향별 수준 차이는 남지만 같은 계절 변화는 작음", fontsize=15)
    save(fig, "persistence_levels.png", "정책 후보 밖 기존 고정 셀·동일한 2024년 사전 기준. 선은 비교 기간 평균을 연결하며 중간 날짜 추정이 아님.\n오차선은 주 재표집 변동 구간. 정책·노선·기상·운임 변화를 분리한 인과 효과 또는 독립 시험이 아님.")

    retention_path = OUT / "pre2025_retention.csv"
    retained = pd.read_csv(retention_path)
    retained = retained[retained.band.eq("evening")]
    table = retained.groupby(["group", "policy_group"]).agg(total=("route", "size"), kept=("pre2025_eligible", "sum"))
    labels = {"curb": "가로변 이동 후보", "dongtan": "동탄 후보", "reverse_evening": "역방향 후보",
              "other_or_unclassified": "기타·분류 미확정"}
    fig, ax = plt.subplots(figsize=(11, 5.6))
    position = np.arange(len(table))
    fraction = 100 * table.kept / table.total
    ax.barh(position, fraction, color="#397b91", label="2025 사전 관측률 80% 이상")
    ax.barh(position, 100 - fraction, left=fraction, color="#cfd5da", label="기준 미달")
    for i, row in enumerate(table.itertuples()):
        ax.text(101.5, i, f"{int(row.kept)}/{int(row.total)}", va="center", fontsize=10)
    ax.set(yticks=position, yticklabels=[f"{'남행' if g == 'central_south' else '북행'} · {labels[p]}" for g, p in table.index],
           xlabel="기존 고정 셀 중 비율 (%)", xlim=(0, 117))
    ax.legend(loc="upper center", bbox_to_anchor=(.5, 1.16), ncol=2, fontsize=9)
    fig.suptitle("정책 후보의 관측 소실은 2025년에도 이어짐", fontsize=15)
    save(fig, "persistence_retention.png", "노선 후보는 역사적 경로로 대조한 현재 ID이며 당시 노선명의 확정 매핑은 아님.\n미달을 운행 중단·승객 소실로 바꾸어 해석하지 않음. 기본 분석은 원래 모든 셀을 유지하며 관측률 실패도 보고.")
    write_json(OUT / "figures.json", {"code_sha256": sha256(Path(__file__)),
                                      "inputs": {p.name: sha256(p) for p in [source, retention_path]},
                                      "outputs": {name: sha256(OUT / name) for name in ["persistence_levels.png", "persistence_retention.png"]}})
