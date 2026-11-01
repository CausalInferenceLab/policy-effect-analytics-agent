"""검증된 원본으로 관측 범위 진단 그림을 재현한다. 정책효과 그림이 아니다."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from fetch import HERE, audit, selected_districts  # noqa: E402
from fetch_characteristics import digest  # noqa: E402

QUARTER_LABELS = [f"{2021 + q // 4}Q{q % 4 + 1}" for q in range(16)]
GU_LABELS = {
    "동대문구": "Dongdaemun (treated)",
    "종로구": "Jongno",
    "용산구": "Yongsan",
    "광진구": "Gwangjin",
    "중랑구": "Jungnang",
    "성북구": "Seongbuk",
    "강북구": "Gangbuk",
    "도봉구": "Dobong",
    "노원구": "Nowon",
    "은평구": "Eunpyeong",
    "서대문구": "Seodaemun",
    "마포구": "Mapo",
    "양천구": "Yangcheon",
    "강서구": "Gangseo",
    "구로구": "Guro",
    "금천구": "Geumcheon",
    "영등포구": "Yeongdeungpo",
    "동작구": "Dongjak",
    "강남구": "Gangnam",
    "송파구": "Songpa",
    "강동구": "Gangdong",
}


def summarize(diagnostics: pd.DataFrame, names: list[str]) -> pd.DataFrame:
    """관측 상권×업종 조합 수. 첫 분기의 진입·이탈과 미관측 금액을 보존한다."""
    from sales_panel import INDUSTRIES

    keys = ["gu_name", "quarter_idx", "industry_code"]
    expected = pd.MultiIndex.from_product([names, range(16), INDUSTRIES], names=keys)
    actual = pd.MultiIndex.from_frame(diagnostics[keys])
    if diagnostics.duplicated(keys).any() or set(actual) != set(expected):
        raise ValueError("진단 격자 누락·중복·범위 오류")
    for col in ["observed_areas", "entered_observation", "left_observation"]:
        values = diagnostics[col]
        missing = diagnostics.quarter_idx.eq(0) if col != "observed_areas" else False
        if not values.isna().eq(missing).all():
            raise ValueError("관측 수 결측 또는 첫 분기 진입·이탈 표기 오류")
        if not np.isfinite(values.dropna()).all() or (values.dropna() < 0).any():
            raise ValueError("비정상 관측 수")
        if not values.dropna().mod(1).eq(0).all():
            raise ValueError("관측 수는 정수여야 함")
    amount = diagnostics.observed_raw_amount_krw
    if not amount.isna().eq(diagnostics.observed_areas.eq(0)).all():
        raise ValueError("미관측 금액은 0이 아니라 결측이어야 함")
    if not np.isfinite(amount.dropna()).all() or (amount.dropna() < 0).any():
        raise ValueError("비정상 관측 금액")
    cols = ["observed_areas", "entered_observation", "left_observation", "observed_raw_amount_krw"]
    result = diagnostics.groupby(keys[:2])[cols].sum(min_count=1).reset_index()
    result["missing_industries"] = (
        diagnostics.assign(absent=diagnostics.observed_areas.eq(0))
        .groupby(keys[:2])
        .absent.sum()
        .to_numpy()
    )
    for _, group in result.groupby("gu_name"):
        change = group.observed_areas.diff().iloc[1:].to_numpy()
        turnover = (group.entered_observation - group.left_observation).iloc[1:].to_numpy()
        if not np.array_equal(change, turnover):
            raise ValueError("관측 수 변화와 진입·이탈 불일치")
    return result


def draw(summary: pd.DataFrame, names: list[str], output: Path) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    groups = [
        (summary.loc[summary.gu_name.eq(names[0])], "Dongdaemun", "#B54142"),
        (summary.loc[~summary.gu_name.eq(names[0])], "20 controls (mean per gu)", "#167A8A"),
    ]
    fig, axes = plt.subplots(3, 1, figsize=(11, 10), sharex=True)
    for frame, label, color in groups:
        mean = frame.groupby("quarter_idx").mean(numeric_only=True)
        axes[0].plot(mean.index, mean.observed_areas, "o-", color=color, label=label)
        axes[1].plot(
            mean.index, mean.entered_observation, "o-", color=color, label=f"{label}: entered"
        )
        axes[1].plot(mean.index, mean.left_observation, "x--", color=color, label=f"{label}: left")
        amount = mean.observed_raw_amount_krw
        axes[2].plot(mean.index, amount / amount.loc[0] * 100, "o-", color=color, label=label)
    for ax in axes:
        ax.axvspan(11.5, 12.5, color="#888888", alpha=0.15)
        ax.axvline(12.5, color="#555555", linestyle=":")
        ax.grid(axis="y", alpha=0.2)
        ax.legend(fontsize=8, loc="best")
    axes[0].set(title="Observed area-industry pairs (not stores)", ylabel="Pairs per gu")
    axes[1].set(title="Observation entry / exit (not openings / closures)", ylabel="Pairs per gu")
    axes[2].set(
        title="Observed raw amount: descriptive index, not a policy effect", ylabel="2021Q1 = 100"
    )
    axes[2].set_xticks(range(16), QUARTER_LABELS, rotation=45, ha="right")
    fig.suptitle("Observation coverage and amount | 2024Q1 shaded: excluded only from estimation")
    fig.tight_layout()
    first = output / "observation_coverage.png"
    fig.savefig(first, dpi=150)
    plt.close(fig)

    matrix = summary.pivot(index="gu_name", columns="quarter_idx", values="missing_industries").loc[
        names
    ]
    fig, ax = plt.subplots(figsize=(12, 8))
    im = ax.imshow(matrix, vmin=0, vmax=4, cmap="YlOrRd", aspect="auto")
    for i, row in enumerate(matrix.to_numpy()):
        for q, value in enumerate(row):
            ax.text(
                q,
                i,
                str(int(value)),
                ha="center",
                va="center",
                fontsize=8,
                color="white" if value >= 3 else "black",
            )
    ax.set_yticks(range(len(names)), [GU_LABELS[n] for n in names])
    ax.set_xticks(range(16), QUARTER_LABELS, rotation=45, ha="right")
    ax.axvline(11.5, color="#555555", linestyle=":")
    ax.axvline(12.5, color="#555555", linestyle=":")
    ax.set_title(
        "Industries with no observed rows (out of 4)\n0 means rows exist; it does not prove complete coverage"
    )
    fig.colorbar(im, ax=ax, ticks=range(5), label="Absent industries (not a missing-sales rate)")
    fig.tight_layout()
    second = output / "industry_coverage.png"
    fig.savefig(second, dpi=150)
    plt.close(fig)
    return [first, second]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args(argv)
    audit_dir = HERE / "data/sales-audit" / args.snapshot.name
    # 매번 원본을 검사한다. 오래된 진단 CSV나 패널만으로 그림을 갱신하지 않는다.
    report = audit(args.snapshot, audit_dir, observed=True)
    if not report["panel_written"]:
        print("시각화 중단: " + "; ".join(report["blockers"]))
        return 2
    path = audit_dir / "observation-diagnostics.csv"
    names = selected_districts()
    summary = summarize(pd.read_csv(path), names)
    files = draw(summary, names, HERE / "figures")
    manifest = {
        "scope": "descriptive_observation_diagnostics_not_causal_effect",
        "snapshot": args.snapshot.name,
        "plan_sha256": report["plan_sha256"],
        "panel_sha256": report["panel_sha256"],
        "diagnostics_sha256": digest(path.read_bytes()),
        "source_code_sha256": report["code_sha256"],
        "visualize_sha256": digest(Path(__file__).read_bytes()),
        "figures": {f.name: digest(f.read_bytes()) for f in files},
    }
    (HERE / "visualization_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("관측 범위 그림 2개 생성; 인과효과 및 완전성 검증 아님")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
