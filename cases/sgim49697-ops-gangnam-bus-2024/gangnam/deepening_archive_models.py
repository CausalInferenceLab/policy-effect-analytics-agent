"""같은 학습 표본으로 달력·공개 과거 월 분위수 모형을 별도 학습한다."""

import hashlib
import importlib.metadata
import json
import platform
import time
import warnings
from collections import Counter

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from .common import CASE, digest, sha256, utcnow, write_json
from .deepening_archive_data import MANIFEST, OUT, RAW, checked, reference, verify
from .overnight_baseline_methods import empirical_model, empirical_prediction, interval_losses
from .overnight_forecast_models import fit_quantile, transform, uniform_sample

TRAINING = OUT / "training_manifest.json"
KEY = ["link_id", "target_start", "origin", "speed_kmh"]
QCOLS = ["q10", "q50", "q90"]


def predict_quantiles(model, frame, threads):
    return model["estimator"].predict(transform(frame, model["schema"]), thread_count=threads, task_type="CPU")


def read_features(entry, audit):
    if audit["code_sha256"] != sha256(CASE / "gangnam/deepening_archive_features.py"):
        raise ValueError("월별 특징 생성 코드가 변경됐습니다")
    if audit["data_code_sha256"] != sha256(CASE / "gangnam/deepening_archive_data.py"):
        raise ValueError("월별 특징 자료 판독 코드가 변경됐습니다")
    frame = pd.read_parquet(checked(entry))
    if len(frame) != entry["rows"] or frame.duplicated(["link_id", "target_start"]).any():
        raise ValueError("월별 특징 행 수·키 중복 오류")
    if frame.target_start.dt.year.ge(2026).any() or not frame.target_start.sub(frame.origin).eq(pd.Timedelta(hours=entry["horizon"] - 1)).all():
        raise ValueError("월별 특징 잠금·발행 시계 오류")
    return frame


def development_parts(frame, cfg):
    train = frame[frame.split.eq("train") & frame.speed_kmh.notna()].copy()
    tuning = frame[frame.split.eq("tuning") & frame.link_id.isin(cfg["primary_links"]) & frame.speed_kmh.notna()].copy()
    for name, part in [("train", train), ("tuning", tuning)]:
        start, end = cfg["splits"][name]
        if not len(part) or not part.target_start.dt.strftime("%Y-%m-%d").between(start, end).all():
            raise ValueError("월별 모형 개발 분할·날짜 불일치")
        if not np.isfinite(part.speed_kmh).all():
            raise ValueError("월별 모형 개발 목표의 비유한 값")
    return train, tuning


def sampled_key_hash(train, cfg, seed):
    sample = uniform_sample(train, cfg["training"]["maximum_rows_per_link"], seed)
    values = pd.util.hash_pandas_object(sample[["link_id", "target_start", "speed_kmh"]], index=False).to_numpy()
    return hashlib.sha256(values.tobytes()).hexdigest(), len(sample)


def ordered_predictions(prediction):
    q = np.asarray(prediction)
    if q.ndim != 2 or q.shape[1] != 3 or not np.isfinite(q).all():
        raise ValueError("유한한 세 분위수 예측이 필요합니다")
    crossing = (np.diff(q, axis=1) < 0).any(axis=1)
    return np.sort(q, axis=1), crossing


def archive_profile_prediction(model, frame, minimum):
    result, _ = empirical_prediction(model, frame)
    profile = frame[["archive_profile_3_q10", "archive_profile_3_q50", "archive_profile_3_q90"]].to_numpy()
    valid = frame.archive_profile_3_count.ge(minimum).to_numpy() & np.isfinite(profile).all(axis=1)
    result[valid] = profile[valid]
    return ordered_predictions(result)[0], ~valid


def load_feature_audit():
    path = OUT / "feature_audit.json"
    audit = json.loads(path.read_text())
    if audit["input_manifest_sha256"] != sha256(MANIFEST):
        raise ValueError("월별 모형 특징의 고정 입력 변경")
    return audit


