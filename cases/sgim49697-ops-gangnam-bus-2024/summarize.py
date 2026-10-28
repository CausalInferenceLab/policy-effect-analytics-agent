"""검증된 공통 평가 결과에서 공개할 집계표·그림·재현 정보를 생성한다."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess

import pandas as pd
from gangnam.common import CASE, real_data_gate, sha256, utcnow, write_json
from gangnam.models import REGISTRY


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    root = CASE / "runs" / args.run
    if root.resolve().parent != (CASE / "runs").resolve():
        parser.error("실험 이름은 runs의 직접 하위 폴더여야 합니다")
    registration = real_data_gate()
    out = CASE / "results"
    out.mkdir(exist_ok=True)
    rows, resources, models = [], [], {}
    for split in ("pre_test", "transition", "post_test"):
        item = read(root / f"comparison-{split}.json")
        rows.extend({"split": split, **r} for r in item["results"] if r["group"] in {"all", "gangnam", "evening"})
    for path in sorted(root.glob("*/selection.json")):
        selected = read(path)
        if selected["registration"]["hashes"] != registration["hashes"]:
            raise ValueError("집계 대상 학습 설정이 현재 설정과 다릅니다")
        models[selected["model"]] = {k: selected[k] for k in ("params", "seeds", "group", "trials")}
        models[selected["model"]]["final_stats"] = selected.get("final_stats", {})
        models[selected["model"]]["source_hashes"] = selected.get("source_hashes", {})
        for metric in path.parent.glob("*-seed-*.json"):
            value = read(metric)
            resources.append({k: value[k] for k in ("model", "seed", "split", "windows", "prediction_seconds_including_load", "resources")})
    metrics = pd.DataFrame(rows).sort_values(["split", "group", "horizon", "mae_mean"])
    if set(models) != set(REGISTRY):
        raise ValueError("아홉 모델의 학습·추론 설정이 모두 필요합니다")
    expected = {(s, m, g, h) for s in ("pre_test", "transition", "post_test") for m in models
                for g in ("all", "gangnam", "evening") for h in (1, 3)}
    if set(zip(metrics.split, metrics.model, metrics.group, metrics.horizon, strict=True)) != expected:
        raise ValueError("일부 모델·기간·평가 집단의 비교 결과가 누락되었습니다")
    metrics.to_csv(out / "forecast_metrics.csv", index=False, float_format="%.6f")
    audit = read(CASE / "data/audit.json")
    policy = read(CASE / "runs/policy/diagnostics.json")
    write_json(out / "data_quality.json", audit)
    write_json(out / "policy_diagnostics.json", policy)
    write_json(out / "training_summary.json", models)
    write_json(out / "prediction_resources.json", resources)
    shutil.copyfile(CASE / "runs/policy/descriptive.csv", out / "policy_summary.csv")
    shutil.copyfile(CASE / "runs/policy/daily_speed.png", out / "policy_daily_speed.png")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(12, 6), sharey=True, sharex=True)
    for ax, split in zip(axes, ("pre_test", "post_test"), strict=True):
        for horizon, offset in ((1, -0.18), (3, 0.18)):
            part = metrics[(metrics.split == split) & (metrics.group == "all") & (metrics.horizon == horizon)].set_index("model")
            order = sorted(models)
            selected = part.reindex(order)
            ax.barh([i + offset for i in range(len(order))], selected.mae_mean, height=0.34,
                    xerr=selected.mae_seed_std.fillna(0), capsize=2, label=f"{horizon}h")
        ax.set_yticks(range(len(order)), order)
        ax.set_title(split)
        ax.set_xlabel("MAE (km/h), lower is better")
        ax.grid(axis="x", alpha=0.2)
        ax.legend()
    axes[0].invert_yaxis()
    fig.suptitle("Exploratory fixed-budget comparison\nChronos2 uses external pretraining; error bars show seed SD", fontsize=11)
    fig.tight_layout()
    fig.savefig(out / "forecast_mae.png", dpi=160)
    plt.close(fig)
    checkpoints = {str(p.relative_to(root)): sha256(p) for p in sorted(root.rglob("*"))
                   if p.suffix in {".pt", ".cbm"}}
    write_json(out / "reproduction.json", {"run": args.run, "generated_at": utcnow(), "registration": registration,
        "code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=CASE, text=True).strip(),
        "source_manifest_sha256": sha256(CASE / "source-manifest.json"),
        "environment_lock_sha256": sha256(CASE / "requirements-gpu.lock"),
        "report_generator_sha256": sha256(CASE / "summarize.py"),
        "analysis_source_hashes": {name: sha256(CASE / name) for name in
            ("fetch.py", "estimate.py", "audit.py", "gangnam/topis.py", "gangnam/policy.py")},
        "dataset_identity": audit["dataset_identity"], "checkpoint_hashes": checkpoints,
        "graph": read(CASE / "data/graph/edges.source.json"),
        "note": "원본·가공 행·개별 예측·가중치는 로컬 보관. 공개 산출물은 집계·자체 그림·실행 근거"})
    make_report(metrics, models, audit, policy, args.run)
    print(metrics[(metrics.group == "all") & (metrics.horizon == 1)][["split", "model", "mae_mean", "mae_seed_std"]].to_string(index=False))
    print(f"공개 집계 생성: {out}")


def make_report(metrics, models, audit, policy, run):
    def table(headers, rows):
        return "\n".join(["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |",
                          *["| " + " | ".join(map(str, row)) + " |" for row in rows]])

    values = metrics.set_index(["split", "model", "group", "horizon"])
    overview, core = [], []
    for name in REGISTRY:
        numbers = [f"{values.loc[(s, name, 'all', h), 'mae_mean']:.3f}" for s in ("pre_test", "post_test") for h in (1, 3)]
        overview.append([name + (" †" if name == "chronos2" else ""), *numbers])
        core.append([name, *[f"{values.loc[(s, name, 'gangnam', 1), 'mae_mean']:.3f}" for s in ("pre_test", "transition", "post_test")]])
    description = pd.read_csv(CASE / "results/policy_summary.csv")
    means = description.pivot(index="corridor_id", columns="period", values="mean")
    policies = [[name, f"{r.pre:.3f}", f"{r.post:.3f}", f"{r.post-r.pre:+.3f}"] for name, r in means.iterrows()]
    sensitivity = [[name, f"{r['did_kmh']:+.3f}" if r["status"] == "ok" else "미실행: " + r["reason"]]
                   for name, r in policy["sensitivities"].items()]
    costs = []
    for name, selected in models.items():
        trials, final = selected["trials"], selected["final_stats"]
        seconds = sum(t["seconds"] for t in trials) + sum(s["seconds"] for seed, s in final.items() if seed != "17")
        stats = list(final.values())
        peak = max([s.get("peak_vram_bytes", 0) for s in [*trials, *stats]], default=0) / 1024**3
        costs.append([name, len(selected["seeds"]), f"{seconds:.1f}", f"{peak:.2f}", selected["params"]])
    graph = read(CASE / "data/graph/edges.source.json")
    gangnam_change = means.loc["gangnam", "post"] - means.loc["gangnam", "pre"]
    bad = audit["invalid_reasons"]
    text = f"""# 강남대로 버스 정책 전후 비교와 단기 예측 결과

