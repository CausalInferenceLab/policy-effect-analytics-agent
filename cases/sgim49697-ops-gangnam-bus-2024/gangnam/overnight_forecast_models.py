"""학습기 대체값·계절 기준선·분류·분위수 모델과 분리된 확률 보정을 구현한다."""

from __future__ import annotations

import numpy as np
import pandas as pd

CATEGORICAL = ["link_id", "hour", "weekday", "month"]


def fit_schema(train, columns):
    categorical = [c for c in CATEGORICAL if c in columns]
    numeric = [c for c in columns if c not in categorical]
    medians = train[numeric].median()
    # 학습기 전체 결측 열은 상수 0과 결측 표시를 함께 사용하고 예외를 기록한다.
    return {"columns": columns, "categorical": categorical, "numeric": numeric,
            "medians": medians.fillna(0.).to_dict(), "all_missing_training_columns": medians[medians.isna()].index.tolist()}


def transform(frame, schema):
    result = frame[schema["columns"]].copy()
    for column in schema["categorical"]:
        if result[column].isna().any():
            raise ValueError("달력·링크 범주에 결측이 있습니다")
        result[column] = result[column].astype(str)
    for column in schema["numeric"]:
        result[column + "__missing"] = result[column].isna().astype("int8")
        result[column] = result[column].fillna(schema["medians"][column]).astype("float64")
    if not np.isfinite(result.select_dtypes("number").to_numpy()).all():
        raise ValueError("학습 특징에 유한하지 않은 값이 있습니다")
    return result


def uniform_sample(train, maximum, seed):
    rng = np.random.default_rng(seed)
    positions = []
    for _, part in train.groupby("link_id", sort=True, observed=True):
        positions.extend(rng.choice(part.index.to_numpy(), size=min(maximum, len(part)), replace=False))
    return train.loc[sorted(positions)].copy()


def fit_seasonal(train, label, smoothing):
    groups = ["link_id", "weekday", "hour"]
    stats = train.groupby(groups, observed=True)[label].agg(["sum", "count"])
    prior = train.groupby("link_id", observed=True)[label].mean()
    stats["probability"] = (stats["sum"] + smoothing * stats.index.get_level_values("link_id").map(prior)) / (stats["count"] + smoothing)
    return {"family": "seasonal", "groups": groups, "probabilities": stats.probability,
            "link_prior": prior, "global_prior": float(train[label].mean()), "label": label}


def seasonal_probability(model, frame):
    index = pd.MultiIndex.from_frame(frame[model["groups"]])
    probability = model["probabilities"].reindex(index).to_numpy()
    fallback = frame.link_id.map(model["link_prior"]).fillna(model["global_prior"]).to_numpy()
    return np.where(np.isfinite(probability), probability, fallback)


def fit_classifier(family, parameter, train, tuning, columns, cfg, seed, label="label_10"):
    from catboost import CatBoostClassifier
    from sklearn.compose import ColumnTransformer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    schema = fit_schema(train, columns)
    sample = uniform_sample(train, cfg["training"]["maximum_rows_per_link"], seed)
    x = transform(sample, schema)
    if family == "logistic":
        numeric = [c for c in x if c not in schema["categorical"]]
        preparation = ColumnTransformer([
            ("categories", OneHotEncoder(handle_unknown="ignore", sparse_output=True), schema["categorical"]),
            ("numeric", StandardScaler(), numeric)], sparse_threshold=1.)
        estimator = Pipeline([("preparation", preparation), ("classifier", LogisticRegression(
            C=parameter, max_iter=cfg["models"]["logistic"]["max_iter"], solver="lbfgs", random_state=seed))])
        estimator.fit(x, sample[label].astype(int))
        iterations = int(estimator.named_steps["classifier"].n_iter_[0])
    elif family == "catboost":
        options = cfg["models"]["catboost_classifier"]
        estimator = CatBoostClassifier(depth=parameter, iterations=options["iterations"],
            learning_rate=options["learning_rate"], loss_function=options["loss_function"],
            random_seed=seed, task_type="CPU", thread_count=options["thread_count"],
            cat_features=schema["categorical"], allow_writing_files=False, verbose=False)
        estimator.fit(x, sample[label].astype(int), eval_set=(transform(tuning, schema), tuning[label].astype(int)),
            early_stopping_rounds=options["early_stopping_rounds"], use_best_model=True)
        iterations = int(estimator.tree_count_)
    else:
        raise ValueError(f"알 수 없는 분류 모델: {family}")
    return {"family": family, "estimator": estimator, "schema": schema, "parameter": parameter,
            "iterations": iterations, "training_rows": len(sample), "seed": seed, "label": label}


