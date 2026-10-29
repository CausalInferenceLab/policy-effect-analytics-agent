"""같은 14개 노선의 양방향 공동 날짜 비교와 기술적 변동 범위를 그린다."""

import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .common import sha256, write_json  # noqa: E402
from .overnight_matched_directions import OUT  # noqa: E402
from .overnight_operations_plots import style  # noqa: E402


def run():
    style()
    path = OUT / "comparisons.csv"
    audit = json.loads((OUT / "audit.json").read_text())
    if sha256(path) != audit["outputs"][path.name]:
        raise ValueError("공동 노선 그림 입력 변경")
    data = pd.read_csv(path)
    labels = {"summer2024": "2024 사전 → 2024 여름", "pre_year_over_year": "2024 사전 → 2025 사전",
              "post2025_from_pre2024": "2024 사전 → 2025 여름",
              "summer2025": "2025 사전 → 2025 여름", "post_year_over_year": "2024 여름 → 2025 여름"}
    fig, axis = plt.subplots(figsize=(11.5, 5.5))
    for segment, label, color, offset in [("south", "남행 22011→22009", "#287c9c", -.12),
                                         ("north", "북행 22008→22010", "#b56535", .12)]:
        rows = data[data.segment.eq(segment)].set_index("comparison").reindex(labels)
        valid = rows.quality_pass.eq(True)
        y = np.arange(len(labels)) + offset
        axis.hlines(y[valid], rows.loc[valid, "week_bootstrap_low"], rows.loc[valid, "week_bootstrap_high"], color=color, lw=2)
        axis.scatter(rows.loc[valid, "change_pct"], y[valid], s=35, color=color, label=label, zorder=3)
        for position, row in zip(y, rows.itertuples(), strict=True):
            if not row.quality_pass:
                axis.text(0, position, "관측 조건 미달", va="center", fontsize=8)
    axis.axvline(0, color="#888", lw=.8)
    axis.axhline(2.5, color="#ccc", lw=.8, ls="--")
    axis.set(yticks=range(len(labels)), yticklabels=list(labels.values()),
             xlabel="각 비교의 앞 기간 대비 기록 운행시간 지수 변화 (%)")
    axis.invert_yaxis()
    axis.legend(loc="lower left", fontsize=9)
    fig.suptitle(f"양쪽 모두 같은 {audit['selected_routes']}개 노선·같은 날짜로 맞춰도 남는 차이", fontsize=15)
    fig.text(.02, .025, "양방향 07~22시 모두 양수인 노선·날짜만 공동 사용하고 17~19시를 비교. 사후 누락 노선은 고정 분모에 유지.\n"
             "선은 개별 주 재표집 변동 구간. 같은 차량의 왕복 비교·정확한 역방향 구간·인과 효과가 아님.", fontsize=9)
    fig.tight_layout(rect=(0, .14, 1, .92))
    figure = OUT / "matched_changes.png"
    fig.savefig(figure, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    write_json(OUT / "figures.json", {"code_sha256": sha256(Path(__file__)), "inputs": {path.name: sha256(path)},
                                      "outputs": {figure.name: sha256(figure)}})
