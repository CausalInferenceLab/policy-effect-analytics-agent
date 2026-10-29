"""동결한 월별 파일 모형을 같은 발행 시점·표본에서 평가하고 주별 차이를 계산한다."""

import json
import subprocess

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from .common import CASE, sha256, utcnow, write_json
from .deepening_archive_data import MANIFEST, OUT, RAW, checked, reference, verify
from .deepening_archive_models import (
    KEY,
    QCOLS,
    TRAINING,
    archive_profile_prediction,
    load_feature_audit,
    ordered_predictions,
    predict_quantiles,
    read_features,
)
from .overnight_baseline_methods import interval_losses, paired_intervals

CONTEXT = OUT / "context_prediction_sources.json"


def prepare_context():
    cfg, _ = verify()
    if CONTEXT.exists():
        for entry in json.loads(CONTEXT.read_text())["predictions"]:
            checked(entry)
        return
    paths = {"summer": "results/overnight/forecast_baselines/evaluation_audit.json",
             "autumn": "results/overnight/confirmation/evaluation_audit.json"}
    refs = []
    for period, path in paths.items():
        source = json.loads((CASE / path).read_text())
        for horizon in cfg["horizons"]:
            match = [r for r in source["predictions"] if r["name"] == "catboost_frozen_quantile" and r["horizon"] == horizon
                     and r.get("variant", "raw") == "raw"]
            if len(match) != 1:
                raise ValueError("기존 최근 속도 분위수 참고 예측이 유일하지 않습니다")
            checked(match[0])
            refs.append(dict(period=period, **match[0]))
    write_json(CONTEXT, dict(prepared_at=utcnow(), inputs={path: sha256(CASE / path) for path in paths.values()}, predictions=refs,
        interpretation="입력 접근 조건과 기존 학습 설정이 다른 참고 비교; 월별 파일 모형의 공정한 입력 제거 비교는 아님"))
    print("기존 최근 속도 분위수 참고 예측 4개를 결과 읽기 없이 고정", flush=True)


def committed(path):
    name = str(path.relative_to(CASE.parents[1]))
    content = subprocess.run(["git", "show", "HEAD:" + name], cwd=CASE, capture_output=True, check=True).stdout
    if content != path.read_bytes():
        raise ValueError("평가 전 학습·참고 명세를 먼저 커밋해야 합니다")


def evaluation_rows(frame, cfg, period, horizon):
    start, end = cfg["splits"][period]
    use = frame.link_id.isin(cfg["primary_links"]) & frame.target_start.dt.strftime("%Y-%m-%d").between(start, end)
    use &= frame.origin.ge(pd.Timestamp(cfg["evaluation_origin_not_before"]))
    result = frame[use].copy().sort_values(["link_id", "target_start"]).reset_index(drop=True)
    targets = pd.date_range(start, end + " 23:00", freq="h", tz=cfg["timezone"])
    origins = targets - pd.Timedelta(hours=horizon - 1)
    expected = int((origins >= pd.Timestamp(cfg["evaluation_origin_not_before"])).sum()) * len(cfg["primary_links"])
    if len(result) != expected or result.duplicated(["link_id", "target_start"]).any():
        raise ValueError("월별 모형 평가의 전체 시간 격자·키 오류")
    return result


def slices(frame, primary):
    yield "primary_all_hours", frame
    yield "primary_evening_17_19", frame[frame.target_start.dt.hour.isin([17, 18, 19])]
    for link in primary:
        yield "link_" + link, frame[frame.link_id.eq(link)]
    for month, group in frame.groupby(frame.target_start.dt.strftime("%Y-%m")):
        yield "month_" + month, group


def metrics(frame):
    valid = frame[frame.speed_kmh.notna() & frame[QCOLS].notna().all(axis=1)]
    if not len(valid):
        raise ValueError("평가 가능한 속도·예측 행이 없습니다")
    values = {name: float(loss.mean()) for name, loss in interval_losses(valid).items()}
    return dict(expected_rows=len(frame), observed_target_rows=int(frame.speed_kmh.notna().sum()),
        scored_rows=len(valid), missing_target_rows=int(frame.speed_kmh.isna().sum()),
        missing_prediction_rows=int(frame[QCOLS].isna().any(axis=1).sum()),
        raw_crossing_fraction=float(frame.raw_crossing.mean()), **values)


def context_prediction(base, ref):
    old = pd.read_parquet(checked(ref))
    if len(old) != ref["rows"]:
        raise ValueError("기존 참고 예측 행 수 변경")
    old["link_id"] = old.link_id.astype(str)
    result = base[KEY].merge(old[[*KEY, *QCOLS]], on=KEY[:3], how="left", suffixes=("", "_previous"), validate="one_to_one")
    np.testing.assert_allclose(result.speed_kmh, result.speed_kmh_previous, rtol=0, atol=0, equal_nan=True)
    available = result[QCOLS].notna().all(axis=1)
    if not available.eq(result.speed_kmh.notna()).all():
        raise ValueError("기존 참고 예측과 실제값의 관측 격자 불일치")
    q, crossings = ordered_predictions(result.loc[available, QCOLS].to_numpy())
    result.loc[available, QCOLS] = q
    result["raw_crossing"] = np.nan
    result.loc[available, "raw_crossing"] = crossings.astype(float)
    return result.drop(columns="speed_kmh_previous")


