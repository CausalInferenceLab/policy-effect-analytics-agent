"""버스 구간·시간대·정류장 기록과 주변 교통의 탐색 결과 그림을 저장한다."""

from importlib.metadata import version
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

from .common import CASE, read_yaml, sha256, utcnow, write_json  # noqa: E402
from .followup import OUT, periods  # noqa: E402

COLORS = {"pre": "#78879b", "post": "#d66b32"}
GROUPS = {"central_south": "중앙차로 남행", "central_north": "중앙차로 북행", "curb_south": "가로변 남행 후보"}


def save(fig, name, note):
    fig.text(.02, .015, note, fontsize=9, color="#4b5563")
    fig.tight_layout(rect=(0, .07, 1, .94))
    fig.savefig(OUT / name, dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot():
    for path in (Path("/mnt/c/Windows/Fonts/malgun.ttf"), Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")):
        if path.exists():
            font_manager.fontManager.addfont(str(path))
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(path)).get_name()
            break
    plt.rcParams.update({"axes.unicode_minus": False, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.titleweight": "bold", "font.size": 10})
    cfg = read_yaml("followup_config.yaml")
    pre, post = periods(cfg)
    profile = pd.read_csv(OUT / "bus_hour_profile.csv")
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5), sharey=True)
    for ax, (group, title) in zip(axes, GROUPS.items(), strict=True):
        part = profile[profile.group.eq(group)].sort_values("hour")
        for p, label in (("pre", "이전"), ("post", "이후")):
            ax.plot(part.hour, part[p + "_mean"], marker="o", ms=3, color=COLORS[p], label=label)
        rejected = part[~part.quality_pass]
        ax.scatter(rejected.hour, rejected.post_mean, marker="x", color="black", s=45, label="관측률/일수 기준 미달" if len(rejected) else None)
        ax.axhline(100, color="gray", lw=.7, linestyle="--")
        ax.axvspan(17, 19, alpha=.08, color="orange")
        ax.set(title=title, xlabel="원본의 시간 열 (시)", xticks=[7, 10, 13, 16, 19, 22])
        ax.legend(fontsize=8)
    axes[0].set_ylabel("양의 기록 운행시간 지수\n노선·구간·시간별 이전 평균=100")
    fig.suptitle("같은 버스 구간도 시간대와 방향에 따라 변화가 다르다", fontsize=15)
    save(fig, "bus_hour_profile.png", "평일·공휴일 제외. 단위/집계 정의 미확인: 분·승객 시간·대기행렬이 아님. × 표시는 비교 근거가 부족한 탐색값.")

    segments = pd.read_csv(OUT / "bus_segments.csv")
    seg = segments[segments.adjacent & segments.mapping_verified & segments.group.str.startswith("central")].sort_values(["group", "order"])
    fig, ax = plt.subplots(figsize=(11, 7))
    y = np.arange(len(seg))
    colors = ["#2a8c82" if v < 0 else "#d66b32" for v in seg.relative_change_pct]
    bars = ax.barh(y, seg.relative_change_pct, color=colors)
    for bar, ok in zip(bars, seg.quality_pass, strict=True):
        if not ok:
            bar.set_hatch("///")
            bar.set_alpha(.4)
    labels = [f"{'남행' if r.group == 'central_south' else '북행'} {r.from_ars:05d}→{r.to_ars:05d}  {r.to_name}" for r in seg.itertuples()]
    ax.set(yticks=y, yticklabels=labels, xlabel="양의 기록 운행시간 지수의 전후 상대 변화 (%)")
    ax.invert_yaxis()
    ax.axvline(0, color="gray", lw=.7)
    ax.set_xlim(min(-60, seg.relative_change_pct.min() - 12), max(40, seg.relative_change_pct.max() + 10))
    for i, v in enumerate(seg.relative_change_pct):
        if np.isfinite(v):
            ax.text(v, i, f" {v:+.1f}% ", ha="left" if v >= 0 else "right", va="center", fontsize=9)
        else:
            ax.text(1, i, "관측률 미달", va="center", fontsize=9, color="gray")
    fig.suptitle("저녁 17~19시: 어느 정류장 구간에서 기록값이 달라졌나", fontsize=15)
    save(fig, "bus_segments.png", "사전 관측률로 고정한 노선·구간·시각 비교. 빗금은 품질 기준 미달. 실제 통행 분수·인과 효과로 해석하지 않음.")

    counts = pd.read_csv(OUT / "station_recorded_counts.csv", dtype={"ars": str})
    chosen = ["22009", "22007", "22005", "22653", "22654", "22905", "22132"]
    fig, axes = plt.subplots(1, 2, figsize=(13, 6))
    for ax, kind, title in zip(axes, ("bus_trips", "bus_boardings"), ("운행횟수 기록", "승차 인원 기록"), strict=True):
        part = counts[counts.kind.eq(kind)].set_index(["ars", "period"])
        for p, shift, label in (("pre", -.18, "이전"), ("post", .18, "이후")):
            values = [part.loc[(s, p), "daily_recorded_positive_subtotal"]
                      if (s, p) in part.index and part.loc[(s, p), "days_with_positive_records"] >= cfg["minimum_common_days"]
                      else np.nan for s in chosen]
            ax.barh(np.arange(len(chosen)) + shift, values, height=.34, color=COLORS[p], label=label)
        for i, s in enumerate(chosen):
            if all((s, p) not in part.index or part.loc[(s, p), "days_with_positive_records"] < cfg["minimum_common_days"] for p in ("pre", "post")):
                ax.text(5, i, "기록 일수 부족", va="center", fontsize=9, color="gray")
        names = counts.drop_duplicates("ars").set_index("ars")["name"]
        ax.set(yticks=np.arange(len(chosen)), yticklabels=[s + " " + names[s] for s in chosen],
               title=title, xlabel="양의 기록 소계의 일평균 (저녁 3시간)")
        ax.invert_yaxis()
        ax.legend()
    fig.suptitle("중앙·가로변 정류장에 남은 운행·승차 기록", fontsize=15)
    save(fig, "station_counts.png", "양의 기록이 20일 미만이면 막대 생략. 공란을 0으로 채우지 않음. 완전한 수요 추정이 아니며 일부 가로변 ID는 연결 후보.")

    road = pd.read_csv(OUT / "road_summary.csv").query("scenario == 'main'")
    vol = pd.read_csv(OUT / "volume_summary.csv").query("scenario == 'main'")
    fig, axes = plt.subplots(1, 2, figsize=(13, 6))
    for ax, d, labels, title in ((axes[0], road, road.road + " " + road.direction, "주변 도로 속도"),
                                (axes[1], vol, vol.point + " " + vol.direction, "검지지점 교통량")):
        ax.barh(np.arange(len(d)), d.relative_change_pct, color=["#2a8c82" if x >= 0 else "#d66b32" for x in d.relative_change_pct])
        ax.set(yticks=np.arange(len(d)), yticklabels=labels, title=title, xlabel="전후 변화 (%)")
        ax.axvline(0, color="gray", lw=.7)
        ax.set_xlim(min(-15, d.relative_change_pct.min() - 4), max(4, d.relative_change_pct.max() + 3))
        ax.invert_yaxis()
        for i, v in enumerate(d.relative_change_pct):
            ax.text(v, i, f" {v:+.1f}% ", ha="left" if v >= 0 else "right", va="center", fontsize=9)
    fig.suptitle("버스 구간 변화와 함께 본 일반 차량의 저녁 교통", fontsize=15)
    save(fig, "road_context.png", "속도: 고정 링크 길이 가중 평균 / 교통량: 지점별 대/시간. 전체 도로 맥락이며 정책의 우회·전이 효과를 식별하지 않음.")

    joint = pd.read_csv(OUT / "gangnam_speed_volume.csv")
    fig, ax = plt.subplots(figsize=(8, 5.5))
    for p, dates, label in (("pre", pre, "이전"), ("post", post, "이후")):
        part = joint[joint.date.isin(dates) & joint.hour.isin(cfg["evening_hours"])]
        ax.scatter(part.value, part.speed_kmh, alpha=.5, s=24, color=COLORS[p], label=label)
    ax.set(xlabel="D-35 강남역 유출 교통량 (대/시간)", ylabel="강남역→우성아파트 속도 (km/h)")
    ax.legend()
    fig.suptitle("같은 저녁 시각의 속도와 교통량", fontsize=15)
    save(fig, "speed_volume.png", "시간별 한 행. 검지지점과 도로 링크의 측정 공간은 완전히 같지 않음. 점의 이동은 인과 효과·용량 곡선을 뜻하지 않음.")
    code = ["followup.py", "gangnam/followup.py", "gangnam/followup_data.py", "gangnam/followup_plots.py",
            "gangnam/topis.py", "gangnam/common.py"]
    config = ["followup_config.yaml", "followup-policy.yaml", "followup-sources.json", "research-sources.json",
              "discovery-sources.json", "source-manifest.json", "data_contract.yaml"]
    write_json(OUT / "run_manifest.json", {
        "generated_at": utcnow(), "code": {p: sha256(CASE / p) for p in code},
        "inputs": {p: sha256(CASE / p) for p in config},
        "artifacts": {p.name: sha256(p) for p in sorted(OUT.iterdir()) if p.is_file() and p.name != "run_manifest.json"},
        "versions": {p: version(p) for p in ("pandas", "numpy", "matplotlib", "openpyxl", "pyarrow", "requests")},
        "scope": "2024년 자료의 후속 탐색. 새 예측 모델 학습·인과 효과 식별은 포함하지 않음",
    })
