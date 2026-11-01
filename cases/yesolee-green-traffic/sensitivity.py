"""사전 계획의 대조군·기간 비교. 주분석 표와 결과를 보존하고 별도 결과를 쓴다."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

import pandas as pd
from fetch import CONTROL_STATIONS, SENSITIVITY_CONTROL_STATIONS, TREATED

from core.agent.nodes import quality_checks
from core.pipeline import run_plan, split_hours
from core.schema.plan import Plan, load_plan

HERE = Path(__file__).resolve().parent
SCENARIOS = (
    ("core_controls", "핵심 대조군 4곳"),
    ("post_to_20200119", "정책 후 2020-01-19까지"),
    ("post_to_20200131", "정책 후 2020-01-31까지"),
    ("exclude_2020", "2020년 관측 제외"),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def select_scenario(df: pd.DataFrame, key: str) -> pd.DataFrame:
    """주분석의 공통 관측시간과 시간 번호를 유지하면서 한 조건만 바꾼다."""
    if key == "core_controls":
        mask = df.station_id.isin(TREATED | set(SENSITIVITY_CONTROL_STATIONS))
    else:
        clock = pd.to_datetime(df.datetime, utc=True).dt.tz_convert("Asia/Seoul")
        if key == "post_to_20200119":
            mask = clock.lt(pd.Timestamp("2020-01-20", tz="Asia/Seoul"))
        elif key == "post_to_20200131":
            mask = clock.lt(pd.Timestamp("2020-02-01", tz="Asia/Seoul"))
        elif key == "exclude_2020":
            mask = clock.dt.year.ne(2020)
        else:
            raise ValueError(f"정의되지 않은 민감도 분석: {key}")
    return df.loc[mask].copy()


def validate_sample(df: pd.DataFrame, plan: Plan, stations: set[str]) -> list[dict]:
    """군집 수만 같은 불균형 표가 RI에 들어가지 않도록 실제 공통 시점을 확인한다."""
    if set(df.station_id) != stations:
        raise ValueError("사전 지정한 측정소 명단과 분석 표가 다릅니다.")
    if df.duplicated(["station_id", "hour_idx"]).any():
        raise ValueError("측정소×시간 중복이 있습니다.")
    if (
        df.no2.isna().any()
        or not df.groupby("hour_idx").station_id.nunique().eq(len(stations)).all()
    ):
        raise ValueError("결측 없는 공통 관측시간 표가 필요합니다.")
    checks = quality_checks(plan, df)
    if failed := [x for x in checks if x["status"] == "failed"]:
        raise ValueError(f"품질검사 실패: {failed}")
    active, inactive = split_hours(plan, df)
    for sample in (active, inactive):
        if sample is None or sample.empty:
            raise ValueError("주간·야간 자료가 모두 필요합니다.")
        relative = (sample.hour_idx - plan.treatment.treat_time) // plan.estimator.bin
        if not relative.eq(plan.estimator.ref_period).any():
            raise ValueError("기준 주의 관측이 없습니다.")
        if not relative.ge(0).any():
            raise ValueError("정책 후 관측이 없습니다.")
    return checks


def clean_json(value):
    """무한 신뢰구간을 비표준 Infinity 대신 null로 저장한다. 구간 종류는 별도 필드다."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    return value


def summarise(key: str, label: str, result: dict, alpha: float, pre_alpha: float) -> dict:
    checked = result["assumptions_checked"]
    assignments = checked["ri_assignments"]
    floor = 1 / (assignments + 1)
    low, high = result["ci_low"], result["ci_high"]
    if math.isfinite(low) and math.isfinite(high):
        kind = "finite"
    elif low == -math.inf and high == math.inf:
        kind = "unbounded"
    else:
        kind = "unavailable"
    coefs = result["extra"]["coefs"]
    post_bins = [int(row["rel_time"]) for row in coefs if row["rel_time"] >= 0]
    return {
        "id": key,
        "label": label,
        "estimate": result["estimate"],
        "ci_low": low,
        "ci_high": high,
        "ci_kind": kind,
        "p_value": result["p_value"],
        "n_obs": result["n_obs"],
        "n_clusters": result["n_clusters"],
        "verdict": result["verdict"],
        "ri_assignments": assignments,
        "p_min": floor,
        "effect_test_resolvable": floor <= alpha,
        "diagnostic_tests_resolvable": floor <= pre_alpha,
        "pretrend_p": checked["parallel_pretrends"]["p_value"],
        "placebo_time_p": checked["placebo_time"]["p_value"],
        "placebo_window_p": checked["placebo_window"]["p_value"],
        "post_bins": post_bins,
        "post_bin_count": len(post_bins),
    }


