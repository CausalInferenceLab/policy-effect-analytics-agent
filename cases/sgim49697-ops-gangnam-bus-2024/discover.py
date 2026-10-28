"""공식 추가 자료의 고정 원본·결합 가능성과 기존 예측의 저속 상황을 탐색한다."""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import numpy as np
import pandas as pd
from gangnam.common import CASE, read_yaml, sha256, write_json
from gangnam.topis import session, validate_xlsx

RAW = CASE / "data/discovery"
OUT = CASE / "results/discovery"
KEYS = ["기준_날짜", "노선_ID", "정류장_ID", "정류장_순서"]


def check_file(path, entry):
    if path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
        raise ValueError(f"고정 원본과 해시·크기가 다릅니다. 기존 파일을 보존하세요: {path.name}")
    if path.suffix == ".xlsx":
        validate_xlsx(path)
    elif path.suffix == ".zip":
        try:
            with ZipFile(path) as z:
                if not z.namelist() or any(not n.endswith(".csv") for n in z.namelist()):
                    raise ValueError("예상하지 못한 ZIP 구성")
                if sum(i.file_size for i in z.infolist()) > 2 * 1024**3:
                    raise ValueError("ZIP 해제 크기가 점검 한도 2 GiB를 넘습니다")
        except BadZipFile as e:
            raise ValueError("정상 ZIP이 아닙니다") from e
    elif path.suffix == ".csv":
        pd.read_csv(path, encoding="cp949", nrows=1)
    elif path.suffix == ".pdf":
        with path.open("rb") as f:
            if f.read(5) != b"%PDF-":
                raise ValueError("정상 PDF가 아닙니다")


def collect(entries, folder=RAW):
    """공개 화면의 조회·파일 다운로드 요청만 재현하며 변경된 원본은 덮어쓰지 않는다."""
    folder.mkdir(parents=True, exist_ok=True)
    with session() as client:
        for entry in entries:
            path = folder / entry["file"]
            if path.parent != folder or path.name != entry["file"]:
                raise ValueError("원본 이름은 파일명 하나여야 합니다")
            if not path.exists():
                temporary = path.with_suffix(path.suffix + ".part")
                try:
                    method = entry["method"]
                    if method not in {"GET", "POST"} or not entry["url"].startswith("https://"):
                        raise ValueError("허용하지 않는 다운로드 요청")
                    with client.request(method, entry["url"], data=entry.get("request"),
                                        headers={"Referer": entry["source"]}, stream=True,
                                        timeout=(15, 120)) as response:
                        response.raise_for_status()
                        if "html" in response.headers.get("Content-Type", "").lower():
                            raise ValueError("원본 대신 HTML 오류 응답을 받았습니다")
                        size = 0
                        with temporary.open("wb") as f:
                            for chunk in response.iter_content(1024 * 1024):
                                size += len(chunk)
                                if size > entry["bytes"]:
                                    raise ValueError("원격 파일 크기가 바뀌었습니다. 새 탐색 버전이 필요합니다")
                                f.write(chunk)
                    if size != entry["bytes"] or sha256(temporary) != entry["sha256"]:
                        raise ValueError("원격 원본 변경 또는 불완전한 다운로드")
                    temporary.replace(path)
                finally:
                    temporary.unlink(missing_ok=True)
            check_file(path, entry)
            print(f"확인: {path.name} ({entry['bytes']:,} bytes)", flush=True)


def csv(path):
    return pd.read_csv(path, encoding="cp949", dtype=str)


def read_bus_sample(path, member, hours):
    """ZIP의 명시적 한 주만 읽는다. 월 파일명을 실제 날짜 범위로 가정하지 않는다."""
    with ZipFile(path) as z:
        if member not in z.namelist():
            raise ValueError(f"지정 주간 자료가 없습니다: {member}")
        with z.open(member) as f:
            header = pd.read_csv(f, encoding="cp949", nrows=0).columns.tolist()
        is_time = "출발_정류장_ID" in header
        value = "운행시간" if is_time else ("버스운행횟수" if "버스운행횟수" in header else "승차_승객_수")
        cols = [f"{value}_{h:02}시" for h in hours]
        rename = {"출발_정류장_ID": "정류장_ID", "출발_정류장_순서": "정류장_순서"}
        required = ["기준_날짜", "노선_ID"] + (list(rename) + ["도착_정류장_ID", "도착_정류장_순서"] if is_time else KEYS[2:])
        with z.open(member) as f:
            d = pd.read_csv(f, encoding="cp949", dtype=str, usecols=required + cols).rename(columns=rename)
        for col in cols:
            d[col] = pd.to_numeric(d[col], errors="raise")
        raw_keys = KEYS + (["도착_정류장_ID", "도착_정류장_순서"] if is_time else [])
        summary = {"member": member, "archive_members": sorted(z.namelist()), "rows": len(d),
                   "dates": sorted(d["기준_날짜"].unique().tolist()), "routes": d["노선_ID"].nunique(),
                   "duplicate_full_keys": int(d.duplicated(raw_keys).sum()),
                   "route_zero_rows": int(d["노선_ID"].eq("0").sum()),
                   "hours_profiled": hours, "missing_cells": int(d[cols].isna().sum().sum()),
                   "zero_cells": int(d[cols].eq(0).sum().sum()),
                   "negative_cells": int(d[cols].lt(0).sum().sum())}
        return d, summary


