"""공통 운영 지수·요금 기간·카드 기록·주변 교통의 탐색 결과를 비교 그림으로 저장한다."""

from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

from .common import CASE, sha256, write_json  # noqa: E402

BASE = CASE / "results/overnight"
OUT = BASE / "operations_figures"
COLORS = ["#8a9eac", "#cc784a", "#397b91"]
PERIODS = [("summer2023", "2023 여름"), ("summer2024", "2024 여름"), ("autumn2024", "2024 가을")]


def style():
    for path in [Path("/mnt/c/Windows/Fonts/malgun.ttf"), Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")]:
        if path.exists():
            font_manager.fontManager.addfont(str(path))
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(path)).get_name()
            break
    plt.rcParams.update({"axes.unicode_minus": False, "axes.spines.top": False, "axes.spines.right": False, "font.size": 10})


def save(fig, name, note):
    fig.text(.02, .02, note, fontsize=9, color="#4b5563", va="bottom")
    fig.tight_layout(rect=(0, .11, 1, .93))
    fig.savefig(OUT / name, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def mechanism(data):
    d = data[data.band.eq("evening") & data.endpoint.eq("arrival") & data.subset.eq("other_or_unclassified")
             & data.scope.eq("direction")]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.6), sharey=True)
    metrics = ["time", "trips", "boardings"]
    for ax, group, title in zip(axes, ["central_south", "central_north"], ["남행 268개 셀", "북행 251개 셀"], strict=True):
        for offset, (period, label), color in zip([-.18, .18], PERIODS[1:], COLORS[1:], strict=True):
            x = d[d.group.eq(group) & d.comparison.eq(period)].set_index("metric").reindex(metrics)
            positions = np.arange(3) + offset
            ax.bar(positions, x.change_pct, width=.33, color=color, label=label)
            ax.errorbar(positions, x.change_pct,
                        yerr=np.vstack([x.change_pct - x.week_bootstrap_low, x.week_bootstrap_high - x.change_pct]),
                        fmt="none", ecolor="#34404b", capsize=3, lw=1)
            for pos, row in zip(positions, x.itertuples(), strict=True):
                y = row.week_bootstrap_high + .8 if row.change_pct >= 0 else row.week_bootstrap_low - .8
                ax.text(pos, y, f"{row.change_pct:+.1f}%", ha="center", va="bottom" if row.change_pct >= 0 else "top", fontsize=9)
        ax.set(title=title, xticks=np.arange(3), xticklabels=["기록 시간", "운행횟수", "승차 기록"], ylim=(-17, 19))
        ax.axhline(0, color="#777", lw=.8)
        ax.legend(loc="upper left" if group == "central_south" else "upper right", fontsize=9)
    axes[0].set_ylabel("같은 사전 셀·유효 날짜의 지수 변화 (%)")
    fig.suptitle("남행 시간 감소와 승차 기록 증가는 같은 표본에서 함께 나타남", fontsize=15)
    save(fig, "mechanism_joint.png", "정책 후보 밖 시간 셀의 남행 53.6%·북행 55.7%만 포함. 도착 정류장·같은 기록 시간 연결.\n오차선은 주 재표집 변동 구간이며 원인·정책 효과·개별 차량 매칭을 뜻하지 않음.")


