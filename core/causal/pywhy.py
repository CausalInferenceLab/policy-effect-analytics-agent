"""PyWhy(DoWhy)·CausalML 로 같은 질문을 다시 묻기 — 기본 추정의 '두 번째 의견'.

    단위 × 시점 패널 ──▶ 단위별 정책 전후 변화(Δy) 표
                          T   = 처치 여부(0/1)
                          Δy  = 정책 뒤 평균 − 정책 전 평균 (주 지표)
                          y_pre 와 plan 의 covariates(정책 전 평균) = 공통 원인 후보
    DoWhy   인과 그래프(공통 원인 → T, 공통 원인 → Δy, T → Δy) → 식별(뒷문 기준) → 선형 회귀 추정
            → 반박 검정 3종: 가짜 처치(순서 섞기) · 무작위 공통 원인 추가 · 80% 부분 표본
    CausalML T-러너로 단위별 효과(CATE) — 처치·비교가 각각 10곳 이상일 때만. 정책 전 수준(y_pre)별로 나눠 본다.

Δy 의 처치-비교 차이는 2×2 이중차분과 같은 양이다(공통 원인을 넣지 않으면 정확히 같음). 그래서 기본 추정과
방향·크기가 크게 다르면 그것 자체가 점검 신호다. 판정은 바꾸지 않는다.

라이브러리는 선택 설치: pip install -e ".[causal]"  (dowhy, causalml). 없으면 그 단계만 '설치 안 됨'으로 남긴다.
"""

from __future__ import annotations

import json
import math
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

MIN_HTE_UNITS = 10  # CausalML 단위별 효과: 처치·비교 각각 이 수 이상일 때만
N_SIM = 100  # 반박 검정 반복 수


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _as_time(s: pd.Series):
    """시점 열을 비교 가능한 값으로: 숫자면 숫자, 아니면 날짜."""
    num = pd.to_numeric(s, errors="coerce")
    if num.notna().all():
        return num
    return pd.to_datetime(s, errors="coerce")


def unit_changes(plan, df: pd.DataFrame, outcome_col: str | None = None) -> pd.DataFrame:
    """패널 → 단위별 [T, dy, y_pre, <공변량 정책 전 평균>]. 처치 시점은 단위별 first_treat 또는 treat_time."""
    uid, tcol = plan.unit.id_col, plan.time.col
    y = outcome_col or plan.primary_outcome.col
    tr = plan.treatment
    d = df[
        [c for c in {uid, tcol, tr.group_col, y, *(tr.first_treat_col or "",)} if c in df]
    ].copy()
    covs = [c for c in plan.estimator.covariates if c in df.columns]
    for c in covs:
        d[c] = df[c]
    d["_t"] = _as_time(d[tcol])
    if tr.treat_time is not None:
        cut = _as_time(pd.Series([tr.treat_time])).iloc[0]
        d["_cut"] = cut
    else:  # 시차 도입: 처치 단위는 자기 시점, 비교 단위는 처치 시점들의 중앙값
        ft = _as_time(df[tr.first_treat_col])
        d["_cut"] = ft
        med = ft.dropna().median()
        d.loc[d["_cut"].isna(), "_cut"] = med
    d["_post"] = d["_t"] >= d["_cut"]
    g = d.groupby([uid, "_post"])
    pre = g[y].mean().xs(False, level="_post")
    post = g[y].mean().xs(True, level="_post")
    out = pd.DataFrame({"y_pre": pre, "dy": post - pre}).dropna()
    out["T"] = d.groupby(uid)[tr.group_col].max().reindex(out.index).astype(int)
    for c in covs:
        out[c] = d[~d["_post"]].groupby(uid)[c].mean().reindex(out.index)
    return out.dropna()


def dowhy_check(frame: pd.DataFrame, covariates: list[str], seed: int = 7) -> dict:
    try:
        import dowhy  # noqa: F401
        from dowhy import CausalModel
    except ImportError:
        return {
            "status": "not_installed",
            "message": 'pip install -e ".[causal]" 로 dowhy 를 설치하세요',
        }
    common = ["y_pre", *covariates]
    np.random.seed(seed)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = CausalModel(data=frame, treatment="T", outcome="dy", common_causes=common)
        estimand = model.identify_effect(proceed_when_unidentifiable=True)
        est = model.estimate_effect(
            estimand, method_name="backdoor.linear_regression", test_significance=True
        )
        base = _num(est.value)
        refs = []
        for method, kw, label, rule in (
            (
                "placebo_treatment_refuter",
                {"placebo_type": "permute", "num_simulations": N_SIM},
                "가짜 처치(처치 순서 섞기)",
                "가짜 처치의 효과는 0 근처여야 해요",
            ),
            (
                "random_common_cause",
                {"num_simulations": N_SIM},
                "무작위 공통 원인 추가",
                "아무 관련 없는 변수를 넣어도 추정치가 거의 같아야 해요",
            ),
            (
                "data_subset_refuter",
                {"subset_fraction": 0.8, "num_simulations": N_SIM},
                "80% 부분 표본",
                "일부 단위를 빼도 추정치가 거의 같아야 해요",
            ),
        ):
            try:
                r = model.refute_estimate(estimand, est, method_name=method, random_seed=seed, **kw)
            except Exception as ex:  # 라이브러리 버전에 따라 일부 반박이 실패할 수 있다
                refs.append(
                    {"method": method, "label": label, "status": "error", "message": str(ex)[:160]}
                )
                continue
            new = _num(r.new_effect)
            p = (
                _num((r.refutation_result or {}).get("p_value"))
                if isinstance(r.refutation_result, dict)
                else None
            )
            if method == "placebo_treatment_refuter":
                ok = new is not None and base is not None and abs(new) < max(abs(base), 1e-9) * 0.5
            else:
                ok = (
                    new is not None
                    and base is not None
                    and abs(new - base) <= max(abs(base) * 0.2, 1e-9)
                )
            refs.append(
                {
                    "method": method,
                    "label": label,
                    "rule": rule,
                    "new_effect": new,
                    "p_value": p,
                    "status": "pass" if ok else "warn",
                }
            )
    try:
        backdoor = list(estimand.get_backdoor_variables())
    except Exception:
        backdoor = common
    try:
        ci = [_num(v) for v in np.ravel(est.get_confidence_intervals())]
    except Exception:
        ci = None
    return {
        "status": "ok",
        "graph": {
            "nodes": ["T", "dy", *common],
            "edges": [["T", "dy"], *[[c, "T"] for c in common], *[[c, "dy"] for c in common]],
        },
        "identification": {"method": "backdoor", "adjust_for": backdoor},
        "estimate": base,
        "ci": ci,
        "refutations": refs,
    }


