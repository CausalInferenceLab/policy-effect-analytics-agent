"""같은 계절 창의 버스 기록·핵심 도로 속도·교통량을 서로 다른 측정으로 나누어 그린다."""

import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .common import CASE, sha256, write_json  # noqa: E402
from .overnight_operations_plots import style  # noqa: E402

OUT = CASE / "results/overnight/road_persistence"


def checked_csv(path, audit_name="audit.json"):
    audit = json.loads((path.parent / audit_name).read_text())
    if sha256(path) != audit["outputs"][path.name]:
        raise ValueError("그림 입력 비교표의 해시 불일치")
    return pd.read_csv(path)


def levels(frame):
    values = frame.set_index("comparison")
    if not values.quality_pass.all():
        raise ValueError("그림 대상에 보류된 비교가 있습니다")
    baseline = values.loc["summer2024", "before_mean"]
    return [100., *[100 * values.loc[name, "after_mean"] / baseline
                   for name in ["summer2024", "pre_year_over_year", "post_year_over_year"]]]


def plot():
    style()
    roads = checked_csv(OUT / "comparisons.csv")
    bus = checked_csv(CASE / "results/overnight/persistence/comparisons.csv")
    bus = bus[bus.band.eq("evening") & bus.cohort.eq("frozen_pre2023_pre2024")
              & bus.subset.eq("other_or_unclassified") & bus.aggregation.eq("equal_cells")]
    roads = roads[roads.band.eq("evening") & ~roads.method.eq("equal_cells")]
    fig, axes = plt.subplots(1, 3, figsize=(16, 5.8))
    x = np.arange(4)
    for group, label, color in [("south", "남행", "#397b91"), ("north", "북행", "#cc784a")]:
        axes[0].plot(x, levels(bus[bus.group.eq("central_" + group)]), marker="o", color=color, label=label)
        axes[1].plot(x, levels(roads[roads.scope.eq("core") & roads.group.eq(group)]), marker="o", color=color, label=label)
    for group, label, color, marker in [("D-35|유입", "D-35 북행", "#cc784a", "o"), ("D-35|유출", "D-35 남행", "#397b91", "o"),
                                        ("D-43|유입", "D-43 북행", "#bb9b37", "s"), ("D-43|유출", "D-43 남행", "#6d6292", "s")]:
        axes[2].plot(x, levels(roads[roads.scope.eq("point") & roads.group.eq(group)]), marker=marker, color=color, label=label)
    for ax, title in zip(axes, ["버스 기록 시간\n낮을수록 짧음", "일반도로 핵심 3개 링크 속도\n높을수록 빠름", "검지지점 시간당 교통량\n통과 대수"], strict=True):
        ax.set(title=title, xticks=x, xticklabels=["24 사전", "24 여름", "25 사전", "25 여름"], ylabel="각 자료의 2024년 사전 평균 = 100")
        ax.axhline(100, color="#888", lw=1, ls="--")
        ax.legend(fontsize=9)
    fig.suptitle("버스의 방향별 변화는 주변 도로·교통량과 같은 모양으로 움직이지 않음", fontsize=15)
    fig.text(.02, .02, "저녁 17~19시, 같은 평일·공휴일 창. 버스는 정책 후보 밖 고정 셀, 일반도로는 교보~뱅뱅, 교통량은 고정 검지지점.\n공간·자료·단위가 다르며 같은 차량·승객을 연결한 결과가 아님. 선은 기간 평균 연결이며 연속 경로·인과 효과를 뜻하지 않음.", fontsize=10)
    fig.tight_layout(rect=(0, .14, 1, .92))
    fig.savefig(OUT / "transport_context_levels.png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 6))
    data = roads[roads.comparison.eq("pre_year_over_year")]
    groups = [("core", "south", "핵심 3개 남행"), ("road_stable_subset", "강남대로|하행", "강남대로 15개 남행"),
              ("core", "north", "핵심 3개 북행"), ("road_stable_subset", "강남대로|상행", "강남대로 15개 북행")]
    for y, (scope, group, _label) in enumerate(groups):
        row = data[data.scope.eq(scope) & data.group.eq(group)].iloc[0]
        color = "#397b91" if y < 2 else "#cc784a"
        ax.hlines(y, row.week_bootstrap_low, row.week_bootstrap_high, lw=3, color=color)
        ax.scatter(row.change_pct, y, color=color, zorder=3)
        ax.annotate(f"{row.change_pct:+.2f}%", (row.change_pct, y), xytext=(0, 10), textcoords="offset points", ha="center")
    ax.axvline(0, color="#888", lw=1)
    ax.set(yticks=np.arange(4), yticklabels=[item[2] for item in groups], xlabel="2024 사전 대비 2025 사전 속도 변화 (%)", ylim=(-.6, 3.6))
    ax.invert_yaxis()
    fig.suptitle("같은 강남대로도 공간 범위를 넓히면 남행 속도의 변화 방향이 달라짐", fontsize=14)
    fig.text(.02, .025, "고정 링크 길이 가중 산술평균, 저녁 17~19시. 점은 변화율, 선은 달력 주 재표집 95% 구간.\n핵심 3개 링크는 15개 링크에 포함되므로 두 표본은 독립이 아니며, 도로 전체의 정책 효과를 뜻하지 않음.", fontsize=10)
    fig.tight_layout(rect=(0, .14, 1, .93))
    fig.savefig(OUT / "road_spatial_scope.png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    paths = [OUT / "comparisons.csv", CASE / "results/overnight/persistence/comparisons.csv"]
    write_json(OUT / "figures.json", {"code_sha256": sha256(Path(__file__)), "inputs": {str(path.relative_to(CASE)): sha256(path) for path in paths},
                                      "outputs": {name: sha256(OUT / name) for name in ["transport_context_levels.png", "road_spatial_scope.png"]}})
