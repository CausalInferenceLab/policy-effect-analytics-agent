"""리포트용 그림. 한글 폰트가 없는 CI 환경을 고려해 그림 라벨은 영문으로 둔다."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

TREAT, CTRL, GREY = "#D1495B", "#00798C", "#8D99AE"


def _finish(ax, out: str | Path):
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.3)
    fig = ax.get_figure()
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return Path(out)


def raw_trends(
    df: pd.DataFrame, y: str, time: str, group_col: str, treat_time, out, ylabel: str | None = None
):
    """처치/통제 집단 평균 추이 (가공 전 데이터 그대로)."""
    m = df.groupby([time, group_col])[y].mean().unstack()
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(m.index, m[1], "o-", color=TREAT, label="Treated")
    ax.plot(m.index, m[0], "s--", color=CTRL, label="Control")
    ax.axvline(treat_time - 0.5, color=GREY, ls=":", label="Policy start")
    ax.set(xlabel=time, ylabel=ylabel or y, title="Raw trends: treated vs control (group means)")
    ax.legend(frameon=False)
    return _finish(ax, out)


def event_study_plot(coefs: pd.DataFrame, out, ylabel: str = "Effect vs t=-1"):
    fig, ax = plt.subplots(figsize=(7, 4))
    pre = coefs["rel_time"] < 0
    for mask, c in ((pre, CTRL), (~pre, TREAT)):
        s = coefs[mask]
        ax.errorbar(
            s["rel_time"],
            s["coef"],
            yerr=[s["coef"] - s["ci_low"], s["ci_high"] - s["coef"]],
            fmt="o",
            color=c,
            capsize=3,
        )
    ax.axhline(0, color="black", lw=0.8)
    ax.axvline(-0.5, color=GREY, ls=":")
    ax.set(
        xlabel="Periods relative to policy (endpoints binned)",
        ylabel=ylabel,
        title="Event study (95% CI, cluster-robust)",
    )
    return _finish(ax, out)


def its_plot(df: pd.DataFrame, y: str, time: str, treat_time, fitted, counterfactual, out):
    d = df.sort_values(time)
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(d[time], d[y], "o", color=GREY, ms=4, label="Observed")
    ax.plot(d[time], fitted, color=TREAT, label="Fitted")
    post = d[time] >= treat_time
    ax.plot(
        d[time][post],
        counterfactual[post.values],
        "--",
        color=CTRL,
        label="Counterfactual (pre-trend)",
    )
    ax.axvline(treat_time, color=GREY, ls=":")
    ax.set(xlabel=time, ylabel=y, title="Interrupted time series")
    ax.legend(frameon=False)
    return _finish(ax, out)
