"""노선 이동·계절 비교·기상 표본의 한계를 그림과 실행 해시로 기록한다."""

from importlib.metadata import version
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

from .common import CASE, sha256, utcnow, write_json  # noqa: E402
from .directional_data import OUT  # noqa: E402

GROUPS = {"central_south": "중앙 남행", "central_north": "중앙 북행", "curb_south": "가로변 후보"}
PERIODS = {"summer2023": "2023 여름", "summer2024": "2024 여름", "autumn2024": "2024 가을"}
COHORTS = {"common_pre_calendar": "전체 달력·사전 공통", "common_pre_source_days": "원본 있는 날·사전 공통",
           "summer_survivors_source_days": "양년 여름에도 남은 구간"}
COLORS = {"summer2023": "#8095ac", "summer2024": "#d06b35", "autumn2024": "#288980"}


def save(fig, name, note):
    fig.text(.02, .015, note, fontsize=9, color="#4b5563")
    fig.tight_layout(rect=(0, .08, 1, .94))
    fig.savefig(OUT / name, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def route_plot():
    d = pd.read_csv(OUT / "family_movement.csv", dtype={"family": str})
    families = d.sort_values(["policy_group", "family"]).family.drop_duplicates().tolist()
    policy_names = {"reverse_evening": "역방향", "curb": "가로변", "dongtan": "동탄"}
    labels = [f"{policy_names[d[d.family.eq(f)].policy_group.iloc[0]]}  {f}" for f in families]
    fig, axes = plt.subplots(1, 3, figsize=(12, 9), sharey=True)
    for ax, period, title in zip(axes, ("pre2024", "post2024", "autumn2024"), ("정책 이전", "여름 이후", "가을"), strict=True):
        part = d[d.period.eq(period)].set_index("family").reindex(families)
        values = np.column_stack([part[g + "_days"] / part.source_available_days for g in GROUPS])
        ax.imshow(values, vmin=0, vmax=1, cmap="Blues", aspect="auto")
        for y in range(len(families)):
            for x, g in enumerate(GROUPS):
                count = part.iloc[y][g + "_days"]
                ax.text(x, y, f"{count:.0f}/{part.iloc[y].source_available_days:.0f}", ha="center", va="center", fontsize=8,
                        color="white" if values[y, x] > .6 else "#263645")
        ax.set(title=title, xticks=range(3), xticklabels=["중앙 남행", "중앙 북행", "가로변"], yticks=range(len(families)))
    axes[0].set_yticklabels(labels)
    fig.suptitle("정책 후보 노선 20개군: 저녁 운행 기록이 있는 방향·정류장군", fontsize=15)
    save(fig, "route_movement.png", "셀: 양의 기록이 있는 날짜 / 원본 존재 평일. 0은 관측 기록 없음이며 운행 0의 확정이 아님. 현재 노선명 연결·일부 가로변 ID 미확정.")


def seasonal_plot():
    d = pd.read_csv(OUT / "index_comparisons.csv")
    fig, axes = plt.subplots(1, 2, figsize=(14, 6.5), sharey=True)
    labels = [f"{cohort}\n{period}" for cohort in COHORTS.values() for period in PERIODS.values()]
    for ax, group in zip(axes, ("central_south", "central_north"), strict=True):
        part = d[d.group.eq(group)].set_index(["cohort", "comparison"])
        for y, (cohort, period) in enumerate((c, p) for c in COHORTS for p in PERIODS):
            row = part.loc[(cohort, period)]
            value = row.change_pct
            if pd.notna(value):
                ax.barh(y, value, color=COLORS[period], alpha=1 if row.quality_pass else .35,
                        hatch=None if row.quality_pass else "///", height=.65)
                ax.text(value + (.2 if value >= 0 else -.2), y, f"{value:+.1f}%" + (" ×" if not row.quality_pass else ""),
                        va="center", ha="left" if value >= 0 else "right", fontsize=9)
            else:
                ax.text(.3, y, "산출 불가 ×", va="center", color="#777777")
        ax.axvline(0, color="gray", lw=.7)
        ax.set(title=GROUPS[group], yticks=range(len(labels)), xlabel="각 연도 정책 전 기간 대비 기록 지수 변화 (%)", xlim=(-12, 20))
    axes[0].set_yticklabels(labels, fontsize=9)
    axes[0].invert_yaxis()
    fig.suptitle("방향별 변화: 전년 참고 비교와 가을 지속성", fontsize=15)
    save(fig, "seasonal_comparison.png", "×·빗금: 일수/관측률 기준 미달. 마지막 3행은 이후에도 기록이 남은 표본에 한정한 민감도 분석. 분 단위·인과 효과가 아님.")


def segment_plot():
    d = pd.read_csv(OUT / "segment_comparisons.csv")
    d = d[d.adjacent & d.group.str.startswith("central")]
    order = d[["group", "order", "from_ars", "to_ars", "to_name"]].drop_duplicates().sort_values(["group", "order"], ascending=[False, True])
    keys = list(zip(order.from_ars, order.to_ars, strict=True))
    labels = [f"{'남행' if r.group == 'central_south' else '북행'} {r.from_ars:05d}→{r.to_ars:05d}  {r.to_name}" for r in order.itertuples()]
    fig, axes = plt.subplots(1, 2, figsize=(14, 8), sharey=True)
    for ax, cohort, title in zip(axes, ("common_pre_source_days", "summer_survivors_source_days"),
                                ("양년 사전 기록으로 고정", "양년 여름에도 기록이 남은 표본"), strict=True):
        rows = d[d.cohort.eq(cohort)].set_index(["from_ars", "to_ars", "comparison"])
        values, passed = np.full((len(keys), 3), np.nan), np.zeros((len(keys), 3), dtype=bool)
        for y, (a, b) in enumerate(keys):
            for x, period in enumerate(PERIODS):
                if (a, b, period) in rows.index:
                    row = rows.loc[(a, b, period)]
                    values[y, x], passed[y, x] = row.change_pct, row.quality_pass
        ax.imshow(np.ma.masked_invalid(values), cmap="RdBu_r", vmin=-55, vmax=55, aspect="auto")
        for y in range(len(keys)):
            for x in range(3):
                value = values[y, x]
                label = f"{value:+.1f}%" if np.isfinite(value) else "—"
                ax.text(x, y, label + (" ×" if not passed[y, x] else ""), ha="center", va="center", fontsize=9,
                        color="white" if abs(value) > 38 else "#263645")
        ax.set(title=title, yticks=range(len(keys)), xticks=range(3), xticklabels=PERIODS.values())
    axes[0].set_yticklabels(labels, fontsize=9)
    fig.suptitle("어느 정류장 구간에서 변화가 남았나", fontsize=15)
    save(fig, "segment_comparison.png", "양의 기록 운행시간 지수 변화. 파랑=감소, 빨강=증가, ×=품질 기준 미달. 원본이 있는 날짜 조건부 비교이며 오른쪽은 생존 표본 편향 가능.")


def weather_plot():
    d = pd.read_csv(OUT / "weather_comparisons.csv")
    schemes = {"weekday": "요일만", "rain_record": "강수 기록 층", "rain_temperature": "강수 층+기온", "rain_temperature_weekday": "강수 층+기온+요일"}
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.5), sharey=True)
    for ax, group in zip(axes, ("central_south", "central_north"), strict=True):
        rows = d[d.group.eq(group) & d.comparison.eq("summer2024")].set_index("scheme").loc[list(schemes)]
        for offset, field, label, color in ((-.18, "before", "이전", "#8095ac"), (.18, "after", "이후", "#d06b35")):
            values = rows[field + "_used"].to_numpy()
            bars = ax.barh(np.arange(4) + offset, values, height=.33, color=color, label=label)
            for y, (bar, (_, row)) in enumerate(zip(bars, rows.iterrows(), strict=True)):
                if not row.support_pass:
                    bar.set_hatch("///")
                ax.text(values[y] + .3, y + offset, f"{values[y]:.0f}/{row[field + '_total']:.0f}", va="center", fontsize=9)
        ax.set(title=GROUPS[group], yticks=range(4), xlabel="공통 층에 남은 날짜 / 원래 유효 날짜", xlim=(0, 35))
        ax.legend()
    axes[0].set_yticklabels(schemes.values())
    axes[0].invert_yaxis()
    fig.suptitle("날씨 조건을 맞추면 비교할 날짜가 부족해진다", fontsize=15)
    save(fig, "weather_support.png", "2024 여름, 원본 존재일 사전 공통 표본. 빗금: 공통 층 일수·유지율 기준 미달. 요일 통과는 기상 보정 통과가 아님. 서울108 일자료.")


