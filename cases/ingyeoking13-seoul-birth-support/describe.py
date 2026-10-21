"""25개 구 기술통계와 작은 표본의 배정 진단. 인과 검정으로 해석하지 않는다."""

from __future__ import annotations

import itertools
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

LABELS = (
    "Jongno Jung Yongsan Seongdong Gwangjin Dongdaemun Jungnang Seongbuk Gangbuk "
    "Dobong Nowon Eunpyeong Seodaemun Mapo Yangcheon Gangseo Guro Geumcheon "
    "Yeongdeungpo Dongjak Gwanak Seocho Gangnam Songpa Gangdong"
).split()


def assignment_diagnostic(panel: pd.DataFrame) -> dict:
    """관측 배정을 포함한 5C2=10개 배정 전수 비교. 무작위 배정 가정은 성립하지 않는다."""
    wide = panel.pivot(index="district", columns="year", values="log_births")
    change = wide[[2023, 2024]].mean(axis=1) - wide[2022]
    treated = set(panel.loc[panel.treated == 1, "district"])

    def contrast(names):
        mask = change.index.isin(names)
        return float(change[mask].mean() - change[~mask].mean())

    observed = contrast(treated)
    values = [contrast(names) for names in itertools.combinations(change.index, len(treated))]
    # 같은 배정을 다시 계산할 때의 부동소수점 오차도 동률로 포함한다.
    fraction = sum(abs(value) >= abs(observed) - 1e-12 for value in values) / len(values)
    return {"observed": observed, "assignments": len(values), "tail_fraction": fraction}


def write_description(case_dir: Path, districts: tuple[str, ...]) -> None:
    births = pd.read_csv(case_dir / "data" / "raw" / "births.csv")
    panel = pd.read_csv(case_dir / "data" / "panel.csv")
    annual = births.groupby(["district", "year"]).births.sum().unstack()
    groups = panel.groupby("district").treated.first().to_dict()
    diagnostic = assignment_diagnostic(panel)
    colors = {1: "#c9435a", 0: "#008295", None: "#8b9199"}
    fig, axes = plt.subplots(5, 5, figsize=(15, 12), sharex=True, sharey=True)
    for ax, district, label in zip(axes.flat, districts, LABELS, strict=True):
        series = annual.loc[district] / annual.loc[district, 2022] * 100
        group = groups.get(district)
        ax.plot(series.index, series, marker="o", ms=3, color=colors[group])
        ax.axhline(100, color="#c0c5ca", lw=0.7)
        ax.axvline(2022.5, color="#c0c5ca", ls=":", lw=0.8)
        ax.set_title(label, fontsize=11, color=colors[group])
        ax.set_xticks([2018, 2020, 2022, 2024])
        ax.grid(axis="y", alpha=0.15)
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Seoul birth registrations, 2018–2024 (2022 = 100)", fontsize=19)
    fig.supxlabel("Year | red: increased grant; teal: unchanged first-child grant; gray: excluded")
    fig.supylabel("Annual registrations, indexed to 2022")
    fig.tight_layout(rect=(0.015, 0.02, 1, 0.96))
    figdir = case_dir / "figures"
    figdir.mkdir(exist_ok=True)
    fig.savefig(figdir / "district_trends.png", dpi=150)
    plt.close(fig)
    lines = [
        "# 서울 25개 구 출생등록 기술통계",
        "",
        "`fetch.py`가 공식 월별 CSV에서 생성한 연구용 요약이다. 정책 효과 추정표가 아니다.",
        "출생등록은 주민등록 신고기준이며 발생기준 출생아 수·출산율과 다르다.",
        "",
        "![25개 구 추세](figures/district_trends.png)",
        "",
        "| 자치구 | 비교 분류 | 2022 | 2023 | 2024 | 2022→2024 변화 |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for district in districts:
        row = annual.loc[district]
        label = {1: "증액", 0: "유지"}.get(groups.get(district), "제외")
        lines.append(
            f"| {district} | {label} | {row[2022]:,} | {row[2023]:,} | {row[2024]:,} "
            f"| {(row[2024] / row[2022] - 1) * 100:+.1f}% |"
        )
    city = annual.sum()
    lines += [
        "",
        f"서울 합계: 2022년 {city[2022]:,}건, 2023년 {city[2023]:,}건, 2024년 {city[2024]:,}건.",
        "원본의 서울시 총계와 25개 구 합이 84개월 모두 일치했다.",
        "",
        "## 작은 표본의 추론 진단",
        "",
        f"5개 구의 2022년 대비 2023~2024년 평균 로그 변화 차이는 "
        f"{diagnostic['observed']:+.6f}이다. 균형 패널 이벤트 스터디의 사후 평균과 같다.",
        f"5개 구 중 2개를 선택하는 {diagnostic['assignments']}개 배정에 관측 배정도 포함해 "
        f"전수 비교하면 양측 꼬리 비율은 {diagnostic['tail_fraction']:.3f}이다.",
        "이는 결과를 본 후 추가한 구현 점검용 진단이며 사전 등록된 주 분석을 대체하지 않는다.",
        "실제 정책 배정은 무작위가 아니므로 이 비율도 인과적 p값으로 사용할 수 없다.",
        "",
        "현재 공통 엔진은 실제 처치 구를 제외한 대조 구 3개 중 2개를 뽑는 방식을 999회 "
        "반복한다. 서로 다른 가짜 배정은 3개뿐이다. 자동 리포트의 p=0.001과 좁은 구간을 "
        "유효한 무작위배정 검정이나 정책 효과의 신뢰구간으로 해석하지 않는다. "
        "공통 엔진은 변경하지 않았으며, 사전 계획에 따라 종합 판정은 식별 불가다.",
        "",
        "자료: [행정안전부 주민등록 인구통계](https://jumin.mois.go.kr/etcStatBirth.do), "
        "[공공데이터포털 3033249](https://www.data.go.kr/data/3033249/fileData.do) "
        "(이용허락범위 제한 없음). 정책 분류·근거 부족은 [policy-review.md](policy-review.md) 참조.",
    ]
    (case_dir / "descriptive-report.md").write_text("\n".join(lines) + "\n")