def run():
    cfg, manifest = verify()
    audit = load_feature_audit()
    state_inputs = {"input_manifest_sha256": sha256(MANIFEST), "feature_audit_sha256": sha256(OUT / "feature_audit.json"),
                    "training_code_sha256": sha256(__file__)}
    if TRAINING.exists():
        state = json.loads(TRAINING.read_text())
        if state["inputs"] != state_inputs:
            raise ValueError("중단 후 재개할 학습의 입력·코드가 달라졌습니다")
        for entry in state["entries"]:
            checked(entry["model"])
        for entry in state.get("empirical", {}).values():
            checked(entry)
        if state["completed"]:
            if len(state["entries"]) != manifest["planned_fits"] or len(state.get("empirical", {})) != len(cfg["horizons"]):
                raise ValueError("완료된 학습 명세의 모형 수 불일치")
            print("이미 완료된 월별 모형·명세 해시를 확인했습니다. 덮어쓰지 않습니다.", flush=True)
            return
    else:
        state = dict(started_at=utcnow(), inputs=state_inputs, configuration=cfg, entries=[], completed=False,
            environment={"python": platform.python_version(), "platform": platform.platform(),
                **{name: importlib.metadata.version(name) for name in ["catboost", "pandas", "numpy", "pyarrow", "joblib", "threadpoolctl"]}},
            interpretation="훈련·튜닝 분할만으로 별도 모형 추정; 평가 결과로 선택하지 않음")
    (RAW / "models").mkdir(parents=True, exist_ok=True)
    for feature in audit["outputs"]:
        horizon = feature["horizon"]
        frame = read_features(feature, audit)
        train, tuning = development_parts(frame, cfg)
        if len(train.link_id.unique()) != manifest["selected_links"]:
            raise ValueError("훈련 링크 수가 기존 고정 선택과 다릅니다")
        for seed in cfg["training"]["seeds"]:
            sample_hash, sample_rows = sampled_key_hash(train, cfg, seed)
            for name in cfg["feature_sets"]:
                previous = [e for e in state["entries"] if (e["horizon"], e["seed"], e["name"]) == (horizon, seed, name)]
                if previous:
                    if len(previous) != 1 or previous[0]["sample_key_sha256"] != sample_hash:
                        raise ValueError("기존 실행과 다른 학습 표본")
                    continue
                print(f"월별 파일 모형 학습 시작: h{horizon} {name} seed{seed} {sample_rows:,}행", flush=True)
                start = time.monotonic()
                with warnings.catch_warnings(record=True) as caught, threadpool_limits(limits=cfg["resources"]["threads"]):
                    warnings.simplefilter("always")
                    model = fit_quantile(cfg["models"]["catboost_quantile"]["depth"], train, tuning,
                        feature["feature_sets"][name], cfg, seed)
                    prediction, crossings = ordered_predictions(predict_quantiles(model, tuning, cfg["resources"]["threads"]))
                if model["training_rows"] != sample_rows:
                    raise ValueError("실제 학습 표본 수 불일치")
                path = RAW / "models" / f"h{horizon}_{name}_s{seed}.joblib"
                if path.exists():
                    raise ValueError("명세에 없는 같은 이름의 모델을 덮어쓸 수 없습니다")
                joblib.dump(model, path)
                tuning_frame = tuning[KEY].copy()
                tuning_frame[QCOLS] = prediction
                loss = interval_losses(tuning_frame)
                entry = dict(name=name, horizon=horizon, seed=seed, model=reference(path),
                    feature_sha256=feature["sha256"], training_rows=model["training_rows"], tuning_rows=len(tuning),
                    training_links=train.link_id.nunique(), sample_key_sha256=sample_hash, iterations=model["iterations"],
                    feature_columns=feature["feature_sets"][name], transformed_features=model["estimator"].feature_names_,
                    all_missing_training_columns=model["schema"]["all_missing_training_columns"],
                    tuning_metrics={key: float(value.mean()) for key, value in loss.items()},
                    tuning_raw_crossing_fraction=float(crossings.mean()), elapsed_seconds=time.monotonic() - start,
                    warnings=[dict(message=message, count=count) for message, count in Counter(str(w.message) for w in caught).items()],
                    signature=digest(dict(name=name, horizon=horizon, seed=seed, feature=feature["sha256"], configuration=cfg)))
                state["entries"].append(entry)
                write_json(TRAINING, state)
                print(f"학습 완료: h{horizon} {name} seed{seed} {model['iterations']}개 트리·{entry['elapsed_seconds']:.1f}초", flush=True)
        fallback_path = RAW / "models" / f"h{horizon}_empirical_fallback.joblib"
        saved = state.get("empirical", {}).get(str(horizon))
        if saved:
            checked(saved)
        else:
            if fallback_path.exists():
                raise ValueError("명세에 없는 경험 기준선을 덮어쓸 수 없습니다")
            model = empirical_model(train, cfg["empirical_baseline"]["minimum_training_group_rows"])
            joblib.dump(model, fallback_path)
            state.setdefault("empirical", {})[str(horizon)] = dict(**reference(fallback_path), training_rows=len(train))
            write_json(TRAINING, state)
        del frame, train, tuning
    if len(state["entries"]) != manifest["planned_fits"]:
        raise ValueError("계획한 학습 수가 완료되지 않았습니다")
    state["completed"], state["completed_at"] = True, utcnow()
    write_json(TRAINING, state)
    print("월별 파일 모형 8개와 경험 기준선 준비 완료. 평가 전에 학습 명세를 커밋합니다.", flush=True)