def mechanism_plot():
    d = pd.read_csv(OUT / "mechanism_alignment.csv")
    d = d[d.group.str.startswith("central") & d.change_pct.notna()]
    fig, ax = plt.subplots(figsize=(10, 6))
    for group, color in (("central_south", "#288980"), ("central_north", "#d06b35")):
        rows = d[d.group.eq(group)]
        ax.scatter(rows.arrival_recorded_trips_change_pct, rows.change_pct, color=color, s=60, label=GROUPS[group])
        failed = rows[~rows.quality_pass]
        ax.scatter(failed.arrival_recorded_trips_change_pct, failed.change_pct, marker="x", color="black", s=60)
        for r in rows.itertuples():
            if (r.from_ars, r.to_ars) in {(22011, 22009), (22008, 22010)}:
                ax.annotate(f"{r.from_ars}→{r.to_ars}", (r.arrival_recorded_trips_change_pct, r.change_pct), xytext=(8, 6), textcoords="offset points")
    ax.axhline(0, color="gray", lw=.7)
    ax.axvline(0, color="gray", lw=.7)
    ax.set(xlabel="도착 정류장에 기록된 운행횟수 소계 변화 (%)", ylabel="구간의 기록 운행시간 지수 변화 (%)")
    ax.legend()
    fig.suptitle("운행 기록의 이동과 구간 지수 변화가 함께 나타나는가", fontsize=15)
    save(fig, "mechanism_alignment.png", "2024 여름 기술 비교. ×=지수 품질 기준 미달. 재방문 행은 횟수 소계에서 제외. 기록 누락·노선 구성 변화로 인과·용량 곡선 해석 불가.")