def join_bus(left, right, label):
    """순환 노선의 재방문을 구분하도록 정류장 순서를 반드시 포함한다."""
    if right.duplicated(KEYS).any() or right[KEYS].isna().any().any():
        raise ValueError(f"{label}: 결합 키의 중복 또는 결측")
    merged = left.merge(right, on=KEYS, how="left", validate="many_to_one", indicator=label)
    return merged, float(merged[label].eq("both").mean())


def audit_bus(cfg):
    routes, stops = csv(RAW / "route_master.csv"), csv(RAW / "stop_master.csv")
    if routes["노선_ID"].duplicated().any() or stops["정류장_ID"].duplicated().any():
        raise ValueError("마스터 ID 중복")
    latitude = pd.to_numeric(stops["위도"], errors="coerce")
    longitude = pd.to_numeric(stops["경도"], errors="coerce")
    selected = stops[latitude.between(*cfg["stop_box"]["latitude"]) & longitude.between(*cfg["stop_box"]["longitude"])]
    candidate = routes[routes["노선_명칭"].str.match(cfg["route_candidate_pattern"], na=False)]
    frames, profiles = {}, {}
    for filename, member in cfg["bus_samples"].items():
        d, profile = read_bus_sample(RAW / filename, member, cfg["hours"])
        observed = set(d["노선_ID"])
        profile["route_master_matched_ids"] = len(observed & set(routes["노선_ID"]))
        profile["stop_master_matched_row_fraction"] = float(d["정류장_ID"].isin(stops["정류장_ID"]).mean())
        part = d[d["정류장_ID"].isin(selected["정류장_ID"])].copy()
        profile["box_rows"] = len(part)
        profile["box_routes"] = part["노선_ID"].nunique()
        full_keys = KEYS + (["도착_정류장_ID", "도착_정류장_순서"] if "도착_정류장_ID" in part else [])
        profile["box_duplicate_full_keys"] = int(part.duplicated(full_keys).sum())
        profile["box_identical_rows"] = int(part.duplicated().sum())
        profile["candidate_names_observed_in_box"] = candidate[candidate["노선_ID"].isin(part["노선_ID"])][["노선_ID", "노선_명칭"]].to_dict("records")
        frames[filename], profiles[filename] = part, profile
    joined, trips_rate = join_bus(frames["bus_time_202407.zip"], frames["bus_trips_202407.zip"], "trip_match")
    joined, boarding_rate = join_bus(joined, frames["bus_boardings_202407.zip"], "boarding_match")
    ambiguous, complete_cells = 0, 0
    for h in cfg["hours"]:
        ambiguous += int(
            (joined[f"운행시간_{h:02}시"].gt(0) & joined[f"버스운행횟수_{h:02}시"].fillna(0).le(0)).sum())
        complete_cells += int((joined[f"운행시간_{h:02}시"].gt(0) & joined[f"버스운행횟수_{h:02}시"].gt(0)
                               & joined[f"승차_승객_수_{h:02}시"].notna()).sum())
    return {"master_valid_on_2024": "unverified", "route_master_rows": len(routes), "stop_master_rows": len(stops),
            "box_stop_count": len(selected), "samples": profiles,
            "join": {"rows": len(joined), "keys": KEYS, "trip_match_fraction": trips_rate,
                     "boarding_match_fraction": boarding_rate,
                     "profiled_hour_cells": len(joined) * len(cfg["hours"]),
                     "positive_time_and_trips_with_recorded_boardings_cells": complete_cells,
                     "positive_time_without_positive_departure_trip_cells": ambiguous},
            "note": "현 마스터의 명칭·좌표는 2024년 유효성 미검증. 후보 노선 매칭은 정책 대상 확정이 아니다. 운행시간 단위·0·집계 분모 미확인으로 효과·승객시간은 계산하지 않는다."}


