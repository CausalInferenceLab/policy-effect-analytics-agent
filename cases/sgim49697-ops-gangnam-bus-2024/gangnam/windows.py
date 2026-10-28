"""학습 구간에서만 전처리를 맞추고 예측 발행시각 기준의 공통 창을 만든다."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta

import numpy as np
import pandas as pd

from .common import digest


def bounds(cfg, split):
    start, end = cfg["splits"][split]
    return pd.Timestamp(start, tz="Asia/Seoul"), pd.Timestamp(end, tz="Asia/Seoul") + timedelta(days=1)


def validate_config(cfg):
    if cfg["context_hours"] != 168 or cfg["output_hours"] != 3 or cfg["horizons"] != [1, 3]:
        raise ValueError("현재 구현은 입력 168시간·출력 3시간·평가 1/3시간 규약입니다")
    previous = None
    for split in ("train", "validation", "pre_test", "transition", "post_test"):
        start, end = bounds(cfg, split)
        if start >= end or (previous is not None and start != previous):
            raise ValueError("전역 시간 분할에 중첩·공백 또는 역전이 있습니다")
        previous = end


@dataclass
class Prepared:
    times: pd.DatetimeIndex
    links: list[str]
    raw: np.ndarray
    filled: np.ndarray
    observed: np.ndarray
    means: np.ndarray
    scales: np.ndarray
    calendar_means: np.ndarray
    cfg: dict
    identity: str
    dataset_identity: str

    def keys(self, split):
        """(발행시각의 행 번호, 링크 열 번호). 모든 출력이 분할 안의 실측일 때만 사용."""
        start, end = bounds(self.cfg, split)
        c, h = self.cfg["context_hours"], self.cfg["output_hours"]
        counts = np.vstack([np.zeros((1, len(self.links))), np.cumsum(self.observed, axis=0)])
        keys = []
        for i in np.flatnonzero((self.times >= start) & (self.times + timedelta(hours=h) <= end)):
            if i < c:
                continue
            context_ok = (counts[i] - counts[i - c]) / c >= self.cfg["minimum_observed_context"]
            labels_ok = self.observed[i:i + h].all(axis=0)
            keys.extend((i, int(j)) for j in np.flatnonzero(context_ok & labels_ok))
        return np.asarray(keys, dtype=np.int64).reshape(-1, 2)

    def batch(self, keys, scaled=True):
        c, h = self.cfg["context_hours"], self.cfg["output_hours"]
        rows, cols = keys[:, :1], keys[:, 1:2]
        past = rows + np.arange(-c, 0)
        x = self.filled[past, cols].astype("float32")
        y = self.raw[rows + np.arange(h), cols].astype("float32")
        mask = self.observed[past, cols]
        j = keys[:, 1]
        if scaled:
            x = (x - self.means[j, None]) / self.scales[j, None]
            y = (y - self.means[j, None]) / self.scales[j, None]
        return x, y, mask

    def targets(self, keys):
        return self.raw[keys[:, :1] + np.arange(self.cfg["output_hours"]), keys[:, 1:2]]


def prepare(hourly, cfg):
    validate_config(cfg)
    if hourly.duplicated(["link_id", "interval_start_kst"]).any():
        raise ValueError("링크×시각 중복")
    data = hourly.copy()
    data["link_id"] = data.link_id.astype(str)
    data.loc[~data.is_valid, "speed_kmh"] = np.nan
    wide = data.pivot(index="interval_start_kst", columns="link_id", values="speed_kmh").sort_index()
    if wide.index.tz is None or str(wide.index.tz) != "Asia/Seoul":
        raise ValueError("정규화 자료는 Asia/Seoul 시간대여야 합니다")
    start, _ = bounds(cfg, "train")
    _, end = bounds(cfg, "post_test")
    if wide.index.min() > start or wide.index.max() < end - timedelta(hours=1):
        raise ValueError("2023~2024 전체 요청 기간이 없습니다. 축소 분석은 설정 변경으로 기록하세요")
    times = pd.date_range(start, end, freq="h", inclusive="left")
    wide = wide.reindex(times)
    train_start, train_end = bounds(cfg, "train")
    train_mask = (times >= train_start) & (times < train_end)
    coverage = wide.loc[train_mask].notna().mean()
    eligible = sorted(coverage[coverage >= cfg["minimum_train_coverage"]].index)
    required = cfg["required_links"]
    if not set(required) <= set(eligible):
        raise ValueError("핵심 링크가 학습기간 관측률 기준에 미달합니다")
    if cfg["max_links"] < len(required):
        raise ValueError("max_links가 핵심 링크 수보다 작습니다")
    links = sorted(required + [x for x in eligible if x not in required][:cfg["max_links"] - len(required)])
    wide = wide[links]
    raw = wide.to_numpy(dtype="float32")
    observed = np.isfinite(raw)
    if np.isinf(raw).any():
        raise ValueError("비유한 관측값")
    train = raw[train_mask]
    means = np.nanmean(train, axis=0)
    scales = np.nanstd(train, axis=0)
    scales = np.where(scales > 1e-6, scales, 1).astype("float32")
    calendar = times.weekday * 24 + times.hour
    calendar_means = np.empty((168, len(links)), dtype="float32")
    for hour in range(168):
        cells = train[calendar[train_mask] == hour]
        counts = np.isfinite(cells).sum(axis=0)
        calendar_means[hour] = np.divide(np.nansum(cells, axis=0), counts,
                                         out=means.copy(), where=counts > 0)
    # ffill은 과거 방향으로만, 3시간까지. 나머지는 학습 구간 요일·시간 평균.
    filled = wide.ffill(limit=cfg["forward_fill_limit"]).to_numpy(dtype="float32")
    filled = np.where(np.isfinite(filled), filled, calendar_means[calendar])
    identity = digest({"config": cfg, "links": links,
                       "train_hash": hashlib.sha256(train.tobytes()).hexdigest()})
    dataset_identity = hashlib.sha256(raw.tobytes()).hexdigest()
    return Prepared(times, links, raw, filled, observed, means, scales, calendar_means, cfg, identity, dataset_identity)


def baseline(name, data, keys):
    pred = []
    for i, j in keys:
        if name == "last_value":
            p = [data.filled[i - 1, j]] * 3
        elif name == "weekly_naive":
            p = data.filled[i - 168:i - 165, j]
        elif name == "weekday_hour_mean":
            ts = data.times[i:i + 3]
            p = data.calendar_means[ts.weekday * 24 + ts.hour, j]
        else:
            raise ValueError(name)
        pred.append(p)
    return np.asarray(pred, dtype="float32")


def features(data, keys, horizon, holiday_dates):
    frames = []
    for offset in range(0, len(keys), 8192):
        part = keys[offset:offset + 8192]
        past, _, seen = data.batch(part, scaled=False)
        target = data.times[part[:, 0] + horizon - 1]
        values = {"link_id": np.asarray(data.links)[part[:, 1]]}
        values.update({f"lag{n}": past[:, -n] for n in (1, 2, 3, 24, 168)})
        values.update({f"mean{n}": past[:, -n:].mean(axis=1) for n in (3, 24, 168)})
        values.update({f"std{n}": past[:, -n:].std(axis=1) for n in (24, 168)})
        values["observed_fraction"] = seen.mean(axis=1)
        values.update({f"mask{n}": seen[:, -n].astype(int) for n in (1, 2, 3, 24, 168)})
        values.update({"hour": target.hour, "weekday": target.weekday,
                       "holiday": target.strftime("%Y-%m-%d").isin(holiday_dates).astype(int)})
        frames.append(pd.DataFrame(values))
    return pd.concat(frames, ignore_index=True)


def prediction_frame(data, keys, predictions, model, seed, split):
    if predictions.shape != (len(keys), 3):
        raise ValueError("예측 형태가 공통 평가 창과 다릅니다")
    truth = data.targets(keys)
    horizons = np.asarray(data.cfg["horizons"])
    values = predictions[:, horizons - 1].reshape(-1)
    if not np.isfinite(values).all():
        raise ValueError("예측 실패 값을 평가에서 조용히 제외할 수 없습니다")
    return pd.DataFrame({"model": model, "seed": seed, "split": split,
        "link_id": np.repeat(np.asarray(data.links)[keys[:, 1]], len(horizons)),
        "issue_time_kst": data.times[np.repeat(keys[:, 0], len(horizons))],
        "horizon": np.tile(horizons, len(keys)),
        "target_start_kst": data.times[(keys[:, :1] + horizons - 1).reshape(-1)],
        "y_true": truth[:, horizons - 1].reshape(-1), "y_pred": values})


def score(frame, required_links):
    key = ["link_id", "issue_time_kst", "horizon"]
    if frame.duplicated(key).any() or not np.isfinite(frame[["y_true", "y_pred"]]).all().all():
        raise ValueError("평가 키 중복 또는 비유한 정답·예측")
    groups = {"all": frame, "gangnam": frame[frame.link_id.isin(required_links)],
              "evening": frame[frame.target_start_kst.dt.hour.isin([17, 18, 19])]}
    groups.update({f"link:{link}": g for link, g in frame.groupby("link_id")})
    rows = []
    for group, data in groups.items():
        for h, part in data.groupby("horizon"):
            e = part.y_pred.to_numpy() - part.y_true.to_numpy()
            rows.append({"group": group, "horizon": int(h), "n": len(e),
                         "mae": float(np.abs(e).mean()), "rmse": float(np.sqrt(np.mean(e * e)))})
    return rows


def assert_common_keys(frames):
    canonical = None
    for frame in frames:
        keys = frame.set_index(["split", "link_id", "issue_time_kst", "horizon"])["y_true"].sort_index()
        if keys.index.has_duplicates:
            raise ValueError("모델 내 평가 키 중복")
        if canonical is not None and not canonical.equals(keys):
            raise ValueError("모델별 평가 키 또는 실측 정답이 다릅니다")
        canonical = keys
