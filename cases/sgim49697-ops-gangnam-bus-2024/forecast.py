"""학습·평가·모델 비교를 분리해서 실행하는 개인 사례 CLI."""

from __future__ import annotations

import argparse
import json
import re
import time

import pandas as pd
from gangnam.common import CASE, holiday_dates, read_yaml, real_data_gate, utcnow, write_json
from gangnam.models import BASELINES, GRAPH_MODELS, REGISTRY, predict_model, train_model
from gangnam.topis import read_hourly
from gangnam.windows import assert_common_keys, prediction_frame, prepare, score


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["train", "evaluate", "compare"])
    p.add_argument("--run", required=True, help="실험 폴더 이름. 설정 변경·재학습 시 새 이름 사용")
    p.add_argument("--models", nargs="+", default=["all"])
    p.add_argument("--split", choices=["validation", "pre_test", "transition", "post_test"], default="pre_test")
    p.add_argument("--graph", help="역사적 연결 CSV와 같은 이름의 .source.json 필요")
    args = p.parse_args()
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", args.run):
        p.error("--run은 영문·숫자·밑줄·하이픈만 사용합니다")
    names = list(REGISTRY) if args.models == ["all"] else args.models
    if not names or len(names) != len(set(names)) or set(names) - set(REGISTRY):
        p.error("알 수 없거나 중복된 모델: " + ", ".join(names))
    registration = real_data_gate()
    cfg = read_yaml("ml_config.yaml")
    data = prepare(read_hourly(CASE / "data/processed", verify=True), cfg)
    days = holiday_dates(cfg["splits"]["train"][0], cfg["splits"]["post_test"][1])
    root = CASE / "runs" / args.run
    root.mkdir(parents=True, exist_ok=True)
    adjacency, evidence = None, None
    if args.graph:
        from gangnam.graph import load_graph
        adjacency, evidence = load_graph(args.graph, data.links, read_yaml("data_contract.yaml"), cfg)
    if args.action == "train":
        for name in names:
            if name in GRAPH_MODELS and adjacency is None:
                write_json(root / f"blocked-{name}.json", {"status": "blocked", "reason": "검증된 역사적 그래프가 필요합니다"})
                print(f"{name}: 역사적 그래프 미확보로 보류", flush=True)
                continue
            train_model(name, data, root, days, registration, adjacency, evidence)
            print(f"{name}: 검증 구간으로 설정 선택 및 저장 완료", flush=True)
        return
    keys = data.keys(args.split)
    if not len(keys):
        raise ValueError("평가 가능한 공통 창이 없습니다")
    reference = prediction_frame(data, keys, data.targets(keys), "canonical", 0, args.split)
    evaluated, all_scores = 0, []
    for name in names:
        folder = root / name
        if (root / f"blocked-{name}.json").exists() and not folder.exists():
            print(f"{name}: 학습 보류 상태", flush=True)
            continue
        info = json.loads((folder / "selection.json").read_text(encoding="utf-8"))
        if info["registration"]["hashes"] != registration["hashes"]:
            raise ValueError("저장된 학습 설정과 현재 사전 등록 설정이 다릅니다")
        if info["dataset_identity"] != data.dataset_identity or info["prepared_identity"] != data.identity:
            raise ValueError("저장된 학습·평가 자료와 현재 자료가 다릅니다")
        if name in GRAPH_MODELS and (adjacency is None or evidence != info["graph_evidence"]):
            raise ValueError("학습 당시의 검증된 그래프가 필요합니다")
        for seed in info["seeds"]:
            output = folder / f"{args.split}-seed-{seed}.parquet"
            if args.action == "evaluate":
                if output.exists():
                    raise ValueError(f"기존 평가를 덮어쓰지 않습니다. compare로 비교하세요: {output}")
                started = time.perf_counter()
                resources = {}
                gpu = name not in BASELINES | {"catboost"} and cfg["training"]["device"] == "cuda"
                if gpu:
                    import torch
                    torch.cuda.init()
                    torch.cuda.reset_peak_memory_stats()
                pred = predict_model(name, data, keys, folder, seed, days, adjacency, resources)
                if gpu:
                    torch.cuda.synchronize()
                elapsed = time.perf_counter() - started
                resources["peak_vram_bytes"] = torch.cuda.max_memory_allocated() if gpu else 0
                frame = prediction_frame(data, keys, pred, name, seed, args.split)
                scores = score(frame, cfg["required_links"])
                frame.to_parquet(output, index=False)
                write_json(output.with_suffix(".json"), {"model": name, "seed": seed, "split": args.split,
                    "group": info["group"], "scores": scores, "evaluated_at": utcnow(),
                    "prediction_seconds_including_load": elapsed, "windows": len(keys), "resources": resources})
            frame = pd.read_parquet(output)
            assert_common_keys([reference, frame])
            evaluated += 1
            for item in score(frame, cfg["required_links"]):
                all_scores.append({"model": name, "seed": seed, "training_group": info["group"], **item})
    if not evaluated:
        raise ValueError("비교 가능한 모델 결과가 없습니다")
    scores = pd.DataFrame(all_scores)
    summary = []
    for (name, group, horizon), part in scores.groupby(["model", "group", "horizon"]):
        summary.append({"model": name, "group": group, "horizon": int(horizon),
                        "training_group": part.training_group.iloc[0], "seeds": len(part),
                        "mae_mean": float(part.mae.mean()),
                        "mae_seed_std": float(part.mae.std(ddof=1)) if len(part) > 1 else None,
                        "rmse_mean": float(part.rmse.mean())})
    write_json(root / f"comparison-{args.split}.json", {"split": args.split, "common_keys": len(reference),
        "results": summary, "note": "Chronos2의 외부 사전학습 자료와 평가기간 중첩은 확인되지 않았음. 별도 비교군으로 해석"})
    main_rows = scores[(scores.group == "all") & (scores.horizon == 1)]
    print(main_rows[["model", "seed", "mae", "rmse"]].to_string(index=False))


if __name__ == "__main__":
    main()
