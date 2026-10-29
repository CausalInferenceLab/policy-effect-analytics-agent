"""사전 고정한 네 공간 집단과 모든 개별 도로 링크의 변화 표를 그린다."""

import json

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .common import read_yaml, sha256, write_json  # noqa: E402
from .deepening_road import CONFIG, OUT  # noqa: E402
from .overnight_operations_plots import style  # noqa: E402

LABELS = {"summer2023": "2023 사전 → 여름", "summer2024": "2024 사전 → 여름",
          "summer2025": "2025 사전 → 여름", "pre_year_over_year": "2024 사전 → 2025 사전",
          "post_year_over_year": "2024 여름 → 2025 여름", "post2025_from_pre2024": "2024 사전 → 2025 여름"}


def run():
    style()
    cfg = read_yaml(CONFIG)
    audit = json.loads((OUT / "audit.json").read_text())
    inputs = {}
    for name in ["group_comparisons.csv", "single_link_evening.csv", "metadata_check.csv"]:
        actual = sha256(OUT / name)
        if actual != audit["outputs"][name]:
            raise ValueError("도로 그림 입력 해시 변경")
        inputs[name] = actual
    groups = pd.read_csv(OUT / "group_comparisons.csv")
    d = groups[groups.band.eq("evening") & groups.method.eq("fixed_length_arithmetic")]
    if len(d) != 24 or not d.quality_pass.eq(True).all():
        raise ValueError("그림의 고정 집단 비교 수·품질 조건 미달")
    fig, axes = plt.subplots(2, 2, figsize=(12.6, 8.8), sharex=True, sharey=True)
    for ax, group in zip(axes.ravel(), cfg["groups"], strict=True):
        rows = d[d.group.eq(group)].set_index("comparison").reindex(LABELS)
        y = np.arange(len(LABELS))
        color = "#287c9c" if group.endswith("south") else "#b56535"
        ax.hlines(y, rows.week_bootstrap_low, rows.week_bootstrap_high, color=color, lw=2)
        ax.scatter(rows.change_pct, y, color=color, s=32, zorder=3)
        ax.axvline(0, color="#888", lw=.8)
        ax.axhline(2.5, color="#ccc", ls="--", lw=.8)
        ax.set(title=cfg["groups"][group]["label"], yticks=y, yticklabels=list(LABELS.values()), xlim=(-35, 27))
        ax.grid(axis="x", alpha=.15)
    axes[0, 0].invert_yaxis()
    for ax in axes[1]:
        ax.set_xlabel("길이 가중 일반도로 속도 변화 (%)")
    fig.suptitle("같은 강남대로에서도 영동1교 주변과 강남역의 변화가 다름", fontsize=15)
    fig.text(.02, .02, "저녁 17~19시, 고정 14개 링크. 선은 달력 주 재표집 95% 구간이며 다중비교 보정은 하지 않았다.\n"
             "버스 시간·연결 경로의 실제 이동속도가 아니다. 동시 도로 공사·버스 정책·GTX의 원인별 효과를 분리하지 않는다.", fontsize=9)
    fig.tight_layout(rect=(0, .09, 1, .95))
    fig.savefig(OUT / "spatial_group_changes.png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    single = pd.read_csv(OUT / "single_link_evening.csv", dtype={"link_id": str})
    meta = pd.read_csv(OUT / "metadata_check.csv", dtype={"link_id": str}).drop_duplicates("link_id").set_index("link_id")
    order = [link for spec in cfg["groups"].values() for link in spec["links"]]
    if len(single) != 84 or not single.quality_pass.eq(True).all():
        raise ValueError("개별 링크 그림의 비교 수·품질 조건 미달")
    matrix = single.pivot(index="link_id", columns="comparison", values="change_pct").reindex(index=order, columns=LABELS)
    if matrix.isna().any().any():
        raise ValueError("개별 링크 그림의 누락")
    labels = [f"{'남행' if meta.loc[link, 'direction_original'] == '하행' else '북행'}  "
              f"{meta.loc[link, '시점명_original']} → {meta.loc[link, '종점명_original']}" for link in order]
    fig, ax = plt.subplots(figsize=(12.8, 8.4))
    im = ax.imshow(matrix.to_numpy(), cmap="RdBu", vmin=-70, vmax=70, aspect="auto")
    for row in range(len(matrix)):
        for col in range(len(LABELS)):
            value = matrix.iloc[row, col]
            ax.text(col, row, f"{value:+.1f}", ha="center", va="center", fontsize=9,
                    color="white" if abs(value) > 43 else "#222")
    xlabels = ["2023 사전\n→ 여름", "2024 사전\n→ 여름", "2025 사전\n→ 여름", "2024 사전\n→ 2025 사전",
               "2024 여름\n→ 2025 여름", "2024 사전\n→ 2025 여름"]
    ax.set(yticks=np.arange(len(order)), yticklabels=labels, xticks=np.arange(len(LABELS)), xticklabels=xlabels)
    position = 0
    for spec in list(cfg["groups"].values())[:-1]:
        position += len(spec["links"])
        ax.axhline(position - .5, color="white", lw=2)
    fig.colorbar(im, ax=ax, pad=.02, label="개별 링크 저녁 평균 속도 변화 (%)")
    fig.suptitle("주변 링크 안에서도 속도 증가와 감소가 섞여 있음", fontsize=15)
    fig.text(.02, .015, "결과 크기로 고르지 않은 14개 링크 전체. 붉은색은 속도 감소, 파란색은 증가. 공사 노출이나 정체의 이동을 입증하는 지도가 아니다.", fontsize=9)
    fig.tight_layout(rect=(0, .06, 1, .95))
    fig.savefig(OUT / "single_link_changes.png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    write_json(OUT / "figures.json", dict(code_sha256=sha256(__file__), inputs=inputs,
        outputs={name: sha256(OUT / name) for name in ["spatial_group_changes.png", "single_link_changes.png"]}))
