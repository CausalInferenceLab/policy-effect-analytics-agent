"""역사적 정류장 대응과 승하차·환승 자료의 관측 한계를 그림으로 남긴다."""

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.colors import ListedColormap  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from .common import CASE, sha256, write_json  # noqa: E402

ROOT = CASE / "results/overnight"
OUT = ROOT / "auxiliary"
LABELS = {"central_south": "중앙 남행", "central_north": "중앙 북행", "curb_south": "가로변", "feeder": "인접 정류장"}


def save(fig, name, note, bottom=.12):
    fig.text(.02, .015, note, fontsize=9, color="#4b5563")
    fig.tight_layout(rect=(0, bottom, 1, .94))
    fig.savefig(OUT / name, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def identity():
    d = pd.read_csv(ROOT / "cards/station_identity.csv", dtype={"stop": str, "expected_ars": str})
    stations = pd.read_csv(ROOT.parent / "directional/station_registry.csv", dtype={"stop": str, "ars": str})
    stations = stations.set_index("group").loc[list(LABELS)].reset_index().sort_values(["group", "order"], kind="stable")
    months = sorted(d.month.unique())
    d["state"] = np.select([d.source_status.eq("quarantined_header"), d.all_observed_ars_agree.eq(True)], [2, 1], default=0)
    matrix = d.pivot(index="stop", columns="month", values="state").reindex(index=stations.stop, columns=months)
    fig, ax = plt.subplots(figsize=(13, 10))
    ax.imshow(matrix, cmap=ListedColormap(["#dde2e5", "#367e83", "#e3af62"]), vmin=0, vmax=2, aspect="auto")
    ax.set(xticks=range(len(months)), xticklabels=months, yticks=range(len(stations)),
           yticklabels=[f"{LABELS[r.group]} {r.ars}" for r in stations.itertuples()])
    ax.tick_params(axis="x", rotation=65, labelsize=8)
    ax.tick_params(axis="y", labelsize=8)
    ax.legend(handles=[Patch(color=c, label=t) for c, t in [("#367e83", "ID·ARS 일치"), ("#dde2e5", "카드 행 없음"),
                                                          ("#e3af62", "파일 헤더 손상·미판정")]],
              ncol=3, loc="upper center", bbox_to_anchor=(.5, -.13), fontsize=9)
    fig.suptitle("중앙 16개 정류장의 ID·ARS는 사용 가능한 모든 월에서 일치", fontsize=15)
    save(fig, "card_identity.png", "2022·2025년은 식별자만 확인. 같은 ID·ARS가 관측됐다는 뜻이며 물리적 위치 불변·경기버스 수록을 보증하지 않음.", .16)


def card_coverage():
    d = pd.read_csv(ROOT / "cards/monthly_group.csv")
    d = d[d.cohort.eq("common_pre_labels") & d.band.eq("evening") & d.flow.eq("boardings")]
    groups = ["central_south", "central_north"]
    months = sorted(d.month.unique())
    data = d.pivot(index="group", columns="month", values="known_fraction").reindex(index=groups, columns=months) * 100
    fig, ax = plt.subplots(figsize=(12, 4.8))
    ax.imshow(data, cmap="YlGnBu", vmin=50, vmax=100, aspect="auto")
    for i in range(2):
        for j in range(len(months)):
            value = data.iloc[i, j]
            ax.text(j, i, f"{value:.1f}", ha="center", va="center", color="white" if value > 85 else "#223949", fontsize=9)
    ax.set(xticks=range(len(months)), xticklabels=months, yticks=range(2), yticklabels=[LABELS[g] for g in groups])
    ax.tick_params(axis="x", rotation=45)
    fig.suptitle("고정 카드 노선표기 표본에서도 공개 키 중복·부재가 남음", fontsize=15)
    save(fig, "card_cohort_coverage.png", "숫자는 저녁 고정 셀의 알려진 값 비율(%). 0은 유효하나 동일 노선표기·정류장에 여러 행이 있으면 제외.\n월 합계를 완전한 정류장 이용량으로 제시하는 조건은 100%이며, 기준을 낮춰 전체 효과를 만들지 않음.", .22)


def transfer_keys():
    d = pd.read_csv(OUT / "transfer_probe_selected_quality_by_day.csv", dtype={"기준_날짜": str})
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    date = pd.to_datetime(d["기준_날짜"], format="%Y%m%d")
    axes[0].bar(date, d.ambiguous_fraction * 100, color="#b77d56")
    axes[0].set(ylabel="공개 키가 중복되는 선택 행 (%)", ylim=(0, 50), title="2024년 5월 · 날짜별 중복 비중")
    axes[0].tick_params(axis="x", rotation=40)
    m = pd.read_csv(OUT / "transfer_key_multiplicity.csv")
    bars = axes[1].bar(m.multiplicity.astype(str), m.public_keys, color="#537f91")
    axes[1].bar_label(bars, fmt="{:,.0f}", fontsize=8, padding=3)
    axes[1].set(xlabel="같은 날짜·정류장 쌍·시각을 가진 행 수", ylabel="공개 키 수", title="1개 키에 최대 6개 서로 다른 행")
    axes[1].set_ylim(0, m.public_keys.max() * 1.18)
    fig.suptitle("환승시간 분석 전 필요한 것은 공개 행의 실제 집계 단위 확인", fontsize=15)
    save(fig, "transfer_key_quality.png", "32개 고정 정류장 관련 기록 171,627행 중 62,235행(36.3%)의 키가 중복. 5/28·29는 헤더만 있어 막대를 그리지 않음.\n여러 행을 합치거나 한 행만 남기는 처리와 분 단위 환승시간 해석은 보류.", .22)


def plot():
    for path in [Path("/mnt/c/Windows/Fonts/malgun.ttf"), Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")]:
        if path.exists():
            font_manager.fontManager.addfont(str(path))
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(path)).get_name()
            break
    plt.rcParams.update({"axes.unicode_minus": False, "axes.spines.top": False, "axes.spines.right": False, "font.size": 10})
    identity()
    card_coverage()
    transfer_keys()
    inputs = [ROOT / "cards/station_identity.csv", ROOT / "cards/monthly_group.csv",
              OUT / "transfer_probe_selected_quality_by_day.csv", OUT / "transfer_key_multiplicity.csv"]
    write_json(OUT / "figures.json", {"code_sha256": sha256(Path(__file__)),
                                      "inputs": {str(p.relative_to(CASE)): sha256(p) for p in inputs},
                                      "figures": {p.name: sha256(p) for p in OUT.glob("*.png")}})
