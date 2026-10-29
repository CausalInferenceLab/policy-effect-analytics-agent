"""고정된 예측·임계값의 연속 저속 구간과 실제 발행 시점 경보를 평가한다."""

import json
import subprocess

import numpy as np
import pandas as pd

from .common import CASE, read_yaml, sha256, utcnow, write_json

CONFIG = "deepening_episode_config.yaml"
OUT = CASE / "results/deepening/episodes"
RAW = CASE / "data/deepening/episodes"
MANIFEST = OUT / "input_manifest.json"
SELECTION = "results/overnight/confirmation/selection_manifest.json"
SOURCE_AUDITS = {"relative_probability": "relative_ablation", "conditional_probability": "conditional_low",
                 "conditional_margin": "conditional_margin"}
KEY = ["link_id", "target_start"]


def check_config(cfg):
    if cfg["horizons"] != [1, 3] or cfg["period_end"] != "exclusive" or cfg["timezone"] != "Asia/Seoul":
        raise ValueError("경보 평가의 시계·간격 설정이 다릅니다")
    for start, end in cfg["periods"].values():
        first, last = pd.Timestamp(start), pd.Timestamp(end) - pd.Timedelta(hours=1)
        if first > last or first.year < 2025 or last.year >= cfg["locked_year"]:
            raise ValueError("잠금 연도 또는 범위 밖의 경보 평가")
    if cfg["cooldown_hours"] != [0, 3] or cfg["minimum_observed_episode_hours"] != [1, 2]:
        raise ValueError("고정한 재알림·최소 길이 규칙이 다릅니다")


def read_json(path):
    return json.loads((CASE / path).read_text())


def verify_path(ref):
    path = (CASE / ref["path"]).resolve()
    if not path.is_relative_to(CASE.resolve()) or sha256(path) != ref["sha256"]:
        raise ValueError("동결 경보 입력 경로·해시 불일치")
    return path


def prepare():
    """결과값을 읽지 않고 기존 동결과 예측 파일 참조를 복사한다."""
    from .overnight_confirmation_data import verify as verify_previous

    cfg = read_yaml(CONFIG)
    check_config(cfg)
    verify_previous()
    if MANIFEST.exists():
        verify(committed=False)
        return
    selected = read_json(SELECTION)
    paths = [CONFIG, SELECTION, "results/overnight/confirmation/evaluation_audit.json"]
    audits = {}
    for task, directory in SOURCE_AUDITS.items():
        path = f"results/overnight/{directory}/evaluation_audit.json"
        paths.append(path)
        audits[task] = read_json(path)
    confirmation = read_json(paths[2])
    entries = []
    for task, names in cfg["candidates"].items():
        for name in names:
            for horizon in cfg["horizons"]:
                source = [row for row in selected["entries"] if row["confirmation_task"] == task
                          and row["name"] == name and row["horizon"] == horizon]
                if len(source) != 1:
                    raise ValueError("기존 동결 후보가 유일하지 않습니다")
                refs = {}
                for period, candidates in [("summer", audits[task]["predictions"]), ("autumn", confirmation["predictions"])]:
                    match = [row for row in candidates if row["name"] == name and row["horizon"] == horizon
                             and row.get("task", task) == task]
                    if len(match) != 1:
                        raise ValueError("예측 파일 참조가 유일하지 않습니다")
                    verify_path(match[0])
                    refs[period] = {key: match[0][key] for key in ["path", "sha256", "rows"]}
                entries.append(dict(task=task, name=name, horizon=horizon,
                    rules={rule: source[0][rule] for rule in cfg["rules"]}, predictions=refs))
    OUT.mkdir(parents=True, exist_ok=True)
    write_json(MANIFEST, dict(prepared_at=utcnow(), configuration=cfg, entries=entries,
        inputs={path: sha256(CASE / path) for path in paths},
        interpretation="이미 열람한 2025년 예측의 후속 기술 평가; 모형·확률·임계값 변경 없음"))
    print(f"후속 경보 입력 {len(entries)}개 후보·{sum(len(e['predictions']) for e in entries)}개 파일 고정", flush=True)