2026-10-28 실자료 실행 `{run}`. **탐색 분석이며 정책 인과효과는 판단 불가(`not_identified`)다.**

## 자료와 실행 조건

[TOPIS 월별 차량 통행속도](https://topis.seoul.go.kr/refRoom/openRefRoom_1.do)의 2023-01~2024-08, 20개월을 수집했다. 네 도로의 94개 링크 중 시종점 변경 4개를 제외했고, train 관측률 기준을 통과한 {len(audit['selected_links'])}개를 사용했다. {audit['rows']:,}개 시간별 관측의 유효율은 {audit['valid_fraction']:.4%}다. 빈칸 {bad.get('blank', 0):,}개, 문자열 결측 표기 {bad.get('sentinel', 0):,}개, 0값 {bad.get('zero', 0):,}개, 음수 {bad.get('negative', 0):,}개를 기록했다. 2024-08-02~03 누락 때문에 post_test 평가 창이 줄었으며, 모든 모델에 같은 창을 적용했다.

공휴일은 공식 역서와 대조했다. 시간 열을 종료시각으로, 단위를 km/h로 해석하는 가정은 공식 월별 정의 확인과 구분한다. 차선 수 변경을 허용했고 측정 환경의 불변성을 입증하지 않았다. {len(graph['node_ids'])}개 노드·{graph['edges']}개 방향 연결은 시종점명으로 만든 그래프이며, 역사적 지도나 실제 회전 가능성의 검증 결과가 아니다.

## 정책 전후 비교

정책일은 [서울시 안내](https://mediahub.seoul.go.kr/archives/2011484)에 따른 2024-06-29, 전 기간은 05-20~06-28, 후 기간은 07-08~08-16이다. 평일·비공휴일 17~20시의 고정 길이가중 속도지수를 비교했다. 모든 도로에서 동일한 전 {policy['quality']['common_days']['pre']}일·후 {policy['quality']['common_days']['post']}일을 확보했다. 단위는 km/h다.

{table(['도로', '전 평균', '후 평균', '단순 변화'], policies)}

강남대로 자체 속도의 변화는 {gangnam_change:+.3f} km/h다. 비교 도로 평균의 하락 폭이 더 커서 이중차분은 **{policy['did_kmh']:+.3f} km/h**다. 이를 '강남대로 속도가 0.94 km/h 빨라졌다'로 읽으면 안 된다. 통상적인 버스 통행시간·승객 시간 절감도 측정하지 않았다.

![도로별 일별 속도](results/policy_daily_speed.png)

점선은 정책일, 회색 구간은 주 분석에서 제외한 전환 기간이다. 오른쪽은 각 도로의 전 기간 평균을 뺀 값이며 인과효과 추정 곡선이 아니다.

{table(['민감도', '상대 변화(km/h)'], sensitivity)}

가짜 정책일 2024-06-10의 상대 변화는 {policy['placebo_kmh']:+.3f} km/h다. 비교 도로 한 곳씩 제외한 값은 {min(policy['leave_one_control_out_kmh'].values()):+.3f}~{max(policy['leave_one_control_out_kmh'].values()):+.3f} km/h다. 시간 창과 양재역 연장에 따라 크기가 달라진다. 한 처치 도로와 세 후보 비교 도로만으로 동시 정책·장마·우회 노출을 배제할 수 없으므로 유의확률이나 인과 신뢰구간을 제시하지 않는다.

## 예측 비교

train은 2023-01~2024-03, validation은 2024-04다. 평가 시각마다 그때까지 관측된 최신 168시간으로 다음 1·3시간을 예측하며 모델 가중치는 다시 학습하지 않는다. 정답은 보간하지 않는다. 과거 입력은 최대 3시간 전방 채움 후 train의 요일·시간 평균을 사용하고, 평균·표준편차·링크 선택·CatBoost 표본은 train만으로 정한다. 5개 학습 모델은 검증 구간으로 설정을 고른 뒤 seed 17·42·2026으로 학습했다. 단순 기준선과 Chronos2는 한 번 평가했다.

정책 전 시험은 05-01~06-16({audit['splits']['pre_test']['windows']:,}창), 전환기는 06-17~06-30({audit['splits']['transition']['windows']:,}창), 정책 후 시험은 07-01~08-31({audit['splits']['post_test']['windows']:,}창)이다. 정책 후 시험 기간은 정책 비교의 후 기간과 다르다. 아래 MAE는 작을수록 좋고, 학습 모델은 3개 seed 평균이다.

{table(['모델', '전 1h', '전 3h', '후 1h', '후 3h'], overview)}

† Chronos2는 고정 revision의 외부 사전학습 모델이다. 학습 자료와 2024년 평가 기간의 중첩 여부를 확인하지 못했으므로 같은 데이터로 처음부터 학습한 모델과 구분한다.

![예측 오차 비교](results/forecast_mae.png)

### 강남대로 핵심 세 링크의 1시간 MAE

{table(['모델', '정책 전', '전환기', '정책 후'], core)}

평균에 가려지는 seed 변동, 3시간·저녁 구간·RMSE는 [전체 집계표](results/forecast_metrics.csv)에 있다. 이 예측 성능은 정책의 반사실 효과를 추정한 값이 아니다.

## 계산 예산과 재현

단기 탐색 예산은 DLinear·PatchTST·STGCN 최대 1,000 step, DCRNN 300 step, CatBoost train 최대 20만 창·800회다. 검증 구간에서 가장 나은 체크포인트를 저장했다. 수렴 완료나 같은 계산량으로의 우열을 주장하지 않는다. 그래프 모델은 교육용 구현이며 원 논문의 성능 재현이 아니다.

{table(['모델', 'seed 수', '총 학습 초', '최대 할당 VRAM GiB', '선택 설정'], costs)}

학습 시간은 학습 루프·검증 기록으로, 자료 정규화와 라이브러리 초기화 시간은 제외한다. 후보 탐색과 추가 seed를 포함하되 seed 17의 선택 모델 복사를 중복 계산하지 않았다. 같은 GPU에서 신경망을 순서대로 실행했고 CPU CatBoost와 일부 시간은 겹쳤다. Chronos2의 0초는 로컬 재학습을 하지 않았다는 뜻이다. 모델 적재를 포함한 추론 시간·메모리는 [추론 자원 기록](results/prediction_resources.json)에 따로 있다. GPU 부동소수점 실행의 비트 단위 일치는 보장하지 않는다.

[README](README.md)의 수집→감사→정책 비교→학습→평가→집계 명령으로 재현한다. 개인 `estimate.py`를 사용하므로 공통 `make flow` 결과와 혼동하지 않는다. 설정·원본·환경·모델 가중치 해시는 [재현 기록](results/reproduction.json), 결측과 분할은 [품질 기록](results/data_quality.json), 선택 과정은 [학습 기록](results/training_summary.json)에 남겼다. 원본·가공 행·개별 예측·가중치는 Git에 포함하지 않는다.

자료 정의·사용 조건·정책 노출의 미확인 항목과 해석은 [discussion.md](discussion.md)를 함께 읽는다.
"""
    (CASE / "report.md").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
