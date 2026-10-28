"""주변 지하철 승차의 연도별 여름 비교와 모든 선택 역의 월별 변화를 그린다."""

import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .common import read_yaml, sha256, write_json  # noqa: E402
from .overnight_operations_plots import style  # noqa: E402
from .overnight_subway_data import OUT  # noqa: E402


def run():
    style()
    cfg = read_yaml("overnight_subway_config.yaml")
    audit = json.loads((OUT / "audit.json").read_text())
    paths = [OUT / name for name in ["daily_comparisons.csv", "monthly_changes.csv"]]
    if any(sha256(path) != audit["outputs"][path.name] for path in paths):
        raise ValueError("지하철 그림 입력 해시 변경")
    daily, monthly = [pd.read_csv(path) for path in paths]
    selected = daily[daily.flow.eq("boardings")]
    primary = [s["key"] for s in cfg["stations"] if s["role"] == "primary"]
    names = {s["key"]: s["base_name"] + " " + s["line"] for s in cfg["stations"]}
    fig, axes = plt.subplots(1, 2, figsize=(12.8, 5.5))
    for axis, contrasts, title in [
        (axes[0], [("summer2023", "2023", "#8a9eac", -.23), ("summer2024", "2024", "#cc784a", 0), ("summer2025", "2025", "#397b91", .23)], "각 연도의 사전→여름"),
        (axes[1], [("pre2025_from_pre2024", "사전 창", "#397b91", -.13), ("post2025_from_post2024", "여름 창", "#cc784a", .13)], "2024→2025 같은 계절")]:
        for comparison, label, color, offset in contrasts:
            rows = selected[selected.comparison.eq(comparison)].set_index("station").reindex(primary)
            if not rows.quality_pass.eq(True).all():
                raise ValueError("보류한 지하철 변화를 그림에서 채택하지 않습니다")
            positions = np.arange(len(primary)) + offset
            axis.errorbar(positions, rows.change_pct, yerr=[rows.change_pct - rows.week_bootstrap_low,
                          rows.week_bootstrap_high - rows.change_pct], fmt="o", capsize=4, color=color, label=label)
        axis.axhline(0, color="#888", lw=.8)
        axis.set(title=title, xticks=np.arange(len(primary)), xticklabels=[names[k] for k in primary],
                 ylabel="평일 하루 승차 기록 변화 (%)", xlim=(-.5, 2.5), ylim=(-14, 10))
        axis.legend(ncol=len(contrasts), loc="upper right", fontsize=9)
    fig.suptitle("주변 지하철의 변화는 역·계절마다 다르며 버스의 방향별 변화와 동일하지 않음", fontsize=14)
    fig.text(.02, .02, "사전 5/20~6/28, 여름 7/8~8/16, 주말·공휴일 제외. 주 재표집 변동 구간.\n"
             "역·호선별 카드 기록이며 신분당선은 미제공. 같은 사람의 버스→철도 전환이나 정책 효과를 추정하지 않음.", fontsize=9)
    fig.tight_layout(rect=(0, .12, 1, .93))
    fig.savefig(OUT / "daily_context.png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    selected = monthly[monthly.flow.eq("boardings") & monthly.band.eq("evening") & monthly.after_month.str.startswith("2025")]
    if not selected.quality_pass.eq(True).all():
        raise ValueError("보류한 지하철 월 비교가 있습니다")
    station_order = [s["key"] for s in cfg["stations"]]
    frame = selected.pivot(index="station", columns="after_month", values="change_pct").reindex(station_order)
    fig, axis = plt.subplots(figsize=(11.7, 6.4))
    limit = max(20, float(np.abs(frame.to_numpy()).max()))
    mesh = axis.imshow(frame, cmap="RdBu_r", vmin=-limit, vmax=limit, aspect="auto")
    for i in range(len(frame)):
        for j in range(len(frame.columns)):
            value = frame.iloc[i, j]
            axis.text(j, i, f"{value:+.1f}", ha="center", va="center", fontsize=10,
                      color="white" if abs(value) > limit * .65 else "#202b32")
    axis.set(xticks=np.arange(8), xticklabels=[f"{i}월" for i in range(1, 9)], yticks=np.arange(8),
             yticklabels=[names[k] for k in station_order], title="2025년 저녁 승차: 같은 월의 2024년 대비 달력 하루 평균 변화")
    fig.colorbar(mesh, ax=axis, label="변화 (%)")
    fig.text(.02, .02, "17~19시, 월 전체 날짜 합계 ÷ 달력 일수. 주말·공휴일 구성은 보정하지 않음.\n"
             "8개 역 전체를 표시하며 1~2월 변화를 정책 효과로 해석하지 않음. 일별 합과 24시간 합은 384개 조합 모두 정확 일치.", fontsize=9)
    fig.tight_layout(rect=(0, .11, 1, .97))
    fig.savefig(OUT / "monthly_context.png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    write_json(OUT / "figures.json", {"code_sha256": sha256(Path(__file__)),
                                      "inputs": {p.name: sha256(p) for p in paths},
                                      "outputs": {name: sha256(OUT / name) for name in ["daily_context.png", "monthly_context.png"]}})