def verify(committed=True):
    cfg = read_yaml(CONFIG)
    check_config(cfg)
    record = json.loads(MANIFEST.read_text())
    if cfg != record["configuration"]:
        raise ValueError("경보 평가 설정이 고정 이후 변경됐습니다")
    for path, expected in record["inputs"].items():
        verify_path(dict(path=path, sha256=expected))
    for entry in record["entries"]:
        for ref in entry["predictions"].values():
            verify_path(ref)
    if committed:
        path = str(MANIFEST.relative_to(CASE.parents[1]))
        content = subprocess.run(["git", "show", "HEAD:" + path], cwd=CASE, check=True, capture_output=True).stdout
        if content != MANIFEST.read_bytes():
            raise ValueError("후속 경보 규칙·입력 명세를 먼저 커밋해야 합니다")
    return cfg, record


def complete_panel(frame, links, start, end, horizon, timezone="Asia/Seoul"):
    """관측되지 않은 시각을 0 또는 예측값으로 대체하지 않는다."""
    columns = ["link_id", "target_start", "origin", "speed_kmh", "label", "probability"]
    if not set(columns).issubset(frame.columns) or set(frame.columns) - set(columns) - {"raw_probability"}:
        raise ValueError("경보 예측 열이 예상과 다릅니다")
    data = frame[columns].copy()
    data["link_id"] = data.link_id.astype(str)
    for col in ["target_start", "origin"]:
        if str(data[col].dt.tz) != timezone:
            raise ValueError("예측 시각의 시간대 불일치")
        if not data[col].eq(data[col].dt.floor("h")).all():
            raise ValueError("정시가 아닌 예측 시각")
    if data.duplicated(KEY).any() or not data.link_id.isin(links).all():
        raise ValueError("예측 키 중복 또는 범위 밖 링크")
    if not data.label.isin([0, 1]).all() or not np.isfinite(data[["probability", "speed_kmh"]]).all().all():
        raise ValueError("잘못된 정답·확률·속도")
    if not data.probability.between(0, 1).all():
        raise ValueError("확률 범위 오류")
    if not data.target_start.sub(data.origin).eq(pd.Timedelta(hours=horizon - 1)).all():
        raise ValueError("발행 시각과 예측 대상 시각의 차이 불일치")
    grid = pd.date_range(start, end, inclusive="left", freq="h", tz=timezone)
    index = pd.MultiIndex.from_product([links, grid], names=KEY)
    data = data.set_index(KEY)
    if not data.index.isin(index).all():
        raise ValueError("평가 기간 밖의 예측")
    data = data.reindex(index).reset_index()
    data["saved_prediction"] = data.probability.notna()
    data["origin"] = data.target_start - pd.Timedelta(hours=horizon - 1)
    return data


def identify_episodes(panel, prefix):
    """양수 연속 시간의 시작·끝과 양쪽 검열 상태를 기록한다."""
    catalog, assignment = [], pd.Series(pd.NA, index=panel.index, dtype="string")
    for link, group in panel.groupby("link_id", sort=True):
        group = group.sort_values("target_start")
        if len(group) > 1 and not group.target_start.diff().iloc[1:].eq(pd.Timedelta(hours=1)).all():
            raise ValueError("연속 구간 판독에는 공백을 명시한 전체 시간 격자가 필요합니다")
        labels = group.label.to_numpy(dtype=float)
        pos = 0
        while pos < len(group):
            if labels[pos] != 1:
                pos += 1
                continue
            begin = pos
            while pos + 1 < len(group) and labels[pos + 1] == 1:
                pos += 1
            finish = pos
            start = group.iloc[begin].target_start
            episode_id = f"{prefix}:{link}:{start.strftime('%Y%m%d%H')}"
            left = begin == 0 or np.isnan(labels[begin - 1])
            right = finish == len(group) - 1 or np.isnan(labels[finish + 1])
            catalog.append(dict(episode_id=episode_id, link_id=link, start=start,
                last_positive=group.iloc[finish].target_start, observed_hours=finish - begin + 1,
                left_censored=left, right_censored=right, known_onset=not left))
            assignment.loc[group.index[begin:finish + 1]] = episode_id
            pos += 1
    columns = ["episode_id", "link_id", "start", "last_positive", "observed_hours", "left_censored", "right_censored", "known_onset"]
    result = pd.DataFrame(catalog, columns=columns)
    for col in ["start", "last_positive"]:
        result[col] = pd.to_datetime(result[col], utc=True).dt.tz_convert(panel.target_start.dt.tz)
    for col in ["left_censored", "right_censored", "known_onset"]:
        result[col] = result[col].astype(bool)
    result["observed_hours"] = result.observed_hours.astype(int)
    return result, assignment