def run():
    cfg, _ = verify()
    feature_audit = load_feature_audit()
    state = json.loads(TRAINING.read_text())
    if (not state["completed"] or state["inputs"]["feature_audit_sha256"] != sha256(OUT / "feature_audit.json")
            or state["inputs"]["training_code_sha256"] != sha256(CASE / "gangnam/deepening_archive_models.py")):
        raise ValueError("학습이 완료되지 않았거나 개발 입력이 변경됐습니다")
    committed(TRAINING)
    committed(CONTEXT)
    context = json.loads(CONTEXT.read_text())
    for path, expected in context["inputs"].items():
        checked(dict(path=path, sha256=expected))
    (RAW / "predictions").mkdir(parents=True, exist_ok=True)
    measurements, comparisons, predictions, importances = [], [], [], []
    for feature in feature_audit["outputs"]:
        horizon = feature["horizon"]
        full = read_features(feature, feature_audit)
        fallback = joblib.load(checked(state["empirical"][str(horizon)]))
        models = [entry for entry in state["entries"] if entry["horizon"] == horizon]
        for entry in models:
            model = joblib.load(checked(entry["model"]))
            values = model["estimator"].get_feature_importance(thread_count=cfg["resources"]["threads"])
            for name, importance in zip(model["estimator"].feature_names_, values, strict=True):
                importances.append(dict(horizon=horizon, name=entry["name"], seed=entry["seed"], feature=name,
                    importance=float(importance), interpretation="model_split_dependence_not_causal_effect"))
        for period in ["summer", "autumn"]:
            frame = evaluation_rows(full, cfg, period, horizon)
            completed = {}
            for entry in models:
                model = joblib.load(checked(entry["model"]))
                with threadpool_limits(limits=cfg["resources"]["threads"]):
                    q, crossing = ordered_predictions(predict_quantiles(model, frame, cfg["resources"]["threads"]))
                output = frame[KEY].copy()
                output[QCOLS], output["raw_crossing"] = q, crossing.astype(float)
                completed[(entry["name"], entry["seed"])] = output
            baseline, fell_back = archive_profile_prediction(fallback, frame, cfg["empirical_baseline"]["minimum_profile_observations"])
            output = frame[KEY].copy()
            output[QCOLS], output["raw_crossing"], output["profile_fallback"] = baseline, 0., fell_back
            completed[("published_three_month_profile", 0)] = output
            refs = [ref for ref in context["predictions"] if ref["period"] == period and ref["horizon"] == horizon]
            if len(refs) != 1:
                raise ValueError("참고 예측 명세 대응 불가")
            completed[("reference_recent_assumption", 0)] = context_prediction(frame, refs[0])
            for (name, seed), output in completed.items():
                path = RAW / "predictions" / f"{period}_h{horizon}_{name}_s{seed}.parquet"
                output.to_parquet(path, index=False)
                predictions.append(dict(period=period, horizon=horizon, name=name, seed=seed,
                    **reference(path), rows=len(output), finite_prediction_rows=int(output[QCOLS].notna().all(axis=1).sum())))
                for scope, group in slices(output, cfg["primary_links"]):
                    measurements.append(dict(period=period, horizon=horizon, name=name, seed=seed, scope=scope, **metrics(group)))
            for seed in cfg["training"]["seeds"]:
                pairs = {
                    "archive_minus_calendar": (completed[("published_archive", seed)], completed[("calendar_only", seed)]),
                    "archive_minus_profile": (completed[("published_archive", seed)], completed[("published_three_month_profile", 0)]),
                    "profile_minus_calendar": (completed[("published_three_month_profile", 0)], completed[("calendar_only", seed)])}
                if set(pairs) != set(cfg["evaluation"]["paired_comparisons"]):
                    raise ValueError("고정된 짝 비교 목록과 다릅니다")
                for comparison, (left, right) in pairs.items():
                    for scope in ["primary_all_hours", "primary_evening_17_19"]:
                        groups = []
                        for data in [left, right]:
                            chosen = data[data.speed_kmh.notna()].copy()
                            if scope.endswith("17_19"):
                                chosen = chosen[chosen.target_start.dt.hour.isin([17, 18, 19])]
                            groups.append(chosen)
                        values = paired_intervals(*groups, draws=cfg["evaluation"]["week_bootstrap_draws"],
                            seed=cfg["evaluation"]["week_bootstrap_seed"])
                        for result in values:
                            if result["metric"] not in cfg["evaluation"]["metrics"]:
                                continue
                            quality = result["weeks"] >= cfg["evaluation"]["minimum_weeks_for_interval"]
                            comparisons.append(dict(period=period, horizon=horizon, seed=seed, comparison=comparison,
                                scope=scope, quality_pass=quality, **result))
            print(f"월별 파일 평가: {period} h{horizon} {len(frame):,}개 링크·시간, 모형·기준선 6개", flush=True)
        del full
    tables = {"metrics.csv": pd.DataFrame(measurements), "paired_comparisons.csv": pd.DataFrame(comparisons),
              "feature_importance.csv": pd.DataFrame(importances)}
    for name, table in tables.items():
        table.to_csv(OUT / name, index=False, lineterminator="\n")
    write_json(OUT / "evaluation_audit.json", dict(completed_at=utcnow(), input_manifest_sha256=sha256(MANIFEST),
        training_manifest_sha256=sha256(TRAINING), context_sources_sha256=sha256(CONTEXT), code_sha256=sha256(__file__),
        predictions=predictions, outputs={name: sha256(OUT / name) for name in tables},
        interpretation=["already examined 2025 outcomes; exploratory post hoc comparison",
          "only calendar versus archive model with equal seed is a matched new feature comparison",
          "old recent-road reference assumes separate real-time access and uses prior training settings",
          "quantiles sorted before scoring; raw crossings recorded; no interval calibration or coverage guarantee",
          "new models predict all clock rows, including unknown actual targets; metrics exclude unknown targets",
          "two seeds are sensitivity runs, not a search for the best test result",
          "calendar-week paired bootstrap is descriptive and not a causal or multiplicity-corrected interval"] ))
