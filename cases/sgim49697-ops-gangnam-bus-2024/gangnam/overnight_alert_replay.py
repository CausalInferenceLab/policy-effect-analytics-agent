"""고정 확률을 예측 원점 순서로 처리해 경보 상한·대기·연속 확인의 손실을 평가한다."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json

OUT = CASE / "results/overnight/alert_replay"
RAW = CASE / "data/overnight/alert_replay"


def replay(frame, threshold, policy):
    """미래 원점의 확률이나 실제값을 읽지 않고 현재 알려진 후보만 발행한다."""
    required = {"link_id", "origin", "probability"}
    if not required.issubset(frame) or frame.empty or frame.duplicated(["link_id", "origin"]).any():
        raise ValueError("경보 입력의 필수 열·표본·중복 키 오류")
    if frame.link_id.isna().any() or frame.origin.isna().any() or str(frame.origin.dt.tz) != "Asia/Seoul":
        raise ValueError("경보 원점은 유효한 Asia/Seoul 시각이고 링크는 비어 있지 않아야 합니다")
    scores = frame.probability.dropna()
    if not np.isfinite(scores).all() or not scores.between(0, 1).all() or not np.isfinite(threshold) or threshold < 0:
        raise ValueError("경보 확률 또는 임계값 오류")
    cooldown, cap, confirmation = [policy[k] for k in ["cooldown_hours", "daily_cap", "consecutive_hours"]]
    if not isinstance(cooldown, int) or cooldown < 0 or not isinstance(confirmation, int) or confirmation < 1:
        raise ValueError("경보 대기·연속 확인은 유효한 정수여야 합니다")
    if cap is not None and (not isinstance(cap, int) or cap < 1):
        raise ValueError("경보 일별 상한은 양의 정수 또는 미지정이어야 합니다")
    ordered = frame.sort_values(["origin", "probability", "link_id"], ascending=[True, False, True],
                                na_position="last", kind="stable").reset_index(drop=True)
    last_seen, streak, last_issued, daily_count = {}, {}, {}, {}
    issued, reasons, runs = [], [], []
    hour = pd.Timedelta(1, unit="h")
    for row in ordered[["link_id", "origin", "probability"]].itertuples(index=False):
        link, origin, probability = row
        candidate = pd.notna(probability) and probability >= threshold
        continuous = link in last_seen and origin - last_seen[link] == hour
        streak[link] = (streak.get(link, 0) + 1 if continuous else 1) if candidate else 0
        last_seen[link] = origin
        date = origin.date()
        if pd.isna(probability):
            reason = "missing_score"
        elif not candidate:
            reason = "below_threshold"
        elif streak[link] < confirmation:
            reason = "confirmation"
        elif link in last_issued and origin - last_issued[link] < cooldown * hour:
            reason = "cooldown"
        elif cap is not None and daily_count.get(date, 0) >= cap:
            reason = "daily_cap"
        else:
            reason = "issued"
            last_issued[link] = origin
            daily_count[date] = daily_count.get(date, 0) + 1
        issued.append(reason == "issued")
        reasons.append(reason)
        runs.append(streak[link])
    return ordered.assign(issued=issued, reason=reasons, consecutive_exceedances=runs)


def episodes(frame):
    """실제 양성의 연속 한 시간 묶음에서 한 번 이상 발행했는지 집계한다."""
    if frame.duplicated(["link_id", "target_start"]).any():
        raise ValueError("경보 평가 목표 시각·링크가 중복됩니다")
    part = frame[frame.label.eq(1)].sort_values(["link_id", "target_start"]).copy()
    if part.empty:
        return pd.DataFrame(columns=["link_id", "start", "last_start", "observed_hours", "issued_hours", "hit"])
    new = part.link_id.ne(part.link_id.shift()) | part.target_start.diff().ne(pd.Timedelta(1, unit="h"))
    part["episode"] = new.cumsum()
    result = part.groupby("episode").agg(link_id=("link_id", "first"), start=("target_start", "min"),
        last_start=("target_start", "max"), observed_hours=("label", "size"), issued_hours=("issued", "sum")).reset_index(drop=True)
    return result.assign(hit=result.issued_hours.gt(0))


def metrics(frame):
    known = frame[frame.label.notna()]
    if not known.label.isin([0, 1]).all():
        raise ValueError("경보 평가 라벨은 0·1·결측만 허용합니다")
    true = int((known.issued & known.label.eq(1)).sum())
    false = int((known.issued & known.label.eq(0)).sum())
    positives, negatives = int(known.label.eq(1).sum()), int(known.label.eq(0).sum())
    event = episodes(frame)
    counts = frame.groupby(frame.origin.dt.date).issued.sum()
    return {"rows": len(frame), "known_outcomes": len(known), "unknown_outcomes": len(frame) - len(known),
            "positives": positives, "alerts": int(frame.issued.sum()), "true_alerts": true, "false_alerts": false,
            "unknown_alerts": int((frame.issued & frame.label.isna()).sum()),
            "precision_known": true / (true + false) if true + false else np.nan,
            "recall": true / positives if positives else np.nan,
            "false_positive_rate": false / negatives if negatives else np.nan,
            "episodes": len(event), "episodes_hit": int(event.hit.sum()),
            "episode_recall": event.hit.mean() if len(event) else np.nan,
            "target_calendar_days": frame.target_start.dt.date.nunique(),
            "origin_calendar_days": frame.origin.dt.date.nunique(),
            "maximum_alerts_per_origin_day_in_target_window": int(counts.max()) if len(counts) else 0}


def run():
    from threadpoolctl import threadpool_limits

    from .overnight_baseline_runner import KEY_FIELDS, load_model, read_features
    from .overnight_forecast_data import allowed_months
    from .overnight_forecast_diagnostics import align_predictions
    from .overnight_forecast_models import calibrated_probability, raw_score

    cfg = read_yaml("overnight_alert_replay_config.yaml")
    base = read_yaml(cfg["base_config"])
    if cfg["locked_year"] != 2026 or cfg["horizons"] != base["horizons"] or cfg["warmup"] != base["splits"]["decision"]:
        raise ValueError("경보 모의의 잠금·간격·준비 기간 오류")
    allowed_months("test", base)
    selection = json.loads((CASE / cfg["selection"]).read_text())
    original = json.loads((CASE / cfg["original_evaluation"]).read_text())
    names = [p["name"] for p in cfg["policies"]]
    if len(names) != len(set(names)) or "original" not in names:
        raise ValueError("경보 정책 이름은 고유하고 원래 규칙을 포함해야 합니다")
    inputs = {p: sha256(CASE / p) for p in ["overnight_alert_replay_config.yaml", cfg["base_config"], cfg["selection"],
              cfg["original_evaluation"], "gangnam/overnight_forecast_models.py", "gangnam/overnight_baseline_runner.py",
              "gangnam/overnight_forecast_diagnostics.py"]}
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    summaries, daily, hourly, reasons, event_rows, predictions, checks = [], [], [], [], [], [], []
    for horizon in cfg["horizons"]:
        pieces = []
        for scope in ["development", "test"]:
            frame, _, refs = read_features(scope, horizon, base)
            inputs.update(refs)
            part = frame[frame.link_id.isin(base["primary_links"])]
            if scope == "development":
                part = part[part.split.eq("decision")]
            pieces.append(part.copy())
            del frame
        features = pd.concat(pieces, ignore_index=True)
        for label in cfg["labels"]:
            choices = [x for x in selection if x["horizon"] == horizon and x["label"] == label
                       and x["role"] == cfg["roles"][label] and x["family"] == cfg["family"]
                       and x["feature_set"] == cfg["feature_set"] and x["seed"] == cfg["seed"]]
            if len(choices) != 1:
                raise ValueError("고정 경보 모델 선택이 유일하지 않습니다")
            entry = choices[0]
            model = load_model(entry)
            inputs[entry["model_path"]] = entry["model_sha256"]
            output = features[KEY_FIELDS + ["split"]].copy()
            output["label"] = features[label].to_numpy()
            if not output.label.isna().equals(output.speed_kmh.isna()):
                raise ValueError("실제 속도·라벨 결측이 일치하지 않습니다")
            with threadpool_limits(limits=2):
                output["probability"] = calibrated_probability(raw_score(model, features), entry["calibrator"])
            ref = next(x for x in original["predictions"] if x["candidate"] == entry["candidate"])
            path = CASE / ref["path"]
            if not path.resolve().is_relative_to((CASE / "data").resolve()) or sha256(path) != ref["sha256"]:
                raise ValueError("원래 예측 파일 경로·해시 오류")
            inputs[ref["path"]] = ref["sha256"]
            old = pd.read_parquet(path)
            old = old[old.link_id.isin(base["primary_links"])]
            valid = output[output.split.eq("test") & output.label.notna()]
            aligned = align_predictions(valid, old)
            if len(aligned) != 8820 or not np.allclose(aligned.probability_left, aligned.probability_right, rtol=0, atol=1e-12):
                raise ValueError("원래 핵심 시험 확률·유효 표본을 재현하지 못했습니다")
            threshold = entry["decision"]["threshold"]
            tags = {"horizon": horizon, "label": label, "candidate": entry["candidate"], "threshold": threshold}
            for policy in cfg["policies"]:
                full = replay(output, threshold, policy)
                test = full[full.split.eq("test")].copy()
                if len(test) != 8856 or test.label.isna().sum() != 36:
                    raise ValueError("경보의 전체 시험·미관측 실제값 표본이 달라졌습니다")
                counts = full.groupby(full.origin.dt.date).issued.sum()
                if policy["daily_cap"] is not None and counts.max() > policy["daily_cap"]:
                    raise ValueError("준비·시험 전체 원점 날짜에 경보 상한 위반")
                if policy["name"] == "original":
                    comparison = align_predictions(test[test.label.notna()], old)
                    if not np.array_equal(comparison.issued, comparison.alert):
                        raise ValueError("제한 없는 순차 정책이 원래 경보와 다릅니다")
                context = {**tags, "policy": policy["name"]}
                groups = [("all_hours", test), ("evening_17_19", test[test.target_start.dt.hour.isin([17, 18, 19])])]
                groups.extend(("month_" + month, piece) for month, piece in test.groupby(test.target_start.dt.strftime("%Y-%m")))
                summaries.extend({**context, "slice": name, **metrics(piece)} for name, piece in groups)
                for origin_date, piece in test.groupby(test.origin.dt.strftime("%Y-%m-%d")):
                    daily.append({**context, "origin_date": origin_date, **metrics(piece)})
                for hour, piece in test.groupby(test.target_start.dt.hour):
                    hourly.append({**context, "target_hour": hour, **metrics(piece)})
                for reason, piece in test.groupby("reason"):
                    reasons.append({**context, "reason": reason, "rows": len(piece), "positives": int(piece.label.eq(1).sum()),
                                    "unknown_outcomes": int(piece.label.isna().sum())})
                event_rows.extend(episodes(test).assign(**context).to_dict("records"))
                saved = RAW / f"h{horizon}_{label}_{policy['name']}.parquet"
                full.to_parquet(saved, index=False)
                predictions.append({**context, "path": str(saved.relative_to(CASE)), "sha256": sha256(saved),
                                    "rows": len(full), "test_rows": len(test)})
                checks.append({**context, "maximum_full_origin_day_alerts": int(counts.max()), "daily_cap": policy["daily_cap"],
                               "original_known_probabilities_reproduced": len(aligned)})
            print(f"순차 경보 모의: h{horizon} {label}, 고정 표본 8,820 + 미관측 36, 정책 {len(cfg['policies'])}개", flush=True)
    tables = {"metrics": summaries, "daily": daily, "hourly": hourly, "suppression_reasons": reasons, "episodes": event_rows}
    for name, rows in tables.items():
        pd.DataFrame(rows).to_csv(OUT / (name + ".csv"), index=False)
    write_json(OUT / "audit.json", {"completed_at": utcnow(), "configuration": cfg, "code_sha256": sha256(Path(__file__)),
               "inputs": inputs, "checks": checks, "predictions": predictions,
               "outputs": {name + ".csv": sha256(OUT / (name + ".csv")) for name in tables}, "interpretation": cfg["interpretation"]})
