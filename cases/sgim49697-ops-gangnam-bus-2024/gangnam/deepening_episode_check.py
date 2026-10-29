"""경보 후속 결과를 기존 시간별 지표·독립 구간 판독·저장 알림과 대조한다."""

import json

import numpy as np
import pandas as pd

from .common import CASE, sha256, utcnow, write_json
from .deepening_episode import MANIFEST, OUT, SOURCE_AUDITS


def independently_identified(ref, period, family, cfg):
    frame = pd.read_parquet(CASE / ref["path"])
    start, end = cfg["periods"][period]
    grid = pd.date_range(start, end, inclusive="left", freq="h", tz=cfg["timezone"])
    rows = []
    for link in cfg["primary_links"]:
        labels = frame[frame.link_id.astype(str).eq(link)].set_index("target_start").label.reindex(grid)
        sequence = labels.ne(1).cumsum()
        for _, points in labels[labels.eq(1)].groupby(sequence):
            first, last = points.index[0], points.index[-1]
            previous, following = first - pd.Timedelta(hours=1), last + pd.Timedelta(hours=1)
            left, right = pd.isna(labels.get(previous, np.nan)), pd.isna(labels.get(following, np.nan))
            rows.append(dict(episode_id=f"{period}:{family}:{link}:{first.strftime('%Y%m%d%H')}",
                link_id=link, start=first, last_positive=last, observed_hours=len(points),
                left_censored=left, right_censored=right, known_onset=not left, period=period, family=family))
    return pd.DataFrame(rows)


def run():
    audit, manifest = [json.loads(path.read_text()) for path in [OUT / "audit.json", MANIFEST]]
    if audit["input_manifest_sha256"] != sha256(MANIFEST):
        raise ValueError("후속 경보 입력 명세 변경")
    inputs = {str(MANIFEST.relative_to(CASE)): sha256(MANIFEST)}
    for name, expected in audit["outputs"].items():
        if sha256(OUT / name) != expected:
            raise ValueError("후속 경보 출력 변경")
        inputs[str((OUT / name).relative_to(CASE))] = expected
    measured = pd.read_csv(OUT / "metrics.csv")
    published = pd.read_csv(OUT / "episodes.csv", dtype={"link_id": str})
    for col in ["start", "last_positive"]:
        published[col] = pd.to_datetime(published[col], utc=True).dt.tz_convert("Asia/Seoul")
    previous = {}
    for task, directory in SOURCE_AUDITS.items():
        path = f"results/overnight/{directory}/metrics.csv"
        previous[("summer", task)] = pd.read_csv(CASE / path)
        inputs[path] = sha256(CASE / path)
    path = "results/overnight/confirmation/probability_metrics.csv"
    confirmation = pd.read_csv(CASE / path)
    inputs[path] = sha256(CASE / path)
    for task in SOURCE_AUDITS:
        previous[("autumn", task)] = confirmation[confirmation.task.eq(task)]
    columns = {"known_hours": "rows", "positive_hours": "positives", "point_precision": "precision", "point_recall": "recall",
               **{name: name for name in ["alerts", "true_alerts", "false_alerts", "alerts_per_day", "threshold", "calendar_days"]}}
    checks = 0
    chosen = measured[measured.cooldown_hours.eq(0) & measured.minimum_observed_hours.eq(1)]
    for row in chosen.itertuples():
        old = previous[(row.period, row.task)]
        old = old[old.name.eq(row.name) & old.horizon.eq(row.horizon) & old.rule.eq(row.rule) & old["slice"].eq("primary_all_hours")]
        if len(old) != 1:
            raise ValueError("기존 시간별 지표 대응 불가")
        for new, original in columns.items():
            np.testing.assert_allclose(getattr(row, new), old.iloc[0][original], rtol=1e-12, atol=1e-12, equal_nan=True)
            checks += 1
    verified_groups = set()
    independently_read = []
    for entry in manifest["entries"]:
        family = "relative" if entry["task"] == "relative_probability" else "conditional"
        for period, ref in entry["predictions"].items():
            if (period, family) in verified_groups:
                continue
            if sha256(CASE / ref["path"]) != ref["sha256"]:
                raise ValueError("독립 구간 판독 원본 예측 변경")
            rebuilt = independently_identified(ref, period, family, manifest["configuration"])
            actual = published[published.period.eq(period) & published.family.eq(family)]
            pd.testing.assert_frame_equal(rebuilt.sort_values("episode_id").reset_index(drop=True),
                actual[rebuilt.columns].sort_values("episode_id").reset_index(drop=True), check_dtype=False, check_exact=True)
            verified_groups.add((period, family))
            independently_read.append(ref)
    artifact_rows, notification_files = 0, 0
    for artifact in audit["local_artifacts"]:
        path = CASE / artifact["path"]
        if sha256(path) != artifact["sha256"]:
            raise ValueError("저장 경보 상세 파일 변경")
        detail = pd.read_parquet(path)
        if len(detail) != artifact["rows"]:
            raise ValueError("저장 경보 상세 행 수 변경")
        artifact_rows += len(detail)
        if artifact["kind"] != "alerts":
            continue
        notification_files += 1
        if not detail.probability.ge(artifact["threshold"]).all():
            raise ValueError("임계값 아래의 경보")
        if not detail.target_start.sub(detail.origin).eq(pd.Timedelta(hours=artifact["horizon"] - 1)).all():
            raise ValueError("경보 발행 시계 불일치")
        if artifact["cooldown_hours"]:
            gaps = detail.sort_values("origin").groupby("link_id").origin.diff().dropna()
            if not gaps.ge(pd.Timedelta(hours=artifact["cooldown_hours"])).all():
                raise ValueError("재알림 간격 위반")
        selected = measured.minimum_observed_hours.eq(1)
        for key in ["period", "task", "name", "horizon", "rule", "cooldown_hours"]:
            selected &= measured[key].eq(artifact[key])
        metrics = measured[selected]
        if len(metrics) != 1 or int(metrics.iloc[0].alerts) != len(detail):
            raise ValueError("경보 상세와 집계 행 수 불일치")
        for name, count in detail["class"].value_counts().items():
            if metrics.iloc[0]["alerts_" + name] != count:
                raise ValueError("경보 시간 분류의 상세·집계 불일치")
    if not measured.loc[measured.horizon.eq(1), "advance_recall"].eq(0).all():
        raise ValueError("H1 발행에 시작 전 감지 크레딧이 있습니다")
    write_json(OUT / "validation.json", dict(completed_at=utcnow(), code_sha256=sha256(__file__), inputs=inputs,
        existing_metric_rows=len(chosen), existing_numeric_comparisons=checks, independent_episode_groups=len(verified_groups),
        independent_episodes=len(published), independent_sources=independently_read,
        verified_local_files=len(audit["local_artifacts"]), local_rows=artifact_rows,
        notification_files_checked=notification_files, mismatches=0))
    print(f"기존 지표 {len(chosen)}행·{checks}수치, 독립 연속 구간 {len(published)}개, 상세 파일 {len(audit['local_artifacts'])}개 일치", flush=True)
