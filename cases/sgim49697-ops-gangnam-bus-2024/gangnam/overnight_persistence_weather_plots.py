"""관측 조건을 통과한 날씨 분포 표준화 결과와 실패 조합을 함께 표시한다."""

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .common import CASE, sha256, write_json  # noqa: E402
from .overnight_operations_plots import style  # noqa: E402


def plot():
    out = CASE / "results/overnight/persistence_weather"
    source = out / "comparisons.csv"
    data = pd.read_csv(source)
    data = data[data.band.eq("evening") & data.subset.eq("other_or_unclassified") & data.scheme.eq("rain_temperature")]
    order = ["summer2024", "summer2025", "pre_year_over_year", "post_year_over_year"]
    labels = ["2024 사전→여름", "2025 사전→여름", "2024 사전→2025 사전", "2024 여름→2025 여름"]
    combinations = [(station, offset) for station in [108, 400, 401] for offset in [-1, 0, 1]]
    names = {108: "서울", 400: "강남", 401: "서초"}
    columns = pd.MultiIndex.from_tuples(combinations, names=["station", "alignment_offset"])
    style()
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    palette = plt.get_cmap("RdBu_r").copy()
    palette.set_bad("#e6e8eb")
    for ax, group, title in zip(axes, ["central_south", "central_north"], ["남행: 정책 후보 밖 고정 셀", "북행: 정책 후보 밖 고정 셀"], strict=True):
        part = data[data.group.eq(group)].copy()
        part["shown"] = part.change_pct.where(part.usable_comparison)
        matrix = part.pivot(index="comparison", columns=["station", "alignment_offset"], values="shown").reindex(index=order, columns=columns)
        shown = ax.imshow(matrix, cmap=palette, vmin=-15, vmax=15, aspect="auto")
        for (i, j), value in np.ndenumerate(matrix.to_numpy()):
            ax.text(j, i, "보류" if pd.isna(value) else f"{value:+.2f}%", ha="center", va="center",
                    color="white" if pd.notna(value) and abs(value) > 9 else "#26343e", fontsize=10)
        ax.set(title=title, yticks=np.arange(4), yticklabels=labels, xticks=np.arange(9),
               xticklabels=[f"{names[s]}\n{o:+d}시간" for s, o in combinations])
    fig.suptitle("같은 계절의 연도 간 방향 차이는 9개 기상 조합에서 유지", fontsize=15)
    fig.text(.02, .02, "비·기온 공통 층의 기술 비교. 양쪽 최소 20일·유효 버스 날짜의 80% 보존을 요구하며 실패 조합의 수치는 표시하지 않음.\n"
             "9개 조합은 같은 날짜의 민감도이며 독립 반복 검증이 아님. 공개 참조 기상자료의 공식 역사 QC와 시간 단위 정의는 별도 한계.", fontsize=9)
    fig.tight_layout(rect=(0, .12, .95, .93))
    fig.colorbar(shown, ax=axes, location="right", fraction=.025, pad=.03, label="기록 시간 지수 변화 (%)")
    target = out / "weather_support.png"
    fig.savefig(target, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    write_json(out / "figure.json", {"code_sha256": sha256(Path(__file__)), "input_sha256": sha256(source),
                                    "output": str(target.relative_to(CASE)), "output_sha256": sha256(target)})
