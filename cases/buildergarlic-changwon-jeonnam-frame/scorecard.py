"""스코어카드 — 보고서 지표 전체에 같은 추정기(이벤트 스터디 + 무작위화 추론)를 돌리고,
사전 등록한 규칙(indicators.yaml)으로 지표별·종합 성공/실패를 판정합니다.

    python scorecard.py            # data/panel.csv(핵심) + data/extended.csv(확장, 있으면) → scorecard.md / scorecard.json / figures/
    python scorecard.py --n-perm 299   # 빠른 점검용 (무작위화 추론 반복 수)

산출물
- scorecard.md / scorecard.json : 지표별 추정치·신뢰구간·판정, 보고서식 벤치마크(창원 vs 전국 시·대도시·경남 시, 전후 평균), 종합 판정,
                                  산업연관분석 대응(io_counterpart)
- figures/scorecard_forest.png   : 지표별 추정치와 95% 구간
- figures/benchmark_<지표>.png    : 창원과 비교군의 추이
make flow 가 만드는 report.md(핵심 4지표)와 숫자가 같도록 같은 core 추정기를 같은 설정으로 부릅니다.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from io_counterpart import expected_effects, render_md  # noqa: E402

from core.estimators import apply_abstention, event_study, placebo_time  # noqa: E402
from core.schema.plan import load_plan  # noqa: E402

PANEL, EXT = HERE / "data" / "panel.csv", HERE / "data" / "extended.csv"
FIG = HERE / "figures"
MERGED = "창원시"
LABEL = {
    "success": "✅ 목표 방향",
    "failure": "❌ 목표 반대",
    "undetermined": "⚪ 판별 불가",
    "no_data": "— 자료 없음",
}
OVERALL_KO = {
    "success": "성공 근거 있음(조건부)",
    "failure": "실패 근거 있음(조건부)",
    "mixed": "혼재",
    "undetermined": "판별 불가",
}
COLORS = {
    "success": "#2a9d8f",
    "failure": "#d1495b",
    "undetermined": "#8d99ae",
    "no_data": "#dddddd",
}


def load_config() -> dict:
    return yaml.safe_load((HERE / "indicators.yaml").read_text(encoding="utf-8"))


# ── 지표별 추정 ──────────────────────────────────────────────────────────────────────────────
def balanced_subset(
    df: pd.DataFrame, col: str, years: tuple[int, int] | None, merge_year: int
) -> pd.DataFrame:
    """지표의 수록 구간에서 모든 연도 값이 있는 단위만 남긴 균형 패널. 처치 단위는 반드시 포함."""
    d = df[["region_id", "year", "treated", col]].dropna(subset=[col]).copy()
    if years:
        d = d[(d["year"] >= years[0]) & (d["year"] <= years[1])]
    d = d[d["year"] != merge_year]
    all_years = set(d.loc[d["treated"] == 1, "year"])
    if not all_years:
        raise ValueError(f"{col}: 처치 단위(창원)의 값이 없습니다")
    full = d.groupby("region_id")["year"].apply(set)
    keep = full[full.apply(lambda s: s >= all_years)].index
    d = d[d["region_id"].isin(keep) & d["year"].isin(all_years)]
    return d.sort_values(["region_id", "year"]).reset_index(drop=True)


def estimate_indicator(d: pd.DataFrame, col: str, plan, treat_time: int, n_perm: int = 999):
    """plan.yaml 과 같은 설정의 이벤트 스터디(+RI, 가짜 시점, 보류 규칙). 창은 수록 기간에 맞춰 줄인다."""
    years = sorted(d["year"].unique())
    pre_years = [y for y in years if y < treat_time]
    lo = max(plan.estimator.window[0], min(years) - treat_time)
    hi = min(plan.estimator.window[1], max(years) - treat_time)
    ref = (
        plan.estimator.ref_period
        if (treat_time + plan.estimator.ref_period) in years
        else max(pre_years) - treat_time
    )
    import core.estimators.ri as ri_mod  # 반복 수를 바꿀 수 있게 (빠른 점검용)

    orig = ri_mod.event_study_ri.__defaults__
    if n_perm != 999:
        ri_mod.event_study_ri.__defaults__ = tuple(n_perm if v == 999 else v for v in orig)
    try:
        r = event_study(
            d, col, "region_id", "year", "treated", treat_time=treat_time, cluster="region_id", ref_period=ref,
            window=(lo, hi), pretrend_alpha=plan.thresholds.pretrend_alpha, alpha=plan.estimator.alpha,
            min_clusters=plan.thresholds.min_clusters,
        )  # fmt: skip
    finally:
        ri_mod.event_study_ri.__defaults__ = orig
    shift = next(
        (x.params.get("shift", 2) for x in plan.refutations if x.kind == "placebo_time"), None
    )
    if shift and len(pre_years) >= shift + 2:
        r.assumptions_checked["placebo_time"] = placebo_time(
            d, col, "region_id", "year", "treated", treat_time, shift=shift, cluster="region_id",
            alpha=plan.thresholds.pretrend_alpha,
        )  # fmt: skip
    r.assumptions_checked["window"] = [lo, hi]
    r.assumptions_checked["ref_period"] = ref
    r.assumptions_checked["years"] = [int(min(years)), int(max(years))]
    return apply_abstention(r, plan.abstention, plan.thresholds)


def classify(r, goal: str) -> tuple[str, str]:
    """지표별 판정 (indicators.yaml 의 규칙)."""
    if r.verdict == "not_identified":
        return "undetermined", "사전추세 기각 — 방향을 읽지 않음"
    if goal == "unknown":
        return "undetermined", "보고서가 방향을 정하지 않은 지표"
    if r.ci_low <= 0 <= r.ci_high:
        return "undetermined", "95% 구간이 0을 포함"
    sign, want = (1 if r.estimate > 0 else -1), (1 if goal == "increase" else -1)
    if sign == want:
        return "success", "구간이 0을 제외하고 목표 방향"
    return "failure", "구간이 0을 제외하고 목표 반대 방향"


def overall(rows: list[dict], scoring: dict) -> tuple[str, str]:
    decidable = [x for x in rows if x["class"] in ("success", "failure")]
    judged = [x for x in rows if x["class"] != "no_data"]
    primary = next((x for x in rows if x["col"] == scoring["primary"]), None)
    n_s = sum(x["class"] == "success" for x in decidable)
    n_f = sum(x["class"] == "failure" for x in decidable)
    if len(judged) < scoring.get("min_decidable", 3):
        return (
            "undetermined",
            f"판정 가능한 지표 {len(judged)}개 < {scoring.get('min_decidable', 3)}",
        )
    if n_s and n_f:
        return "mixed", f"목표 방향 {n_s}개, 반대 {n_f}개"
    if primary and primary["class"] == "failure" or (judged and n_f >= len(judged) / 2):
        return (
            "failure",
            f"1차 지표 {primary['class'] if primary else '-'}, 반대 방향 {n_f}/{len(judged)}",
        )
    if primary and primary["class"] == "success" and n_s >= len(judged) / 2 and n_f == 0:
        return "success", f"1차 지표 목표 방향, 목표 방향 {n_s}/{len(judged)}, 반대 0"
    return (
        "undetermined",
        f"목표 방향 {n_s}, 반대 {n_f}, 판별 불가 {len(judged) - n_s - n_f} (전체 {len(judged)})",
    )


# ── 보고서식 벤치마크 (B1 동시점 비교 + B2 전후 변화) ───────────────────────────────────────────
def benchmark(
    df: pd.DataFrame, col: str, groups: dict, pre: tuple[int, int], post: tuple[int, int]
) -> dict:
    d = df[["region_id", "year", "treated", col]].dropna(subset=[col])
    sets = {
        "changwon": [MERGED],
        "all_donors": sorted(set(d.loc[d["treated"] == 0, "region_id"])),
        "peer_big_cities": list(groups.get("peer_big_cities", [])),
        "gyeongnam_cities": list(groups.get("gyeongnam_cities", [])),
    }
    out = {}
    for g, units in sets.items():
        x = d[d["region_id"].isin(units)]
        a = x[(x["year"] >= pre[0]) & (x["year"] <= pre[1])].groupby("region_id")[col].mean()
        b = x[(x["year"] >= post[0]) & (x["year"] <= post[1])].groupby("region_id")[col].mean()
        if len(a) == 0 or len(b) == 0:
            out[g] = {"pre": None, "post": None, "change": None, "n": 0}
            continue
        out[g] = {
            "pre": float(a.mean()),
            "post": float(b.mean()),
            "change": float(b.mean() - a.mean()),
            "n": int(len(b)),
        }
    cw = out["changwon"]["change"]
    for g in ("all_donors", "peer_big_cities", "gyeongnam_cities"):
        ch = out[g]["change"]
        out[g]["diff_in_change"] = None if cw is None or ch is None else cw - ch
    return out


# ── 그림 (라벨은 영문: CI 환경에 한글 폰트가 없음) ──────────────────────────────────────────────
def forest_plot(rows: list[dict], out: Path) -> None:
    rows = [x for x in rows if x["class"] != "no_data"]
    n = len(rows)
    ncol = 3
    nrow = int(np.ceil(n / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(4.2 * ncol, 2.6 * nrow))
    axes = np.atleast_1d(axes).ravel()
    for ax, x in zip(axes, rows, strict=False):
        c = COLORS[x["class"]]
        ax.errorbar(
            [x["estimate"]],
            [0],
            xerr=[[x["estimate"] - x["ci"][0]], [x["ci"][1] - x["estimate"]]],
            fmt="o",
            color=c,
            capsize=4,
        )
        ax.axvline(0, color="black", lw=0.8)
        ax.set_yticks([])
        ax.set_title(
            f"{x['col']} ({x['scale']})\n{x['class']} · RI p={x['p_value']:.2f}", fontsize=9
        )
        ax.spines[["top", "right", "left"]].set_visible(False)
    for ax in axes[n:]:
        ax.axis("off")
    fig.suptitle(
        "Post-merger average effect vs. 2009 (event study, randomization-inference 95% CI)",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def benchmark_plot(df: pd.DataFrame, col: str, groups: dict, merge_year: int, out: Path) -> None:
    d = df[["region_id", "year", "treated", col]].dropna(subset=[col])
    series = {
        "Changwon (merged boundary)": d[d["region_id"] == MERGED].groupby("year")[col].mean(),
        "62 donor cities (mean)": d[d["treated"] == 0].groupby("year")[col].mean(),
        "Big cities 500k+ (mean)": d[d["region_id"].isin(groups.get("peer_big_cities", []))]
        .groupby("year")[col]
        .mean(),
        "Gyeongnam cities (mean)": d[d["region_id"].isin(groups.get("gyeongnam_cities", []))]
        .groupby("year")[col]
        .mean(),
    }
    styles = [("#d1495b", "o-"), ("#00798c", "s--"), ("#edae49", "^:"), ("#66a182", "v-.")]
    fig, ax = plt.subplots(figsize=(7, 4))
    for (name, s), (c, st) in zip(series.items(), styles, strict=False):
        if len(s):
            ax.plot(s.index, s.values, st, color=c, label=name, ms=4)
    ax.axvline(merge_year, color="#8d99ae", ls=":", label="Merger (2010)")
    ax.set(xlabel="year", ylabel=col, title=f"{col}: Changwon vs comparison groups")
    ax.legend(frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


# ── 마크다운 ───────────────────────────────────────────────────────────────────────────────────
def _f(v, nd=2):
    return "-" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:,.{nd}f}"


def render(res: dict, cfg: dict) -> str:
    rows = res["indicators"]
    ov = res["overall"]
    L = [
        "# 스코어카드 — 전남·광주 보고서의 기준으로 본 창원 통합(2010)",
        "",
        f"> 실행 {res['run_at']} · {'⚠️ 합성 데이터(결과 해석 금지)' if res['synthetic_data'] else '실데이터'} · "
        f"판정 규칙은 `indicators.yaml`(결과 전 커밋) · 학습·연구용 분석이며 공식 평가가 아닙니다.",
        "",
        f"## 종합 판정: **{OVERALL_KO[ov['verdict']]}** — {ov['reason']}",
        "",
        "판정 가능한 지표 가운데 목표 방향으로 0과 구별되는 것(✅)과 반대 방향(❌)을 세고, 1차 지표(사업체 종사자수)를 우선합니다. "
        "⚪는 '효과 없음'이 아니라 '이 설계(처치 단위 1개, 무작위화 추론)로는 가를 수 없음'입니다.",
        "",
        "## 1. 지표별 판정 (통합 후 평균효과, 2009년 기준, 무작위화 추론 95% 구간)",
        "",
        "| 지표 | 영역 | 목표 방향 | 추정치 [95% CI] | RI p | 사전추세 p | 사전/사후 기간 | 핵심 판정 | 스코어 |",
        "|---|---|---|---|---:|---:|---|---|---|",
    ]
    for x in rows:
        if x["class"] == "no_data":
            L.append(
                f"| {x['name']} | {x['domain']} | {x['goal']} | — | — | — | — | — | {LABEL['no_data']} ({x.get('note', '')}) |"
            )
            continue
        pt = x["pretrend"].get("p_value")
        L.append(
            f"| {x['name']} | {x['domain']} | {x['goal']} | {x['estimate']:+.3f} [{x['ci'][0]:.3f}, {x['ci'][1]:.3f}] | "
            f"{x['p_value']:.3f} | {_f(pt, 3)} | {x['n_pre']}/{x['n_post']} | {x['verdict']} | {LABEL[x['class']]} — {x['why']} |"
        )
    pre, post = cfg["pre_window"], cfg["post_window"]
    L += [
        "",
        f"## 2. 보고서식 벤치마크 — 통합 전({pre[0]}~{pre[1]}) → 후({post[0]}~{post[1]}) 평균의 변화 (B1·B2)",
        "",
        "창원의 변화에서 비교군의 변화를 뺀 값(변화 차이)이 양수면 비교군보다 더 올랐다는 뜻입니다. 판정에는 쓰지 않는 보조 정보입니다.",
        "",
        "| 지표 | 창원 전→후 | 전국 시 62곳 전→후 (변화 차이) | 대도시 11곳 (변화 차이) | 경남 시 5곳 (변화 차이) |",
        "|---|---|---|---|---|",
    ]
    for x in rows:
        b = x.get("benchmark")
        if not b or b["changwon"]["pre"] is None:
            continue
        cw = b["changwon"]

        def cell(g, b=b):
            v = b[g]
            if v["pre"] is None:
                return "-"
            return f"{_f(v['pre'])}→{_f(v['post'])} ({v['diff_in_change']:+.2f})"

        L.append(
            f"| {x['name']} | {_f(cw['pre'])}→{_f(cw['post'])} ({cw['change']:+.2f}) | {cell('all_donors')} | {cell('peer_big_cities')} | {cell('gyeongnam_cities')} |"
        )
    L += ["", "## 3. 산업연관분석 대응 (보고서 §Ⅲ-2 의 창원 버전)", ""]
    L += render_md(res["io_counterpart"]).split("\n")[2:]
    L += [
        "",
        "## 4. 그림",
        "",
        "![forest](figures/scorecard_forest.png)",
        "",
        *[
            f"![{x['col']}](figures/benchmark_{x['col']}.png)"
            for x in rows
            if x["class"] != "no_data"
        ],
        "",
        "## 5. 지표를 뺀 이유 (자료 수집 실패만 해당)",
        "",
        *(
            [f"- {x['name']}: {x.get('note', '')}" for x in rows if x["class"] == "no_data"]
            or ["- 없음"]
        ),
    ]
    return "\n".join(L) + "\n"


# ── 실행 ───────────────────────────────────────────────────────────────────────────────────────
def run(n_perm: int = 999, make_figs: bool = True) -> dict:
    cfg = load_config()
    plan = load_plan(HERE / "plan.yaml")
    core = pd.read_csv(PANEL)
    ext = pd.read_csv(EXT) if EXT.exists() else None
    src = PANEL.with_suffix(".source.json")
    src_meta = json.loads(src.read_text("utf-8")) if src.exists() else {}
    synthetic = bool(src_meta.get("synthetic_data")) if src.exists() else plan.synthetic_data
    indicator_errors = src_meta.get("indicator_errors", {})  # fetch.py 가 남긴 지표별 수집 실패 사유
    treat_time, merge_year = cfg["treat_time"], cfg["merge_year"]
    FIG.mkdir(exist_ok=True)
    rows = []
    for ind in cfg["indicators"]:
        col = ind["col"]
        df = core if ind.get("core") else ext
        base = {"col": col, "name": ind["name"], "domain": ind["domain"], "goal": ind["goal"], "goal_basis": ind["goal_basis"],
                "core": bool(ind.get("core")), "scale": ind.get("scale", "")}  # fmt: skip
        if df is None or col not in df.columns or df[col].notna().sum() == 0:
            note = indicator_errors.get(col) or "통계표 미확인/수집 실패 (fetch.py --probe)"
            rows.append({**base, "class": "no_data", "note": note})
            continue
        try:
            d = balanced_subset(df, col, tuple(ind.get("years", ())) or None, merge_year)
            r = estimate_indicator(d, col, plan, treat_time, n_perm=n_perm)
        except Exception as err:  # noqa: BLE001 — 한 지표가 깨져도 나머지는 계속
            rows.append({**base, "class": "no_data", "note": f"추정 실패: {str(err)[:200]}"})
            continue
        cls, why = classify(r, ind["goal"])
        pre_n = int((d.loc[d["treated"] == 1, "year"] < treat_time).sum())
        post_n = int((d.loc[d["treated"] == 1, "year"] >= treat_time).sum())
        rows.append({
            **base, "estimate": r.estimate, "ci": [r.ci_low, r.ci_high], "p_value": r.p_value, "verdict": r.verdict,
            "triggers": r.triggers, "pretrend": r.assumptions_checked.get("parallel_pretrends", {}),
            "placebo_time": r.assumptions_checked.get("placebo_time"), "n_pre": pre_n, "n_post": post_n,
            "n_units": int(d["region_id"].nunique()), "window": r.assumptions_checked.get("window"),
            "years": r.assumptions_checked.get("years"), "class": cls, "why": why,
            "coefs": r.extra["coefs"].to_dict("records") if "coefs" in r.extra else None,
            "benchmark": benchmark(df, col, cfg["groups"], tuple(cfg["pre_window"]), tuple(cfg["post_window"])),
        })  # fmt: skip
        if make_figs:
            benchmark_plot(df, col, cfg["groups"], merge_year, FIG / f"benchmark_{col}.png")
    verdict, reason = overall(rows, cfg["scoring"])
    cw = core[core["treated"] == 1].set_index("year")
    io = expected_effects(
        baseline_employees=float(cw.loc[2009, "employees"]) if 2009 in cw.index else None,
        baseline_population=float(cw.loc[2011, "population"]) if 2011 in cw.index else None,
    )
    res = {
        "case_id": plan.case_id, "run_at": datetime.now(UTC).isoformat(timespec="seconds"), "synthetic_data": synthetic,
        "n_perm": n_perm, "overall": {"verdict": verdict, "reason": reason}, "indicators": rows, "io_counterpart": io,
        "groups": cfg["groups"], "pre_window": cfg["pre_window"], "post_window": cfg["post_window"],
    }  # fmt: skip
    if make_figs:
        forest_plot(rows, FIG / "scorecard_forest.png")
    (HERE / "scorecard.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2, default=float), "utf-8"
    )
    (HERE / "scorecard.md").write_text(render(res, cfg), "utf-8")
    return res


def main(argv=None) -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--n-perm", type=int, default=999)
    ap.add_argument("--no-figs", action="store_true")
    a = ap.parse_args(argv)
    if not PANEL.exists():
        sys.exit(
            "data/panel.csv 가 없습니다. 먼저 python fetch.py (또는 --simulate) 를 실행하세요."
        )
    res = run(a.n_perm, make_figs=not a.no_figs)
    print(f"[scorecard] 종합: {OVERALL_KO[res['overall']['verdict']]} — {res['overall']['reason']}")
    for x in res["indicators"]:
        if x["class"] == "no_data":
            print(f"  {x['col']:28s} {LABEL['no_data']} {x.get('note', '')[:80]}")
        else:
            print(
                f"  {x['col']:28s} {x['estimate']:+.3f} [{x['ci'][0]:.3f}, {x['ci'][1]:.3f}] p={x['p_value']:.2f} {LABEL[x['class']]}"
            )
    print(f"→ {HERE / 'scorecard.md'}")


if __name__ == "__main__":
    main()
