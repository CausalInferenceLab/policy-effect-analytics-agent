"""공개 집계표만으로 노선명 후보의 대표일 수록 범위를 그린다."""

import json

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.patches import Patch

from .common import CASE, read_yaml, sha256, write_json
from .overnight_operations_plots import style

OUT = CASE / "results/deepening/gyeonggi"


def run():
    cfg = read_yaml("deepening_gyeonggi_audit_config.yaml")
    audit = json.loads((OUT / "audit.json").read_text())
    files = ["candidate_representative_day_trips.csv", "candidate_coverage.csv", "policy_name_presence.csv"]
    for name in files:
        if sha256(OUT / name) != audit["outputs"][name]:
            raise ValueError("public candidate audit checksum changed")
    coverage = pd.read_csv(OUT / "candidate_coverage.csv", dtype={"route": str, "policy_name": str})
    if coverage[["value_conflict_keys", "multiple_description_keys"]].gt(0).any().any():
        raise ValueError("candidate ambiguity requires a separate monthly display rule")
    data = pd.read_csv(OUT / files[0], dtype={"route": str, "policy_name_candidate": str})
    if data.duplicated(["year", "city", "month", "route", "day_type"]).any():
        raise ValueError("representative day key repeated")
    identities = data[["policy_name_candidate", "city", "route"]].drop_duplicates()
    order = {name: i for i, name in enumerate(cfg["policy_names"])}
    identities["order"] = identities.policy_name_candidate.map(order)
    identities = identities.sort_values(["order", "city", "route"])
    observed = set(identities.policy_name_candidate)
    labels = [(r.city, r.route) for r in identities.itertuples()]
    labels += [("후보 미수록", name) for name in cfg["policy_names"] if name not in observed]
    counts = data.groupby(["year", "city", "route", "month"]).day_type.nunique()
    rows = []
    for year in cfg["years"]:
        for city, route in labels:
            for month in range(1, 13):
                rows.append(dict(year=year, city=city, route=route, month=month,
                                 observed_day_types=int(counts.get((year, city, route, month), 0))))
    grid = pd.DataFrame(rows)
    grid.to_csv(OUT / "candidate_coverage_grid.csv", index=False, lineterminator="\n")
    style()
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 12), sharey=True)
    colors = ListedColormap(["#e7e9ed", "#e7ac4f", "#238b72"])
    for ax, year in zip(axes, cfg["years"], strict=True):
        matrix = grid[grid.year.eq(year)].observed_day_types.to_numpy().reshape(len(labels), 12)
        ax.imshow(matrix, cmap=colors, norm=BoundaryNorm([-.5, .5, 1.5, 2.5], 3), aspect="auto")
        ax.set_title(f"{year}년", fontsize=12)
        ax.set_xticks(np.arange(12), range(1, 13), fontsize=8)
        ax.set_xlabel("월")
        ax.set_yticks(np.arange(len(labels)))
        ax.set_yticklabels([f"{city} / {route}" for city, route in labels], fontsize=8)
        ax.set_yticks(np.arange(-.5, len(labels), 1), minor=True)
        ax.grid(which="minor", axis="y", color="white", linewidth=.6)
        ax.grid(which="major", visible=False)
        ax.tick_params(which="both", length=0)
    fig.suptitle("공식 첨부의 노선명·인가지역별 대표일 수록", fontsize=16, y=.97)
    fig.text(.5, .935, "이름 후보를 모두 표시 · 역사 노선 ID 및 정책 대상 동일성은 미확정", ha="center", fontsize=10)
    fig.legend(handles=[Patch(color=colors(i), label=label) for i, label in enumerate(
        ["수록 없음", "두 유형 중 하나만 수록", "평일·토요일 각각 수록"])],
        loc="lower center", ncol=3, bbox_to_anchor=(.58, .035), frameon=False, fontsize=9)
    fig.text(.58, .018, "한 칸은 월 전체가 아닌 대표 하루씩의 수록 상태. 회색을 실제 미운행으로 해석하지 않는다.",
             ha="center", fontsize=8)
    fig.subplots_adjust(left=.22, right=.98, top=.90, bottom=.105, wspace=.10)
    path = OUT / "candidate_coverage.png"
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)
    write_json(OUT / "figures.json", dict(code_sha256=sha256(__file__),
               inputs={name: sha256(OUT / name) for name in files},
               outputs={path.name: sha256(path), "candidate_coverage_grid.csv": sha256(OUT / "candidate_coverage_grid.csv")}))