def plot():
    for path in (Path("/mnt/c/Windows/Fonts/malgun.ttf"), Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")):
        if path.exists():
            font_manager.fontManager.addfont(str(path))
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(path)).get_name()
            break
    plt.rcParams.update({"axes.unicode_minus": False, "axes.spines.top": False, "axes.spines.right": False, "font.size": 10})
    for render in (route_plot, seasonal_plot, segment_plot, weather_plot, mechanism_plot):
        render()
    code = ["directional.py", "gangnam/directional.py", "gangnam/directional_data.py", "gangnam/directional_weather.py",
            "gangnam/directional_plots.py", "gangnam/followup.py", "gangnam/followup_data.py", "gangnam/topis.py", "gangnam/common.py"]
    inputs = ["directional_config.yaml", "directional-sources.json", "directional-weather-sources.json", "directional-history-sources.json",
              "followup-policy.yaml", "followup-sources.json", "discovery-sources.json", "data_contract.yaml", "research-sources.json"]
    write_json(OUT / "run_manifest.json", {"generated_at": utcnow(), "code": {p: sha256(CASE / p) for p in code},
                                          "inputs": {p: sha256(CASE / p) for p in inputs},
                                          "artifacts": {p.name: sha256(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name != "run_manifest.json"},
                                          "versions": {p: version(p) for p in ("pandas", "numpy", "matplotlib", "requests", "holidays", "pyarrow")},
                                          "scope": "2023년 계절 참고·2024년 가을·서울 일기상 후속 탐색. 2026 시험자료 열람·새 모델 학습·인과 식별 없음"})