def fare(data):
    d = data[data.band.eq("evening") & data.subset.eq("other_or_unclassified")]
    order = ["original", "trim_2023_only", "harmonized_august11"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    for ax, group, label in zip(axes, ["central_south", "central_north"], ["남행", "북행"], strict=True):
        for year, color in [(2023, COLORS[0]), (2024, COLORS[1])]:
            x = d[d.group.eq(group) & d.year.eq(year)].set_index("window").reindex(order)
            ax.plot(np.arange(3), x.change_pct, marker="o", color=color, label=str(year))
            for pos, value in enumerate(x.change_pct):
                ax.text(pos, value + .8, f"{value:+.2f}%", ha="center", fontsize=9)
        ax.set(title=label, xticks=np.arange(3), xticklabels=["기존 창", "2023만 8/11까지", "두 해 모두 8/11까지"], ylim=(-12, 16))
        ax.axhline(0, color="#777", lw=.8)
        ax.legend(loc="lower left")
    axes[0].set_ylabel("사전 대비 저녁 기록 시간 지수 변화 (%)")
    fig.suptitle("2023년 요금 인상 이후를 제외해도 2024년 방향별 부호는 유지", fontsize=15)
    save(fig, "fare_window.png", "셀·기준 평균·일별 지수를 유지하고 사후 날짜만 줄임. 모든 표시 비교가 20일·관측률 차이 조건 통과.\n전년은 계절 참고이며 이 비교로 요금 인상 또는 버스 정책의 인과 효과를 추정하지 않음.")


def card_daily(data):
    d = data[data.scope.eq("direction")]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    for ax, flow, title in zip(axes, ["boardings", "alightings"], ["하루 승차 기록", "하루 하차 기록"], strict=True):
        for offset, (period, label), color in zip([-.24, 0, .24], PERIODS, COLORS, strict=True):
            x = d[d.flow.eq(flow) & d.comparison.eq(period)].set_index("group").reindex(["central_south", "central_north"])
            bars = ax.bar(np.arange(2) + offset, x.change_pct, width=.22, color=color, label=label)
            ax.bar_label(bars, fmt="%+.2f%%", padding=4, fontsize=9)
        ax.set(title=title, xticks=np.arange(2), xticklabels=["남행 8개 정류장", "북행 8개 정류장"], ylim=(-7, 7))
        ax.axhline(0, color="#777", lw=.8)
        ax.legend(fontsize=9)
    axes[0].set_ylabel("사전 대비 평일 하루 기록 합계 변화 (%)")
    fig.suptitle("검증된 중앙 정류장 카드 총계: 방향별 변화는 작고 서로 다름", fontsize=15)
    save(fig, "card_daily.png", "일별·월별 합계가 일치한 서울 면허 버스 기록. 8개 정류장이 모두 관측된 평일만 집계.\n전체 경기 광역버스·고유 이용자 수가 아니며 노선 구성·계절·동시 정책 변화가 포함될 수 있음.")


def card_hourly(data):
    d = data[data.month.str.startswith("2024")]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    for ax, group, title in zip(axes, ["central_south", "central_north"], ["남행 8개 정류장", "북행 8개 정류장"], strict=True):
        for months, label, color in [(["04", "05"], "4~5월", COLORS[0]), (["07", "08"], "7~8월", COLORS[1]),
                                     (["09", "10"], "9~10월", COLORS[2])]:
            x = d[d.group.eq(group) & d.flow.eq("boardings") & d.month.str[-2:].isin(months)]
            daily = x.groupby("hour").agg(value=("value", lambda s: s.sum(min_count=2)), days=("calendar_days", "sum"))
            ax.plot(daily.index, daily.value / daily.days, color=color, label=label, lw=2)
        ax.axvspan(16.5, 19.5, color="#ddd", alpha=.4)
        ax.set(title=title, xlabel="기록 시각", xticks=list(range(0, 24, 3)))
        ax.legend()
    axes[0].set_ylabel("시간대 승차 기록 / 달력 하루")
    fig.suptitle("월별 시간대 분포는 하루 총계와 별도로 해석", fontsize=15)
    save(fig, "card_hourly.png", "주말·공휴일을 포함한 달력 하루 평균. 음영은 17~19시. 비교 기준은 4~5월이며 일별 평일 창과 다름.\n일별 총계 일치는 월별 시간대 배분의 정확성까지 독립 검증하지 않음.")


def road_context(data):
    d = data[data.band.eq("evening") & ~data.method.eq("equal_cells")]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for ax, metric, groups, labels in [(axes[0], "speed_kmh", ["south", "north"], ["핵심 남행", "핵심 북행"]),
                                      (axes[1], "vehicles_per_hour", ["D-35|유입", "D-35|유출", "D-43|유입", "D-43|유출"],
                                       ["강남역 유입", "강남역 유출", "신사역 유입", "신사역 유출"])]:
        for offset, (period, label), color in zip([-.18, .18], PERIODS[1:], COLORS[1:], strict=True):
            x = d[d.metric.eq(metric) & d.comparison.eq(period) & d.group.isin(groups)].set_index("group").reindex(groups)
            bars = ax.bar(np.arange(len(groups)) + offset, x.change_pct, width=.33, color=color, label=label)
            ax.bar_label(bars, fmt="%+.2f%%", padding=4, fontsize=9)
        ax.set(xticks=np.arange(len(groups)), xticklabels=labels, ylim=(-6, 4))
        ax.axhline(0, color="#777", lw=.8)
        ax.legend(loc="lower left", fontsize=9)
    axes[0].set(title="일반도로 속도", ylabel="사전 대비 저녁 평균 변화 (%)")
    axes[1].set(title="검지지점 시간당 교통량")
    fig.suptitle("버스의 방향별 변화와 일반도로·교통량의 양상은 같지 않음", fontsize=15)
    save(fig, "road_core_volume.png", "도로: 교보타워~뱅뱅의 방향별 3개 링크, 고정 길이 가중. 교통량: D-35·D-43의 17~19시 평균.\n버스 지수와 단위·공간·관측 범위가 다르며 인과 대조군 또는 정체 이동의 증거로 확정하지 않음.")

    # 전체 시간대의 같은 집계법·같은 2024 여름 결과를 표시한다.
    x = data[data.scope.eq("road_stable_subset") & data.method.eq("fixed_length_arithmetic") & data.comparison.eq("summer2024")]
    x = x.assign(display=x.change_pct.where(x.quality_pass))
    table = x.pivot(index="group", columns="band", values="display").reindex(columns=["morning", "midday", "evening", "late"])
    count = x.groupby("group").selected_links.min()
    fig, ax = plt.subplots(figsize=(9, 7))
    bound = max(10, float(np.nanmax(np.abs(table.to_numpy()))))
    shown = ax.imshow(table, cmap="RdBu", vmin=-bound, vmax=bound, aspect="auto")
    for (i, j), value in np.ndenumerate(table.to_numpy()):
        ax.text(j, i, f"{value:+.1f}%" if pd.notna(value) else "보류", ha="center", va="center",
                color="white" if abs(value) > .65 * bound else "#17252e")
    ax.set(xticks=np.arange(4), xticklabels=["07~09시", "11~14시", "17~19시", "20~22시"],
           yticks=np.arange(len(table)), yticklabels=[f"{g.replace('|', ' ')} ({int(count[g])}개)" for g in table.index])
    fig.colorbar(shown, ax=ax, label="사전 대비 속도 변화 (%)")
    fig.suptitle("일반도로 변화도 도로·방향·시간대마다 다름", fontsize=15)
    save(fig, "road_context_heatmap.png", "2024 여름, 메타데이터가 유지된 링크의 사전 고정 표본. 괄호는 시간대별 최소 선택 링크 수.\n원래 88개 중 메타데이터 변경 22개를 제외했으므로 도로 전체를 대표하지 않음. 양수는 속도 증가.")


def plot():
    OUT.mkdir(parents=True, exist_ok=True)
    style()
    sources = {"mechanism": BASE / "mechanism/comparisons.csv", "fare": BASE / "fare_trim/comparisons.csv",
               "card_daily": BASE / "card_records/daily_comparisons.csv", "card_hourly": BASE / "card_records/monthly_hourly.csv",
               "road": BASE / "road_context/comparisons.csv"}
    mechanism(pd.read_csv(sources["mechanism"]))
    fare(pd.read_csv(sources["fare"]))
    card_daily(pd.read_csv(sources["card_daily"]))
    card_hourly(pd.read_csv(sources["card_hourly"]))
    road_context(pd.read_csv(sources["road"]))
    write_json(OUT / "figures.json", {"code_sha256": sha256(Path(__file__)),
                                      "inputs": {str(p.relative_to(CASE)): sha256(p) for p in sources.values()},
                                      "outputs": {p.name: sha256(p) for p in OUT.glob("*.png")}})
