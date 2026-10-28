"""승객 기록이 사전에 관측된 제한 집단의 동일 표본 가중 비교를 그린다."""

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

from .common import CASE, sha256, write_json  # noqa: E402

OUT = CASE / "results/overnight/passengers"


def plot():
    for path in [Path("/mnt/c/Windows/Fonts/malgun.ttf"), Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")]:
        if path.exists():
            font_manager.fontManager.addfont(str(path))
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(path)).get_name()
            break
    plt.rcParams.update({"axes.unicode_minus": False, "axes.spines.top": False, "axes.spines.right": False, "font.size": 10})
    source = OUT / "covered_comparisons.csv"
    data = pd.read_csv(source)
    data = data[data.subset.eq("all_preselected") & data.band.eq("evening") & data.quality_pass]
    fig, axes = plt.subplots(1, 2, figsize=(11, 5), sharey=True)
    for ax, period, title in zip(axes, ["summer2024", "autumn2024"], ["2024 여름", "2024 가을"], strict=True):
        for offset, method, name, color in [(-.18, "equal_cells_same_covered", "같은 셀 평균", "#7396aa"),
                                          (.18, "fixed_pre_passengers_same_covered", "사전 승객 기록 가중", "#cd895f")]:
            values = data[data.comparison.eq(period) & data.method.eq(method)].set_index("group").reindex(["central_south", "central_north"])
            bars = ax.bar(np.arange(2) + offset, values.change_pct, width=.34, label=name, color=color)
            ax.bar_label(bars, fmt="%+.2f%%", padding=4)
        ax.set(title=title, xticks=np.arange(2), xticklabels=["남행 315개 셀", "북행 318개 셀"], ylim=(-13, 17))
        ax.axhline(0, color="#888888", lw=.8)
        ax.legend(fontsize=9)
    axes[0].set_ylabel("사전 대비 기록 시간 지수 변화 (%)")
    fig.suptitle("승객 기록이 있는 제한 집단에서도 남행·북행의 부호는 유지", fontsize=15)
    fig.text(.02, .015, "전체 사전 셀의 남행 47.9%·북행 63.6%만 포함. 같은 셀·유효 날짜 비교이며 전체 승객 편익이나 분 단위 통행시간이 아님.", fontsize=9, color="#4b5563")
    fig.tight_layout(rect=(0, .1, 1, .94))
    target = OUT / "covered_weight_comparison.png"
    fig.savefig(target, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    write_json(OUT / "covered_figures.json", {"code_sha256": sha256(Path(__file__)), "input_sha256": sha256(source),
        "figures": {target.name: sha256(target)}})