def audit_boarding(cfg):
    summaries = {}
    for month in ("202405", "202407"):
        d = csv(RAW / f"boarding_{month}.csv")
        if set(d["사용년월"]) != {month}:
            raise ValueError("월별 승하차 자료의 월 불일치")
        candidate = d["노선번호"].str.match(cfg["route_candidate_pattern"], na=False)
        summaries[month] = {"rows": len(d), "routes": d["노선번호"].nunique(),
                            "candidate_number_matches": sorted(d.loc[candidate, "노선번호"].unique().tolist()),
                            "time_grain": "month × route × stop × hour-of-day"}
    return summaries


def audit_volume(cfg):
    from openpyxl import load_workbook

    profiles = {}
    for month in ("202405", "202407"):
        w = load_workbook(RAW / f"volume_{month}.xlsx", read_only=True, data_only=True)
        try:
            rows = w[f"{month[:4]}년 {month[4:]}월"].values
            d = pd.DataFrame(rows, columns=next(rows))
            if list(d.columns[6:]) != [f"{h}시" for h in range(24)]:
                raise ValueError("교통량 시간 헤더 변경")
            d = d[d["지점번호"].isin(cfg["volume_points"])].copy()
            if d.duplicated(["일자", "지점번호", "방향"]).any():
                raise ValueError("교통량 키 중복")
            long = d.melt(id_vars=["일자", "지점번호", "방향", "구분"], value_vars=d.columns[6:], var_name="hour", value_name="count")
            numeric = pd.to_numeric(long["count"], errors="coerce")
            invalid = long["count"].notna() & numeric.isna()
            summaries = []
            for (point, direction), part in long.assign(numeric=numeric).groupby(["지점번호", "방향"]):
                summaries.append({"point": point, "direction": direction, "description": part["구분"].iloc[0],
                                  "cells": len(part), "missing": int(part.numeric.isna().sum()),
                                  "zero": int(part.numeric.eq(0).sum()), "negative": int(part.numeric.lt(0).sum())})
            join_cfg = cfg["volume_join"]
            target = long[(long["지점번호"] == join_cfg["point"]) & (long["방향"] == join_cfg["direction"])].copy()
            target["interval_start_kst"] = pd.to_datetime(target["일자"].astype(str), format="%Y%m%d").dt.tz_localize("Asia/Seoul") + pd.to_timedelta(target.hour.str.removesuffix("시").astype(int), unit="h")
            speed = pd.read_parquet(CASE / "data/processed" / f"{month[:4]}-{month[4:]}.parquet")
            speed = speed[speed.link_id.isin(join_cfg["links"])]
            joined = speed.merge(target[["interval_start_kst", "count"]], on="interval_start_kst", how="left", validate="many_to_one", indicator=True)
            profiles[month] = {"selected_cells": len(long), "points": summaries,
                               "unexpected_values": sorted(long.loc[invalid, "count"].astype(str).unique().tolist()),
                               "speed_join_rows": len(joined), "speed_time_key_match_fraction": float(joined._merge.eq("both").mean()),
                               "speed_valid_and_volume_numeric_rows": int((joined.is_valid & pd.to_numeric(joined["count"], errors="coerce").notna()).sum()),
                               "spatial_join_status": join_cfg["status"]}
        finally:
            w.close()
    return profiles


def fit_thresholds(train, start, end, quantile):
    d = train.copy()
    t = d.interval_start_kst
    end_exclusive = pd.Timestamp(date.fromisoformat(end) + timedelta(days=1), tz="Asia/Seoul")
    if t.min() < pd.Timestamp(start, tz="Asia/Seoul") or t.max() >= end_exclusive:
        raise ValueError("정체 기준 학습에 허용 기간 밖의 자료가 들어왔습니다")
    d = d[d.is_valid & d.speed_kmh.notna()].copy()
    d["hour"], d["weekend"] = d.interval_start_kst.dt.hour, d.interval_start_kst.dt.dayofweek.ge(5)
    return d.groupby(["link_id", "hour", "weekend"]).speed_kmh.quantile(quantile).rename("threshold").reset_index()


def tail_score(d):
    if d.empty or d[["y_true", "y_pred", "threshold"]].isna().any().any():
        raise ValueError("저속 진단 입력이 비었거나 결측이 있습니다")
    positive, alert = d.y_true.le(d.threshold), d.y_pred.le(d.threshold)
    tp = int((positive & alert).sum())
    mae = (d.y_true - d.y_pred).abs()
    return {"n": len(d), "low_speed_n": int(positive.sum()), "alert_n": int(alert.sum()),
            "mae": float(mae.mean()), "low_speed_mae": float(mae[positive].mean()) if positive.any() else None,
            "recall": tp / int(positive.sum()) if positive.any() else None,
            "precision": tp / int(alert.sum()) if alert.any() else None,
            "missed_low_speed_n": int((positive & ~alert).sum())}


