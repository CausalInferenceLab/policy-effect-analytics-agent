"""끝점 이름 변화 허용 여부에 따른 도로별 요약의 민감도를 그린다."""

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .common import CASE, sha256, write_json  # noqa: E402
from .overnight_operations_plots import style  # noqa: E402


def plot():
    out = CASE / "results/overnight/road_names_sensitivity"
    source = out / "strict_vs_names.csv"
    data = pd.read_csv(source)
    data = data[data.scope.eq("road_stable_subset") & data.band.eq("evening")
                & data.method.eq("fixed_length_arithmetic")]
    groups = sorted(data.group.unique())
    style()
    fig, axes = plt.subplots(1, 2, figsize=(13, 7.5), sharey=True)
    for ax, period, title in zip(axes, ["summer2024", "autumn2024"], ["2024 여름", "2024 가을"], strict=True):
        selected = data[data.comparison.eq(period)].set_index("group").reindex(groups)
        if not selected.both_quality_pass.all():
            raise ValueError("그림 대상에 관측 조건 실패 또는 누락된 도로가 있습니다")
        positions = np.arange(len(groups))
        for i, row in enumerate(selected.itertuples()):
            ax.plot([row.change_pct_strict, row.change_pct_names_allowed], [i, i], color="#b7bfc4", lw=2)
        ax.scatter(selected.change_pct_strict, positions, color="#397b91", label="끝점 이름 유지", zorder=3)
        ax.scatter(selected.change_pct_names_allowed, positions, color="#cc784a", marker="D", label="이름 변화 허용", zorder=3)
        labels = [f"{group.replace('|', ' ')} ({int(row.selected_links_strict)}→{int(row.selected_links_names_allowed)}개)"
                  for group, row in zip(groups, selected.itertuples(), strict=True)]
        ax.set(title=title, xlabel="사전 대비 저녁 속도 변화 (%)", xlim=(-13, 6), yticks=positions, yticklabels=labels)
        ax.axvline(0, color="#777", lw=.8)
        ax.legend(loc="lower left", fontsize=9)
    axes[0].invert_yaxis()
    fig.suptitle("주변 도로의 일부 요약은 링크 포함 기준에 민감", fontsize=15)
    fig.text(.02, .025, "같은 링크 ID·도로명·방향·길이를 유지하고 끝점 이름 변화만 허용한 가정적 민감도.\n"
             "동일 공간이라는 확인은 아니며, 0 근처 부호 변화는 통계적으로 확정된 차이를 뜻하지 않음.", fontsize=9)
    fig.tight_layout(rect=(0, .10, 1, .94))
    image = out / "names_sensitivity.png"
    fig.savefig(image, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    write_json(out / "figure.json", {"code_sha256": sha256(Path(__file__)),
                                    "input": str(source.relative_to(CASE)), "input_sha256": sha256(source),
                                    "output": str(image.relative_to(CASE)), "output_sha256": sha256(image)})