def notification_mask(panel, threshold, cooldown_hours):
    """정답 열을 참조하지 않고 저장된 확률·발행 시계만으로 알림을 결정한다."""
    if not np.isfinite(threshold) or cooldown_hours < 0:
        raise ValueError("잘못된 경보 임계값·대기 시간")
    result = pd.Series(False, index=panel.index)
    for _, group in panel.groupby("link_id", sort=True):
        last = None
        for row in group.sort_values("origin").itertuples():
            if pd.isna(row.probability) or row.probability < threshold:
                continue
            if last is None or row.origin - last >= pd.Timedelta(hours=cooldown_hours):
                result.at[row.Index] = True
                last = row.origin
    return result


def assess(panel, catalog, threshold, cooldown_hours, minimum_hours, calendar_days):
    emitted = notification_mask(panel, threshold, cooldown_hours)
    alerts = panel.loc[emitted, [*KEY, "origin", "label", "probability", "episode_id"]].copy()
    alerts = alerts.merge(catalog[["episode_id", "start", "known_onset"]], on="episode_id", how="left", validate="many_to_one")
    alerts["class"] = "false_point_alert"
    positive = alerts.label.eq(1)
    unknown = positive & alerts.known_onset.eq(False)
    known = positive & alerts.known_onset.eq(True)
    alerts.loc[unknown, "class"] = "positive_unknown_onset"
    alerts.loc[known & alerts.origin.lt(alerts.start), "class"] = "advance"
    alerts.loc[known & alerts.origin.eq(alerts.start), "class"] = "at_onset"
    alerts.loc[known & alerts.origin.gt(alerts.start), "class"] = "ongoing"
    alerts["issue_minus_onset_hours"] = (alerts.origin - alerts.start).dt.total_seconds() / 3600
    detection = catalog.copy()
    hits = alerts[positive].groupby("episode_id").agg(first_issue=("origin", "min"), positive_alerts=("origin", "size"))
    detection = detection.merge(hits, on="episode_id", how="left", validate="one_to_one")
    detection["positive_alerts"] = detection.positive_alerts.fillna(0).astype(int)
    detection["hit_any"] = detection.positive_alerts.gt(0)
    detection["hit_by_onset"] = detection.known_onset & detection.first_issue.le(detection.start)
    detection["hit_before_onset"] = detection.known_onset & detection.first_issue.lt(detection.start)
    detection["first_issue_minus_onset_hours"] = (detection.first_issue - detection.start).dt.total_seconds() / 3600
    chosen = detection[detection.observed_hours.ge(minimum_hours)]
    eligible = chosen[chosen.known_onset]
    true_alerts = int(positive.sum())
    positives = int(panel.label.eq(1).sum())

    def rate(a, b):
        return float(a / b) if b else np.nan

    metrics = dict(expected_hours=len(panel), known_hours=int(panel.saved_prediction.sum()),
        missing_hours=int((~panel.saved_prediction).sum()), positive_hours=positives,
        calendar_days=calendar_days, alerts=len(alerts), true_alerts=true_alerts,
        false_alerts=len(alerts) - true_alerts, alerts_per_day=len(alerts) / calendar_days,
        point_precision=rate(true_alerts, len(alerts)), point_recall=rate(true_alerts, positives),
        episodes=len(chosen), known_onset_episodes=len(eligible), left_censored_episodes=int(chosen.left_censored.sum()),
        right_censored_episodes=int(chosen.right_censored.sum()), episodes_hit_any=int(chosen.hit_any.sum()),
        known_episodes_hit_any=int(eligible.hit_any.sum()), episodes_hit_by_onset=int(eligible.hit_by_onset.sum()),
        episodes_hit_before_onset=int(eligible.hit_before_onset.sum()),
        episode_recall_any=rate(chosen.hit_any.sum(), len(chosen)),
        known_episode_recall_any=rate(eligible.hit_any.sum(), len(eligible)),
        onset_recall=rate(eligible.hit_by_onset.sum(), len(eligible)),
        advance_recall=rate(eligible.hit_before_onset.sum(), len(eligible)),
        median_first_issue_minus_onset_hours=float(eligible.loc[eligible.hit_any, "first_issue_minus_onset_hours"].median()),
        duplicate_positive_alerts=int(chosen.positive_alerts.sub(1).clip(lower=0).sum()))
    for label in ["advance", "at_onset", "ongoing", "positive_unknown_onset", "false_point_alert"]:
        metrics["alerts_" + label] = int(alerts["class"].eq(label).sum())
    return metrics, alerts, detection