def diagnose(cfg):
    spec = cfg["tail_diagnostic"]
    paths = sorted((CASE / "data/processed").glob("*.parquet"))
    paths = [p for p in paths if spec["fit_start"][:7] <= p.stem <= spec["fit_end"][:7]]
    train = pd.concat([pd.read_parquet(p) for p in paths], ignore_index=True)
    thresholds = fit_thresholds(train, spec["fit_start"], spec["fit_end"], spec["quantile"])
    rows, source_hashes, common = [], {str(p.relative_to(CASE)): sha256(p) for p in paths}, {}
    for model in spec["models"]:
        folder = CASE / "runs" / cfg["original_run"] / model
        seeds = json.loads((folder / "selection.json").read_text())["seeds"]
        for split in spec["splits"]:
            for seed in seeds:
                path = folder / f"{split}-seed-{seed}.parquet"
                d = pd.read_parquet(path)
                d = d[d.horizon.isin(spec["horizons"])].copy()
                keys = ["link_id", "target_start_kst", "horizon"]
                if d.duplicated(keys).any():
                    raise ValueError("예측의 중복 키")
                truth = d[keys + ["y_true"]].sort_values(keys).reset_index(drop=True)
                if split in common and not truth.equals(common[split]):
                    raise ValueError("모델 간 공통 평가 키·정답 불일치")
                common[split] = truth
                d["hour"], d["weekend"] = d.target_start_kst.dt.hour, d.target_start_kst.dt.dayofweek.ge(5)
                d = d.merge(thresholds, on=spec["groups"], how="left", validate="many_to_one")
                source_hashes[str(path.relative_to(CASE))] = sha256(path)
                for horizon in spec["horizons"]:
                    h = d[d.horizon.eq(horizon)]
                    for group, mask in {"all": np.ones(len(h), dtype=bool), "core": h.link_id.isin(cfg["core_links"]),
                                        "core_evening": h.link_id.isin(cfg["core_links"]) & h.hour.isin(cfg["hours"])}.items():
                        rows.append({"model": model, "seed": seed, "split": split, "horizon": horizon,
                                     "group": group, **tail_score(h[mask])})
    metrics = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(OUT / "tail_metrics.csv", index=False, float_format="%.8f")
    thresholds.to_csv(RAW / "train_thresholds.csv", index=False)
    write_json(OUT / "tail_provenance.json", {"mode": cfg["mode"], "fit": spec, "threshold_groups": len(thresholds),
                                               "source_hashes": source_hashes,
                                               "discovery_config_sha256": sha256(CASE / "discovery_config.yaml"),
                                               "code_sha256": sha256(Path(__file__))})
    plot_tail(metrics)


def plot_tail(metrics):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    d = metrics[(metrics.split == "post_test") & (metrics.group == "core_evening")]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), sharey=True)
    for ax, horizon in zip(axes, (1, 3), strict=True):
        part = d[d.horizon.eq(horizon)].groupby("model").recall.agg(["mean", "std"])
        ax.barh(part.index, part["mean"] * 100, xerr=part["std"].fillna(0) * 100, capsize=3)
        ax.set(xlim=(0, 100), xlabel="Low-speed recall (%)", title=f"{horizon}h horizon")
        ax.grid(axis="x", alpha=0.2)
    fig.suptitle("Did forecasts flag unusually slow evening traffic?\nThree policy-core links, Jul-Aug 2024; exploratory train-only q10 threshold", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "low_speed_recall.png", dpi=160)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["collect", "audit", "diagnose"])
    args = p.parse_args()
    cfg = read_yaml("discovery_config.yaml")
    entries = json.loads((CASE / "discovery-sources.json").read_text())["files"]
    if args.action == "collect":
        collect(entries)
    elif args.action == "audit":
        for entry in entries:
            check_file(RAW / entry["file"], entry)
        write_json(OUT / "data_audit.json", {"mode": cfg["mode"], "bus": audit_bus(cfg),
                    "monthly_boarding": audit_boarding(cfg), "volume": audit_volume(cfg),
                    "source_manifest_sha256": sha256(CASE / "discovery-sources.json"),
                    "config_sha256": sha256(CASE / "discovery_config.yaml"), "code_sha256": sha256(Path(__file__))})
    else:
        diagnose(cfg)


if __name__ == "__main__":
    main()
