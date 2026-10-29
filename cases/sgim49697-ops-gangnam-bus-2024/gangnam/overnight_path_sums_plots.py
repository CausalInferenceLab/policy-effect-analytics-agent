"""공동 표본의 세 구간 성분과 원시 평균 합의 변화율을 나란히 그린다."""

import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .common import sha256, write_json  # noqa: E402
from .overnight_operations_plots import style  # noqa: E402
from .overnight_path_sums import OUT  # noqa: E402


def run():
    style()
    path = OUT / "comparisons.csv"
    audit = json.loads((OUT / "audit.json").read_text())
    if sha256(path) != audit["outputs"][path.name]:
        raise ValueError("경로 합 그림 입력 해시 변경")
    data = pd.read_csv(path)
    fig, axes = plt.subplots(1, 2, figsize=(13.6, 6), sharey=True)
    specs = [("south_three_legs", "남행: 15개 노선·45개 고정 노선/시간", ["22013→22011", "22011→22009", "22009→22007", "세 구간 합"]),
             ("north_three_legs", "북행: 20개 노선·60개 고정 노선/시간", ["22006→22008", "22008→22010", "22010→22012", "세 구간 합"])]
    for axis, (key, title, labels) in zip(axes, specs, strict=True):
        for comparison, label, color, offset in [("summer2024", "2024 여름", "#8a9eac", -.16),
                                                ("post2025_from_pre2024", "2025 여름", "#397b91", .16)]:
            rows = data[data.path.eq(key) & data.comparison.eq(comparison)].set_index("metric").reindex(["leg_0", "leg_1", "leg_2", "sum"])
            if not rows.quality_pass.eq(True).all():
                raise ValueError("보류한 경로 합을 유효한 결과로 그리지 않습니다")
            positions = np.arange(4) + offset
            axis.bar(positions, rows.change_pct, color=color, width=.29, label=label)
            axis.errorbar(positions, rows.change_pct, yerr=[rows.change_pct - rows.week_bootstrap_low,
                          rows.week_bootstrap_high - rows.change_pct], fmt="none", color="#34404b", capsize=3, lw=1)
            for i, row in enumerate(rows.itertuples()):
                y = row.week_bootstrap_high + 1 if row.change_pct >= 0 else row.week_bootstrap_low - 1
                axis.text(i + offset, y, f"{row.change_pct:+.1f}%", ha="center", va="bottom" if row.change_pct >= 0 else "top", fontsize=8)
        axis.axhline(0, color="#888", lw=.8)
        axis.axvline(2.5, color="#bbb", ls=":", lw=1)
        axis.set(title=title, xticks=np.arange(4), xticklabels=labels, ylim=(-62, 63))
        axis.tick_params(axis="x", labelsize=8)
        axis.legend(loc="upper left", fontsize=9)
    axes[0].set_ylabel("2024년 사전 대비 같은 공동 표본의 변화 (%)")
    fig.suptitle("바로 옆 구간까지 합쳐도 남행 감소·북행 증가가 남음", fontsize=15)
    fig.text(.02, .02, "시간대별 구간 평균의 합이며 같은 차량의 실제 경로 소요시간이 아님. 합은 원시 값에서 계산 후 자기 사전 평균으로 정규화.\n"
             "구간별 변화율의 합이 아니며 어느 구간이든 결측이면 공동 셀 전체를 제외. 오차선은 주 재표집 기술적 변동 구간.", fontsize=9)
    fig.tight_layout(rect=(0, .12, 1, .93))
    figure = OUT / "path_components.png"
    fig.savefig(figure, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    write_json(OUT / "figures.json", {"code_sha256": sha256(Path(__file__)), "inputs": {path.name: sha256(path)},
                                      "outputs": {figure.name: sha256(figure)}})