def run():
    cfg, manifest = verify()
    RAW.mkdir(parents=True, exist_ok=True)
    metrics, catalogs, coverage, artifacts = [], {}, [], []
    target_panels = {}
    for entry in manifest["entries"]:
        family = "relative" if entry["task"] == "relative_probability" else "conditional"
        for period, ref in entry["predictions"].items():
            start, end = cfg["periods"][period]
            frame = pd.read_parquet(verify_path(ref))
            if len(frame) != ref["rows"]:
                raise ValueError("고정 예측 행 수 불일치")
            panel = complete_panel(frame, cfg["primary_links"], start, end, entry["horizon"], cfg["timezone"])
            group_key = (period, family)
            labels = panel[[*KEY, "speed_kmh", "label"]]
            if group_key not in target_panels:
                target_panels[group_key] = labels
                catalog, assignments = identify_episodes(panel, ":".join(group_key))
                catalogs[group_key] = (catalog.assign(period=period, family=family), assignments)
                for link, group in panel.groupby("link_id"):
                    coverage.append(dict(period=period, family=family, link_id=link, expected_hours=len(group),
                        known_hours=int(group.label.notna().sum()), missing_hours=int(group.label.isna().sum()),
                        positive_hours=int(group.label.eq(1).sum())))
            else:
                pd.testing.assert_frame_equal(labels, target_panels[group_key], check_dtype=False, check_exact=True)
            catalog, assignments = catalogs[group_key]
            panel["episode_id"] = assignments
            days = (pd.Timestamp(end) - pd.Timestamp(start)).days
            for rule in cfg["rules"]:
                for cooldown in cfg["cooldown_hours"]:
                    label = dict(period=period, family=family, task=entry["task"], name=entry["name"],
                        horizon=entry["horizon"], rule=rule, cooldown_hours=cooldown,
                        threshold=entry["rules"][rule]["threshold"])
                    for minimum in cfg["minimum_observed_episode_hours"]:
                        measured, alerts, detections = assess(panel, catalog, label["threshold"], cooldown, minimum, days)
                        metrics.append(dict(**label, minimum_observed_hours=minimum, **measured))
                        if minimum == cfg["minimum_observed_episode_hours"][0]:
                            stem = f"{period}_{entry['task']}_{entry['name']}_h{entry['horizon']}_{rule}_c{cooldown}"
                            for suffix, table in [("alerts", alerts), ("detections", detections)]:
                                path = RAW / f"{stem}_{suffix}.parquet"
                                table.to_parquet(path, index=False)
                                artifacts.append(dict(**label, kind=suffix, path=str(path.relative_to(CASE)),
                                    sha256=sha256(path), rows=len(table)))
            print(f"구간 경보: {period} {entry['task']} {entry['name']} h{entry['horizon']}", flush=True)
    tables = {"metrics.csv": pd.DataFrame(metrics), "episodes.csv": pd.concat([c for c, _ in catalogs.values()], ignore_index=True),
              "coverage.csv": pd.DataFrame(coverage)}
    for name, table in tables.items():
        table.to_csv(OUT / name, index=False, lineterminator="\n")
    write_json(OUT / "audit.json", dict(completed_at=utcnow(), input_manifest_sha256=sha256(MANIFEST),
        code_sha256=sha256(__file__), outputs={name: sha256(OUT / name) for name in tables},
        metric_rows=len(metrics), local_artifacts=artifacts, limitations=[
          "2025 outcomes were already examined; no independent test or retuning",
          "low-label runs are descriptive events, not verified traffic incidents",
          "h1 origin equals target-hour start; h3 origin is two hours before target-hour start",
          "missing saved predictions are unknown; offline cooldown cannot reproduce production alerts through those gaps",
          "each period initializes an empty cooldown state; monthly archive availability is audited separately",
          "point metrics include all positive hours; minimum length filters only episode metrics",
          "no range-weighted precision/recall or external published metric is claimed"] ))
    print(f"경보 평가 {len(metrics)}행·저속 연속 구간 {len(tables['episodes.csv'])}개", flush=True)
