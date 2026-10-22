"""보조 추정 — 합성통제(synthetic control, Abadie·Diamond·Hainmueller 2010)와 placebo-in-space 추론.

core 에는 아직 합성통제가 없어(README '다음: 합성통제') 이 케이스 안에서만 씁니다. 주 추정(make flow)은
plan.yaml 의 event_study + 무작위화 추론이고, 여기서는 같은 패널로 '가상의 창원'(비교 시들의 가중 평균)을
만들어 통합 후 실제 창원과의 차이를 봅니다.

    python synth.py                 # data/panel.csv 가 있어야 함(fetch.py 먼저)
    → synth_results.json, synth_report.md, figures/synth_<지표>_path.png, figures/synth_<지표>_gaps.png

방법
- 가중치 w ≥ 0, Σw = 1 로 통합 전(1998~2009) 결과 경로를 가장 잘 맞추는 비교 시 조합(SLSQP).
- 추론: 모든 비교 시를 차례로 '가짜 창원'으로 두고 같은 계산을 반복(placebo-in-space).
  (통합 후 RMSPE ÷ 통합 전 RMSPE) 비율의 순위로 p값을 냅니다. 사전 적합이 나쁜 가짜(사전 RMSPE 가
  창원의 5배 초과)는 제외한 p값도 함께 냅니다.
- 민감도: 양(+)의 가중치를 받은 비교 시를 하나씩 빼고 다시 추정(leave-one-out).
한계: 처치 단위가 하나라 표준오차가 없고, p값은 비교 시 수(62)에 묶입니다. 결과 해석은 discussion.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import yaml
from scipy.optimize import minimize, nnls

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
TREAT, CTRL, GREY = "#D1495B", "#00798C", "#8D99AE"


def fit_weights(y1_pre: np.ndarray, y0_pre: np.ndarray) -> np.ndarray:
    """min ‖y1 − Y0·w‖² s.t. w ≥ 0, Σw = 1.  y0_pre: (T0, J)."""
    y1, y0 = np.asarray(y1_pre, float), np.asarray(y0_pre, float)
    scale = float(np.std(y1)) or 1.0
    a, b = y0 / scale, y1 / scale
    j = a.shape[1]

    def f(w):
        r = a @ w - b
        return float(r @ r)

    def g(w):
        return 2 * a.T @ (a @ w - b)

    res = minimize(
        f,
        np.full(j, 1 / j),
        jac=g,
        bounds=[(0.0, 1.0)] * j,
        constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1, "jac": lambda w: np.ones(j)}],
        method="SLSQP",
        options={"maxiter": 2000, "ftol": 1e-12},
    )
    w = np.clip(res.x, 0, None)
    if not res.success or w.sum() <= 0:  # 드물게 실패하면 합=1 제약을 큰 벌점 행으로 넣은 NNLS
        big = 1e3
        w, _ = nnls(np.vstack([a, big * np.ones((1, j))]), np.append(b, big))
    return w / w.sum()


def synth_one(wide: pd.DataFrame, treated: str, treat_time: int, donors: list[str]) -> dict:
    """wide: index=연도, columns=단위. 2010 같은 빠진 연도는 그대로 둔다(행이 없음)."""
    years = wide.index.to_numpy()
    pre = years < treat_time
    y1 = wide[treated].to_numpy(float)
    y0 = wide[donors].to_numpy(float)
    w = fit_weights(y1[pre], y0[pre])
    synthetic = y0 @ w
    gap = y1 - synthetic
    pre_rmspe = float(np.sqrt(np.mean(gap[pre] ** 2)))
    post_rmspe = float(np.sqrt(np.mean(gap[~pre] ** 2)))
    return {
        "unit": treated,
        "years": [int(y) for y in years],
        "actual": y1.tolist(),
        "synthetic": synthetic.tolist(),
        "gap": gap.tolist(),
        "weights": {d: float(x) for d, x in zip(donors, w, strict=True) if x > 1e-4},
        "pre_rmspe": pre_rmspe,
        "post_rmspe": post_rmspe,
        "rmspe_ratio": post_rmspe / pre_rmspe if pre_rmspe > 0 else float("inf"),
        "post_mean_gap": float(np.mean(gap[~pre])),
    }


def placebo_in_space(
    wide: pd.DataFrame, treated: str, treat_time: int, donors: list[str], max_pre_ratio: float = 5.0
) -> tuple[dict, dict[str, dict], dict]:
    main = synth_one(wide, treated, treat_time, donors)
    placebos = {d: synth_one(wide, d, treat_time, [x for x in donors if x != d]) for d in donors}
    ratios = np.array([p["rmspe_ratio"] for p in placebos.values()])
    p_ratio = float((1 + np.sum(ratios >= main["rmspe_ratio"])) / (1 + len(ratios)))
    ok = [d for d in donors if placebos[d]["pre_rmspe"] <= max_pre_ratio * main["pre_rmspe"]]
    gaps = np.array([abs(placebos[d]["post_mean_gap"]) for d in ok])
    p_gap = float((1 + np.sum(gaps >= abs(main["post_mean_gap"]))) / (1 + len(ok)))
    rank = int(1 + np.sum(ratios > main["rmspe_ratio"]))
    inference = {
        "p_rmspe_ratio": p_ratio,
        "rank_rmspe_ratio": f"{rank}/{1 + len(ratios)}",
        "p_post_gap_filtered": p_gap,
        "n_placebo_used_for_gap_p": len(ok),
        "max_pre_ratio": max_pre_ratio,
    }
    return main, placebos, inference


def leave_one_out(
    wide: pd.DataFrame, treated: str, treat_time: int, donors: list[str], weights: dict, min_w=0.01
) -> dict[str, float]:
    out = {}
    for d, wv in weights.items():
        if wv >= min_w:
            r = synth_one(wide, treated, treat_time, [x for x in donors if x != d])
            out[d] = r["post_mean_gap"]
    return out


# ── 그림 (CI 에 한글 폰트가 없어 라벨은 영문) ───────────────────────────────────────────────────
def _finish(ax, out):
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.3)
    fig = ax.get_figure()
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def path_plot(res: dict, merge_year: int, ylabel: str, out: Path, synthetic_flag: bool):
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(res["years"], res["actual"], "o-", color=TREAT, label="Treated city (actual)")
    ax.plot(res["years"], res["synthetic"], "s--", color=CTRL, label="Synthetic control")
    ax.axvline(merge_year, color=GREY, ls=":", label=f"Merger ({merge_year}, excluded)")
    title = "Synthetic control: actual vs synthetic"
    if synthetic_flag:
        title += " (SIMULATED DATA)"
    ax.set(xlabel="year", ylabel=ylabel, title=title)
    ax.legend(frameon=False)
    _finish(ax, out)


def gaps_plot(res: dict, placebos: dict, merge_year: int, ylabel: str, out: Path, max_pre_ratio):
    fig, ax = plt.subplots(figsize=(7, 4))
    for p in placebos.values():
        if p["pre_rmspe"] <= max_pre_ratio * res["pre_rmspe"]:
            ax.plot(p["years"], p["gap"], color=GREY, alpha=0.35, lw=0.8)
    ax.plot(res["years"], res["gap"], color=TREAT, lw=2.2, label="Treated city")
    ax.plot([], [], color=GREY, alpha=0.5, label="Placebo cities (good pre-fit)")
    ax.axhline(0, color="black", lw=0.8)
    ax.axvline(merge_year, color=GREY, ls=":")
    ax.set(xlabel="year", ylabel=f"Gap: actual - synthetic ({ylabel})",
           title="Placebo-in-space: each control city as a fake treated unit")  # fmt: skip
    ax.legend(frameon=False)
    _finish(ax, out)


# ── 실행 ───────────────────────────────────────────────────────────────────────────────────────
def run(case_dir: Path = HERE, max_pre_ratio: float = 5.0) -> dict:
    plan = yaml.safe_load((case_dir / "plan.yaml").read_text(encoding="utf-8"))
    unit, time = plan["unit"]["id_col"], plan["time"]["col"]
    treat_time = int(plan["treatment"]["treat_time"])
    group = plan["treatment"]["group_col"]
    panel = pd.read_csv(case_dir / "data" / "panel.csv")
    src = case_dir / "data" / "panel.source.json"
    synthetic_flag = bool(plan.get("synthetic_data")) or (
        src.exists() and json.loads(src.read_text("utf-8")).get("synthetic_data") is True
    )
    treated_units = sorted(panel.loc[panel[group] == 1, unit].unique())
    if len(treated_units) != 1:
        raise ValueError(f"합성통제는 처치 단위 1개용입니다 (지금 {len(treated_units)}개)")
    treated = treated_units[0]
    merge_year = treat_time - 1
    figdir = case_dir / "figures"
    figdir.mkdir(exist_ok=True)
    results = {
        "case_id": plan["case_id"],
        "synthetic_data": synthetic_flag,
        "treated": treated,
        "treat_time": treat_time,
        "outcomes": {},
    }
    rows, n_donors = [], 0
    for o in plan["outcomes"]:
        col = o["col"]
        wide = panel.pivot(index=time, columns=unit, values=col).sort_index()
        donors = [c for c in wide.columns if c != treated and wide[c].notna().all()]
        if len(donors) < 5:
            raise ValueError(f"{col}: 결측 없는 비교 시가 {len(donors)}개뿐입니다")
        main, placebos, inf = placebo_in_space(wide, treated, treat_time, donors, max_pre_ratio)
        loo = leave_one_out(wide, treated, treat_time, donors, main["weights"])
        top = sorted(main["weights"].items(), key=lambda kv: -kv[1])[:5]
        results["outcomes"][col] = {
            "name": o["name"],
            "main": main,
            "inference": inf,
            "leave_one_out": loo,
            "n_donors": len(donors),
            "placebo_rmspe_ratios": {d: p["rmspe_ratio"] for d, p in placebos.items()},
        }
        path_plot(main, merge_year, col, figdir / f"synth_{col}_path.png", synthetic_flag)
        gaps_plot(main, placebos, merge_year, col, figdir / f"synth_{col}_gaps.png", max_pre_ratio)
        loo_txt = f"{min(loo.values()):+.3f} ~ {max(loo.values()):+.3f}" if loo else "-"
        n_donors = len(donors)
        rows.append(
            f"| {o['name']} | {main['pre_rmspe']:.4f} | {main['post_mean_gap']:+.4f} | "
            f"{main['rmspe_ratio']:.2f} | {inf['p_rmspe_ratio']:.3f} ({inf['rank_rmspe_ratio']}) | "
            f"{inf['p_post_gap_filtered']:.3f} (n={inf['n_placebo_used_for_gap_p']}) | {loo_txt} | "
            + ", ".join(f"{d} {w:.2f}" for d, w in top)
            + " |"
        )
    lines = ["# 합성통제(보조) 결과", ""]
    if synthetic_flag:
        lines += [
            "> **⚠️ 합성(simulated) 데이터로 만든 결과입니다. 실제 통합 효과가 아닙니다.**",
            "",
        ]
    lines += [
        f"처치 단위: {treated} · 첫 사후연도: {treat_time} · 비교 시: {n_donors}곳",
        "",
        "| 지표 | 통합 전 RMSPE | 통합 후 평균 격차 | RMSPE 비율(후/전) | p(비율 순위) | p(격차, 적합 양호 placebo) | LOO 범위 | 상위 가중치 |",
        "|---|---:|---:|---:|---:|---:|---|---|",
        *rows,
        "",
        "읽는 법: 통합 후 평균 격차 = 실제 창원 − 가상의 창원(통합 후 연도 평균). RMSPE 비율이 placebo 들보다 "
        "유독 크면(p 작음) 통합 후 격차가 우연으로 보기 어렵다는 뜻. p 는 비교 시 수에 묶이므로 "
        "0.05 아래라도 '근거 있음'이 아니라 '조건부'로 읽는다. LOO 범위는 가중치 상위 시를 하나씩 뺐을 때의 격차.",
        "",
        "그림: "
        + " · ".join(
            f"`figures/synth_{o['col']}_path.png` `figures/synth_{o['col']}_gaps.png`"
            for o in plan["outcomes"]
        ),
    ]
    (case_dir / "synth_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), "utf-8"
    )
    (case_dir / "synth_report.md").write_text("\n".join(lines) + "\n", "utf-8")
    return results


def main() -> None:
    r = run()
    flag = " [합성 데이터]" if r["synthetic_data"] else ""
    for col, x in r["outcomes"].items():
        m, i = x["main"], x["inference"]
        print(
            f"[synth]{flag} {col}: 통합 후 평균 격차 {m['post_mean_gap']:+.4f}, RMSPE 비율 {m['rmspe_ratio']:.2f}, "
            f"p(비율 순위)={i['p_rmspe_ratio']:.3f}, p(격차)={i['p_post_gap_filtered']:.3f}"
        )
    print(f"→ {HERE / 'synth_report.md'}")


if __name__ == "__main__":
    main()