def raw_score(model, frame):
    if model["family"] == "seasonal":
        p = np.clip(seasonal_probability(model, frame), 1e-7, 1 - 1e-7)
        return np.log(p / (1 - p))
    x = transform(frame, model["schema"])
    if model["family"] == "logistic":
        return model["estimator"].decision_function(x)
    return model["estimator"].predict(x, prediction_type="RawFormulaVal")


def fit_calibrator(raw, labels):
    from sklearn.linear_model import LogisticRegression

    if len(np.unique(labels)) != 2:
        raise ValueError("확률 보정 기간에 양성과 음성이 모두 필요합니다")
    model = LogisticRegression(C=1e6, max_iter=1000, solver="lbfgs")
    model.fit(np.asarray(raw).reshape(-1, 1), np.asarray(labels).astype(int))
    return {"intercept": float(model.intercept_[0]), "slope": float(model.coef_[0, 0]),
            "rows": len(labels), "prevalence": float(np.mean(labels)), "C": 1e6}


def calibrated_probability(raw, calibrator=None):
    from scipy.special import expit

    raw = np.asarray(raw)
    return expit(raw if calibrator is None else calibrator["intercept"] + calibrator["slope"] * raw)


def choose_threshold(labels, probability, maximum_fpr):
    from sklearn.metrics import roc_curve

    if len(np.unique(labels)) != 2:
        raise ValueError("경보 기준 선택 기간에 양성과 음성이 모두 필요합니다")
    fpr, recall, thresholds = roc_curve(labels, probability, drop_intermediate=False)
    valid = np.flatnonzero(fpr <= maximum_fpr + 1e-12)
    maximum_recall = recall[valid].max()
    chosen = valid[np.isclose(recall[valid], maximum_recall, rtol=0, atol=1e-12)]
    index = chosen[np.argmax(thresholds[chosen])]
    threshold = thresholds[index]
    if np.isinf(threshold):
        threshold = np.nextafter(1., np.inf)
    return {"threshold": float(threshold), "decision_fpr": float(fpr[index]), "decision_recall": float(recall[index]),
            "decision_rows": len(labels), "decision_prevalence": float(np.mean(labels))}


def fit_quantile(depth, train, tuning, columns, cfg, seed):
    from catboost import CatBoostRegressor

    options = cfg["models"]["catboost_quantile"]
    schema = fit_schema(train, columns)
    sample = uniform_sample(train, cfg["training"]["maximum_rows_per_link"], seed)
    loss = "MultiQuantile:alpha=" + ",".join(str(q) for q in options["quantiles"])
    estimator = CatBoostRegressor(depth=depth, iterations=options["iterations"], learning_rate=options["learning_rate"],
        loss_function=loss, random_seed=seed, task_type="CPU", thread_count=options["thread_count"],
        cat_features=schema["categorical"], allow_writing_files=False, verbose=False)
    estimator.fit(transform(sample, schema), sample.speed_kmh, eval_set=(transform(tuning, schema), tuning.speed_kmh),
                  early_stopping_rounds=options["early_stopping_rounds"], use_best_model=True)
    return {"family": "quantile", "estimator": estimator, "schema": schema, "parameter": depth,
            "iterations": int(estimator.tree_count_), "training_rows": len(sample), "seed": seed,
            "quantiles": options["quantiles"]}


def quantile_prediction(model, frame):
    return model["estimator"].predict(transform(frame, model["schema"]))


def probability_metrics(labels, probability):
    from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score

    if not np.isfinite(probability).all() or np.any((probability < 0) | (probability > 1)):
        raise ValueError("확률이 [0,1] 범위를 벗어났습니다")
    both = len(np.unique(labels)) == 2
    return {"rows": len(labels), "positives": int(np.sum(labels)), "prevalence": float(np.mean(labels)),
        "average_precision": float(average_precision_score(labels, probability)) if np.sum(labels) else None,
        "brier": float(brier_score_loss(labels, probability)), "log_loss": float(log_loss(labels, probability, labels=[0, 1])),
        "roc_auc": float(roc_auc_score(labels, probability)) if both else None}


def quantile_metrics(target, prediction, quantiles):
    from sklearn.metrics import mean_pinball_loss

    return {"rows": len(target), "mean_pinball": float(np.mean([mean_pinball_loss(target, prediction[:, i], alpha=q)
                for i, q in enumerate(quantiles)])),
            "coverage": float(np.mean((target >= prediction[:, 0]) & (target <= prediction[:, -1]))),
            "width": float(np.mean(prediction[:, -1] - prediction[:, 0])),
            "crossing_fraction": float(np.mean((np.diff(prediction, axis=1) < 0).any(axis=1)))}
