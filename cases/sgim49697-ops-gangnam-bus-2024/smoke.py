"""실자료를 읽지 않고 합성 시계열로 CPU·GPU 모델의 학습·저장·추론을 점검한다."""

from __future__ import annotations

import argparse
import copy
import platform
import sys
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version

import numpy as np
import pandas as pd
from gangnam.common import CASE, read_yaml, write_json
from gangnam.models import (
    BASELINES,
    GRAPH_MODELS,
    REGISTRY,
    candidates,
    ensure_device,
    predict_model,
    train_catboost,
    train_neural,
)
from gangnam.windows import baseline, prediction_frame, prepare


def synthetic():
    cfg = copy.deepcopy(read_yaml("ml_config.yaml"))
    cfg["splits"] = {"train": ["2023-01-01", "2023-01-14"],
        "validation": ["2023-01-15", "2023-01-16"], "pre_test": ["2023-01-17", "2023-01-18"],
        "transition": ["2023-01-19", "2023-01-19"], "post_test": ["2023-01-20", "2023-01-21"]}
    cfg["training"]["max_steps"] = 100
    times = pd.date_range("2023-01-01", "2023-01-21 23:00", freq="h", tz="Asia/Seoul")
    rng = np.random.default_rng(17)
    rows = [(link, t, 30 + j * 4 + 5 * np.sin(i / 12) + rng.normal(0, 0.2), True, "")
            for j, link in enumerate(cfg["required_links"]) for i, t in enumerate(times)]
    frame = pd.DataFrame(rows, columns=["link_id", "interval_start_kst", "speed_kmh", "is_valid", "invalid_reason"])
    return prepare(frame, cfg)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--models", nargs="+", choices=REGISTRY, default=list(REGISTRY))
    p.add_argument("--device", choices=["cpu", "cuda"], default="cuda")
    args = p.parse_args()
    data = synthetic()
    data.cfg["training"]["device"] = args.device
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    root = CASE / "runs" / f"synthetic-smoke-{stamp}"
    root.mkdir(parents=True)
    report = {"synthetic": True, "python": sys.executable, "os": platform.platform(), "models": {}}
    if set(args.models) - BASELINES - {"catboost"}:
        import torch
        ensure_device(args.device)
        report["torch"] = torch.__version__
        report["cuda"] = torch.version.cuda
        if args.device == "cuda":
            a = torch.randn(128, 128, device="cuda", dtype=torch.bfloat16)
            assert torch.isfinite(a @ a).all()
            torch.cuda.synchronize()
            report.update({"gpu": torch.cuda.get_device_name(), "capability": list(torch.cuda.get_device_capability()),
                           "bf16_operation": "passed", "architectures": torch.cuda.get_arch_list()})
    report["packages"] = {}
    for name in ("numpy", "pandas", "catboost", "neuralforecast", "chronos-forecasting"):
        try:
            report["packages"][name] = version(name)
        except PackageNotFoundError:
            report["packages"][name] = "not_installed"
    graph = np.array([[0, 1, 0], [0, 0, 1], [0, 0, 0]], dtype="float32")
    keys = data.keys("pre_test")[:8]
    for name in args.models:
        print(f"{name}: 합성 입력 검증 시작", flush=True)
        params, stats, seed = candidates(name, data.cfg)[0], {}, 17
        folder = root / name
        folder.mkdir()
        if name in BASELINES:
            pred = baseline(name, data, keys)
        else:
            if name == "catboost":
                params.update(iterations=10, early_stopping_rounds=5)
                stats = train_catboost(data, params, seed, folder / "seed-17", set())
            elif name != "chronos2":
                steps = data.cfg["training"]["max_steps"]
                if name in GRAPH_MODELS:
                    data.cfg["training"]["max_steps"] = 2
                stats = train_neural(name, data, params, seed, folder / "seed-17", graph if name in GRAPH_MODELS else None)
                data.cfg["training"]["max_steps"] = steps
            if name == "chronos2":
                seed = 0
            write_json(folder / "selection.json", {"prepared_identity": data.identity, "dataset_identity": data.dataset_identity, "links": data.links,
                "params": params, "seeds": [seed], "final_stats": {str(seed): stats}, "synthetic": True})
            pred = predict_model(name, data, keys, folder, seed, set(), graph if name in GRAPH_MODELS else None)
        frame = prediction_frame(data, keys, pred, name, seed, "pre_test")
        if not np.isfinite(frame.y_pred).all():
            raise ValueError(f"{name}: 비유한 예측")
        report["models"][name] = {"status": "passed", "prediction_rows": len(frame), **stats}
        write_json(root / "smoke.json", report)
        print(f"{name}: 학습/추론 통과", flush=True)
    print(f"합성 검증 기록: {root / 'smoke.json'}")


if __name__ == "__main__":
    main()