def causalml_hte(frame: pd.DataFrame, covariates: list[str]) -> dict:
    n_t, n_c = int(frame["T"].sum()), int((1 - frame["T"]).sum())
    if min(n_t, n_c) < MIN_HTE_UNITS:
        return {
            "status": "skipped",
            "message": f"처치 {n_t}곳 · 비교 {n_c}곳 — 단위별 효과는 각각 {MIN_HTE_UNITS}곳 이상일 때만 봅니다",
        }
    try:
        from causalml.inference.meta import BaseTRegressor
        from sklearn.linear_model import LinearRegression
    except ImportError:
        return {
            "status": "not_installed",
            "message": 'pip install -e ".[causal]" 로 causalml 을 설치하세요',
        }
    feats = ["y_pre", *covariates]
    X = frame[feats].to_numpy(dtype=float)
    T = frame["T"].to_numpy()
    y = frame["dy"].to_numpy(dtype=float)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        learner = BaseTRegressor(learner=LinearRegression(), control_name=0)
        ate, lb, ub = learner.estimate_ate(X=X, treatment=T, y=y)
        cate = np.ravel(learner.fit_predict(X=X, treatment=T, y=y))
    groups = []
    q = pd.qcut(
        frame["y_pre"], 3, labels=["정책 전 낮음", "중간", "정책 전 높음"], duplicates="drop"
    )
    for name, idx in frame.groupby(q, observed=True).groups.items():
        m = frame.index.isin(idx)
        groups.append({"group": str(name), "n": int(m.sum()), "cate_mean": _num(cate[m].mean())})
    return {
        "status": "ok",
        "learner": "T-learner (LinearRegression)",
        "features": feats,
        "ate": _num(np.ravel([ate])[0]),
        "ate_ci": [_num(np.ravel([lb])[0]), _num(np.ravel([ub])[0])],
        "cate_quantiles": {
            k: _num(np.quantile(cate, v)) for k, v in (("p10", 0.1), ("p50", 0.5), ("p90", 0.9))
        },
        "by_baseline": groups,
    }


def check_case(case_dir: str | Path, data_path: str | Path | None = None) -> dict:
    """케이스 하나: plan.yaml + 분석용 표 → DoWhy·CausalML 점검 결과 dict."""
    from core.schema.plan import load_plan

    case = Path(case_dir)
    plan = load_plan(case / "plan.yaml")
    path = Path(data_path) if data_path else case / plan.data_sources[0].path
    if not path.exists():
        return {
            "case": case.name,
            "status": "no_data",
            "message": f"{path} 가 없습니다. fetch.py 로 분석용 표를 만든 뒤 다시 실행하세요",
        }
    df = pd.read_csv(path)
    o = plan.primary_outcome
    frame = unit_changes(plan, df, o.col)
    covs = [c for c in plan.estimator.covariates if c in frame.columns]
    did = _num(frame.loc[frame["T"] == 1, "dy"].mean() - frame.loc[frame["T"] == 0, "dy"].mean())
    base = None
    log = case / "flow_log.json"
    if log.exists():
        try:
            rows = json.loads(log.read_text(encoding="utf-8")).get("results") or []
            r = next((x for x in rows if x.get("outcome") == o.col), rows[0] if rows else None)
            base = _num((r or {}).get("estimate"))
        except (ValueError, AttributeError):
            base = None
    dw = dowhy_check(frame, covs)
    n_t = int(frame["T"].sum())
    if dw.get("status") == "ok" and n_t < MIN_HTE_UNITS:
        dw["warning"] = (
            f"처치 단위가 {n_t}곳뿐이라 회귀 신뢰구간은 참고용입니다(기본 추정은 무작위화 추론을 씁니다)"
        )
    same_dir = None
    if dw.get("estimate") is not None and base is not None:
        same_dir = bool(np.sign(dw["estimate"]) == np.sign(base))
    return {
        "case": case.name,
        "status": "ok",
        "data": {"path": str(path), "rows": int(len(df))},
        "outcome": {"col": o.col, "name": o.name, "unit": o.unit, "expected": o.expected_direction},
        "units": {"treated": int(frame["T"].sum()), "control": int((1 - frame["T"]).sum())},
        "did_2x2": did,
        "baseline_estimate": base,
        "same_direction_as_baseline": same_dir,
        "dowhy": dw,
        "causalml": causalml_hte(frame, covs),
        "note": "두 번째 의견입니다. 판정은 plan.yaml 과 기본 추정(make flow)이 냅니다.",
    }


def write(case_dir: str | Path, result: dict) -> Path:
    out = Path(case_dir) / "pywhy_check.json"
    out.write_text(
        json.dumps(result, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8"
    )
    return out
