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
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    for ax, split in zip(axes, ("pre_test", "post_test"), strict=True):
        for horizon, marker in ((1, "o"), (3, "s")):
            part = metrics[(metrics.split == split) & (metrics.group == "all") & (metrics.horizon == horizon)].set_index("model")
            order = sorted(models)
            ax.plot(range(len(order)), part.reindex(order).mae_mean, marker=marker, label=f"{horizon}h")
        ax.set_xticks(range(len(order)), order, rotation=65, ha="right")
        ax.set_title(split)
        ax.set_ylabel("MAE (km/h), lower is better")
        ax.grid(alpha=0.2)
        ax.legend()
    fig.suptitle("Exploratory fixed-budget comparison; Chronos2 uses external pretraining")
    fig.tight_layout()
    fig.savefig(out / "forecast_mae.png", dpi=160)
    plt.close(fig)
    checkpoints = {str(p.relative_to(root)): sha256(p) for p in sorted(root.rglob("*"))
                   if p.suffix in {".pt", ".cbm"}}
    write_json(out / "reproduction.json", {"run": args.run, "generated_at": utcnow(), "registration": registration,
        "code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=CASE, text=True).strip(),
        "source_manifest_sha256": sha256(CASE / "source-manifest.json"),
        "environment_lock_sha256": sha256(CASE / "requirements-gpu.lock"),
        "dataset_identity": audit["dataset_identity"], "checkpoint_hashes": checkpoints,
        "graph": read(CASE / "data/graph/edges.source.json"),
        "note": "원본·가공 행·개별 예측·가중치는 로컬 보관. 공개 산출물은 집계·자체 그림·실행 근거"})
    print(metrics[(metrics.group == "all") & (metrics.horizon == 1)][["split", "model", "mae_mean", "mae_seed_std"]].to_string(index=False))
    print(f"공개 집계 생성: {out}")


if __name__ == "__main__":
    main()