def number(value, digits=4) -> str:
    return "계산 불가" if value is None else f"{value:.{digits}f}"


def render_markdown(records: list[dict]) -> str:
    lines = [
        "# NO₂ 민감도 분석",
        "",
        "주분석의 공통 관측시간 표에서 사전 계획의 조건만 바꿨다. 주분석 결과는 기존 실행 기록을 재사용했다.",
        "대조군 4곳 비교는 11곳의 공통 시간 중 해당 6개 측정소 행만 사용하며, 관측시간을 새로 늘리지 않았다.",
        "",
        "| 분석 | 측정소 수 | 주간 N | 추정치(ppm) | 95% 구간 | p | 판정 |",
        "|---|---:|---:|---:|---|---:|---|",
    ]
    verdicts = {
        "conditional": "크기를 판별하지 못함",
        "not_identified": "판단 불가",
        "identified": "효과 근거 있음(가정 하에서)",
    }
    for entry in records:
        s = entry["summary"]
        if s["ci_kind"] == "finite":
            interval = f"[{number(s['ci_low'])}, {number(s['ci_high'])}]"
        elif s["ci_kind"] == "unbounded":
            interval = "(-∞, +∞)"
        else:
            interval = "계산 불가"
        lines.append(
            f"| {s['label']} | {s['n_clusters']} | {s['n_obs']:,} | {number(s['estimate'])} | {interval} | {number(s['p_value'], 3)} | {verdicts[s['verdict']]} |"
        )
    lines += [
        "",
        "## 자동 검정과 계산 범위",
        "",
        "| 분석 | 가짜 배정 수 | 최소 p | 사전계수 p | 가짜 시점 p | 야간 p | 사후 계수 구간 |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for entry in records:
        s = entry["summary"]
        lines.append(
            f"| {s['label']} | {s['ri_assignments']} | {number(s['p_min'], 3)} | {number(s['pretrend_p'], 3)} | {number(s['placebo_time_p'], 3)} | {number(s['placebo_window_p'], 3)} | {', '.join(map(str, s['post_bins']))} |"
        )
    lines += [
        "",
        "## 해석할 때의 제한",
        "",
        "- 핵심 대조군 4곳의 가짜 배정은 6가지다. 현행 공통 구현의 최소 p값은 1/7(약 0.143)로 5% 효과 검정과 10% 진단 검정 모두 기각이 불가능하다. 큰 p값을 검정 통과의 근거로 쓰지 않는다.",
        "- 기간 비교는 사후 관측기간과 추정 가능한 사후 계수 집합이 함께 바뀐다. 각 추정치는 해당 계수들의 단순평균이므로 동일한 사후 기간의 효과를 추정한 값으로 취급하지 않는다.",
        "- 짧은 사후 기간은 코로나 영향을 완전히 제거하지 않고 계절관리제·주차요금 변화와 겹친다. 2020년을 제외해도 2021년의 코로나 영향은 남는다.",
        "- 공통 시간 선택에 따른 결측 선택 편향, 처치 측정소 2곳의 한계, 대조군 비교 가능성과 동시 정책에 대한 수동 점검은 별도로 남는다.",
        "- 어느 결과도 효과 없음의 입증이나 인과관계의 확정으로 해석하지 않는다. 모든 사전 지정 비교를 함께 보고하며 주분석을 교체하지 않는다.",
        "",
        "## 재현 방법",
        "",
        "- 실행: `.venv/bin/python cases/yesolee-green-traffic/sensitivity.py`",
        "- 상세 결과, 표본·품질검사와 실행 환경 기록: `results/sensitivity.json`",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    plan_path = HERE / "plan.yaml"
    plan = load_plan(plan_path)
    data_path = HERE / plan.data_sources[0].path
    manifest = json.loads((HERE / "run_manifest.json").read_text())
    baseline = json.loads((HERE / "flow_log.json").read_text())
    if sha256(plan_path) != manifest["plan_sha256"] or sha256(data_path) != manifest["data_sha256"]:
        raise ValueError(
            "주분석 실행 기록과 현재 계획·자료가 다릅니다. 먼저 주분석 기록을 확인하세요."
        )
    if baseline["status"] not in {"ok", "warn"} or len(baseline["results"]) != 1:
        raise ValueError("완료된 NO₂ 주분석 결과가 필요합니다.")
    if plan.primary_outcome.col != "no2" or plan.estimator.method != "event_study":
        raise ValueError("이 실행기는 현재 NO₂ 이벤트 스터디 계획을 위한 비교입니다.")
    df = pd.read_csv(data_path, dtype={"station_id": str})
    validate_sample(df, plan, TREATED | set(CONTROL_STATIONS))
    before = set(df.loc[df.hour_idx.lt(plan.treatment.treat_time), "hour_idx"])
    records = [
        {
            "summary": summarise(
                "main",
                "주분석: 대조군 9곳",
                baseline["results"][0],
                plan.estimator.alpha,
                plan.thresholds.pretrend_alpha,
            ),
            "source": "flow_log.json",
        }
    ]
    run_meta = {
        "plan_sha256": sha256(plan_path),
        "data_sha256": sha256(data_path),
        "script_sha256": sha256(Path(__file__)),
        "baseline_flow_sha256": sha256(HERE / "flow_log.json"),
        "baseline_manifest_sha256": sha256(HERE / "run_manifest.json"),
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": git("rev-parse", "HEAD"),
        "git_dirty": bool(git("status", "--porcelain", "--", ".")),
        "baseline_git_sha": manifest["git_sha"],
        "versions": {
            name: metadata.version(name) for name in ["pandas", "numpy", "scipy", "pyfixest"]
        },
    }
    for key, label in SCENARIOS:
        print(f"[sensitivity] {label}: 시작", flush=True)
        sample = select_scenario(df, key)
        if set(sample.loc[sample.hour_idx.lt(plan.treatment.treat_time), "hour_idx"]) != before:
            raise ValueError("사전 관측시간이 주분석과 달라졌습니다.")
        trial = plan.model_copy(deep=True)
        trial.time.end = int(sample.hour_idx.max())
        stations = TREATED | set(
            SENSITIVITY_CONTROL_STATIONS if key == "core_controls" else CONTROL_STATIONS
        )
        checks = validate_sample(sample, trial, stations)
        result = run_plan(trial, sample)[0].to_dict()
        summary = summarise(
            key, label, result, trial.estimator.alpha, trial.thresholds.pretrend_alpha
        )
        records.append(
            {
                "summary": summary,
                "selection": {
                    "stations": sorted(stations),
                    "rows_24h": len(sample),
                    "first_hour_idx": int(sample.hour_idx.min()),
                    "last_hour_idx": int(sample.hour_idx.max()),
                    "uses_main_complete_hour_sample": True,
                    "time_reindexed": False,
                },
                "quality": checks,
                "result": result,
            }
        )
        print(f"[sensitivity] {label}: 완료, 추정치 {summary['estimate']:.6f}", flush=True)
    output = HERE / "results" / "sensitivity.json"
    run_meta["finished_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    output.parent.mkdir(exist_ok=True)
    output.write_text(
        json.dumps(
            clean_json({"manifest": run_meta, "analyses": records}),
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    )
    (HERE / "sensitivity.md").write_text(render_markdown(clean_json(records)))
    print("[sensitivity] results/sensitivity.json · sensitivity.md 저장", flush=True)


if __name__ == "__main__":
    main()
