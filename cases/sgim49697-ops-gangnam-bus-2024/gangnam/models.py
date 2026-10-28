"""아홉 예측 모델의 학습·저장·추론을 같은 시간 창으로 실행한다."""

from __future__ import annotations

import itertools
import json
import os
import random
import sysconfig
import time
from pathlib import Path

import numpy as np

from .common import utcnow, write_json
from .windows import baseline, features

BASELINES = {"last_value", "weekly_naive", "weekday_hour_mean"}
GRAPH_MODELS = {"dcrnn", "stgcn"}
NEURAL_MODELS = {"dlinear", "patchtst", *GRAPH_MODELS}
REGISTRY = (*sorted(BASELINES), "catboost", "dlinear", "patchtst", "chronos2", "dcrnn", "stgcn")


def candidates(name, cfg):
    spec = cfg["models"][name]
    keys = list(spec)
    return [dict(zip(keys, values, strict=True)) for values in itertools.product(
        *[v if isinstance(v, list) else [v] for v in spec.values()])]


def ensure_device(device):
    import torch
    if os.getenv("TORCH_DISABLE_NATIVE_JIT") == "1":
        raise ValueError("정식 실행에서는 native JIT 비활성화를 허용하지 않습니다")
    include = Path(sysconfig.get_path("include"))
    if not all((include / f).exists() for f in ("Python.h", "pyconfig.h")):
        raise ValueError("현재 Python에 맞는 Python.h·pyconfig.h가 필요합니다")
    if device == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA를 사용할 수 없습니다. 장비 호환성을 확인하세요")
    if device == "cuda" and torch.cuda.get_device_capability() == (12, 0):
        if torch.version.cuda != "13.0" or "sm_120" not in torch.cuda.get_arch_list():
            raise ValueError("이 장비의 검증된 cu130·sm_120 환경과 다릅니다")


def seed_all(seed):
    import torch
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def network(name, params, cfg, adjacency=None, seed=17):
    if name in GRAPH_MODELS:
        if adjacency is None:
            raise ValueError("역사적 연결성 검증 없는 그래프 모델 실행 금지")
        from .graph import DCRNN, STGCN
        return (DCRNN if name == "dcrnn" else STGCN)(adjacency, **params)
    from neuralforecast.models import DLinear, PatchTST
    cls = {"dlinear": DLinear, "patchtst": PatchTST}[name]
    # NeuralForecast의 네트워크만 사용하고 학습 창·마스크·scaler는 이 사례에서 관리한다.
    return cls(h=cfg["output_hours"], input_size=cfg["context_hours"], scaler_type="identity", random_seed=seed, **params)


def neural_forward(model, x, graph=False):
    return model(x) if graph else model({"insample_y": x.unsqueeze(-1)}).squeeze(-1)


def graph_batch(data, times, allowed):
    c = data.cfg["context_hours"]
    x, y, mask = [], [], []
    for i in times:
        past = (data.filled[i - c:i] - data.means) / data.scales
        x.append(np.stack([past, data.observed[i - c:i]], axis=-1))
        labels = (data.raw[i:i + 3] - data.means) / data.scales
        valid = np.zeros(len(data.links), dtype=bool)
        valid[allowed[int(i)]] = True
        mask.append(np.isfinite(labels) & valid[None, :])
        y.append(np.nan_to_num(labels))
    return np.asarray(x, dtype="float32"), np.asarray(y, dtype="float32"), np.asarray(mask)


def allowed_nodes(keys):
    allowed = {}
    for i, j in keys:
        allowed.setdefault(int(i), []).append(int(j))
    return allowed


def neural_predict(model, name, data, keys, device, batch_size):
    import torch
    model.eval()
    graph = name in GRAPH_MODELS
    output = np.empty((len(keys), 3), dtype="float32")
    with torch.inference_mode():
        if not graph:
            for offset in range(0, len(keys), batch_size):
                part = keys[offset:offset + batch_size]
                x, _, _ = data.batch(part)
                p = neural_forward(model, torch.as_tensor(x, device=device)).cpu().numpy()
                j = part[:, 1]
                output[offset:offset + len(part)] = p * data.scales[j, None] + data.means[j, None]
        else:
            allowed = allowed_nodes(keys)
            times = sorted(allowed)
            predictions = {}
            for offset in range(0, len(times), batch_size):
                part = times[offset:offset + batch_size]
                x, _, _ = graph_batch(data, part, allowed)
                p = model(torch.as_tensor(x, device=device)).cpu().numpy() * data.scales + data.means
                predictions.update(zip(part, p, strict=True))
            for row, (i, j) in enumerate(keys):
                output[row] = predictions[int(i)][:, j]
    return output


def train_neural(name, data, params, seed, folder, adjacency=None):
    import torch
    device = data.cfg["training"]["device"]
    ensure_device(device)
    train_keys, val_keys = data.keys("train"), data.keys("validation")
    if min(len(train_keys), len(val_keys)) == 0:
        raise ValueError("학습·검증 창이 부족합니다")
    batch_size = data.cfg["training"]["batch_size"]
    val_truth = data.targets(val_keys)[:, 0]
    settings = data.cfg["training"]
    max_steps = settings.get("model_max_steps", {}).get(name, settings["max_steps"])
    inference_batch = settings.get("graph_inference_batch_size" if name in GRAPH_MODELS else "inference_batch_size", batch_size)
    attempts = []
    while True:
        seed_all(seed)
        model = network(name, params, data.cfg, adjacency, seed).to(device)
        optimizer = torch.optim.Adam(model.parameters(), lr=data.cfg["training"]["learning_rate"])
        started, step, stale, best, state = time.perf_counter(), 0, 0, float("inf"), None
        if device == "cuda":
            torch.cuda.reset_peak_memory_stats()
        graph = name in GRAPH_MODELS
        allowed = allowed_nodes(train_keys) if graph else None
        samples = np.array(sorted(allowed)) if graph else np.arange(len(train_keys))
        settings = data.cfg["training"]
        try:
            stop = False
            epochs = 0
            for _ in range(settings["max_epochs"]):
                epochs += 1
                order = np.random.permutation(samples)
                for offset in range(0, len(order), batch_size):
                    model.train()
                    part = order[offset:offset + batch_size]
                    if graph:
                        x, y, mask = graph_batch(data, part, allowed)
                    else:
                        x, y, _ = data.batch(train_keys[part])
                        mask = np.isfinite(y)
                    tx, ty = torch.as_tensor(x, device=device), torch.as_tensor(y, device=device)
                    tm = torch.as_tensor(mask, device=device)
                    optimizer.zero_grad(set_to_none=True)
                    pred = neural_forward(model, tx, graph)
                    loss = torch.abs(pred - ty)[tm].mean()
                    if not torch.isfinite(loss):
                        raise ValueError("학습 손실이 비유한 값입니다")
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                    optimizer.step()
                    step += 1
                    last = offset + batch_size >= len(order) or step >= max_steps
                    if step % settings.get("validation_interval", 250) == 0 or last:
                        pred = neural_predict(model, name, data, val_keys, device, inference_batch)
                        metric = float(np.abs(pred[:, 0] - val_truth).mean())
                        print(f"{name} seed={seed} step={step} validation_mae_h1={metric:.4f}", flush=True)
                        if metric < best:
                            best, stale = metric, 0
                            state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
                        else:
                            stale += 1
                        if stale >= settings["early_stopping_patience"] or step >= max_steps:
                            stop = True
                            break
                if stop:
                    break
            if state is None:
                raise ValueError("유효한 검증 체크포인트가 없습니다")
            folder.mkdir(parents=True, exist_ok=True)
            torch.save(state, folder / "weights.pt")
            if device == "cuda":
                torch.cuda.synchronize()
            return {"validation_mae_h1": best, "steps": step, "epochs": epochs,
                    "batch_size": batch_size, "oom_retries": attempts, "seconds": time.perf_counter() - started,
                    "peak_vram_bytes": torch.cuda.max_memory_allocated() if device == "cuda" else 0,
                    "parameters": sum(p.numel() for p in model.parameters())}
        except torch.OutOfMemoryError:
            attempts.append({"batch_size": batch_size, "step": step})
            if batch_size == 1:
                raise
            batch_size = max(1, batch_size // 2)
            inference_batch = max(1, inference_batch // 2)
        finally:
            tx = ty = tm = pred = loss = state = None
            del optimizer, model
            if device == "cuda":
                torch.cuda.empty_cache()


def sampled_train_keys(data):
    keys = data.keys("train")
    settings = data.cfg["training"]
    limit = settings.get("catboost_max_train_windows", len(keys))
    if limit <= 0:
        raise ValueError("학습 창 상한은 양수여야 합니다")
    if len(keys) > limit:
        rng = np.random.default_rng(settings.get("sample_seed", settings["selection_seed"]))
        keys = keys[np.sort(rng.choice(len(keys), size=limit, replace=False))]
    return keys


def train_catboost(data, params, seed, folder, holiday_dates):
    from catboost import CatBoostRegressor
    train, valid = sampled_train_keys(data), data.keys("validation")
    if min(len(train), len(valid)) == 0:
        raise ValueError("학습·검증 창이 부족합니다")
    folder.mkdir(parents=True, exist_ok=True)
    started, best_score, trees = time.perf_counter(), None, {}
    for h in data.cfg["horizons"]:
        model = CatBoostRegressor(**params, random_seed=seed, task_type="CPU", thread_count=8,
                                 loss_function="MAE", eval_metric="MAE", allow_writing_files=False, verbose=False)
        model.fit(features(data, train, h, holiday_dates), data.targets(train)[:, h - 1], cat_features=["link_id"],
                  eval_set=(features(data, valid, h, holiday_dates), data.targets(valid)[:, h - 1]), use_best_model=True)
        model.save_model(str(folder / f"h{h}.cbm"))
        print(f"catboost seed={seed} horizon={h} trees={model.tree_count_} validation_mae={model.best_score_['validation']['MAE']:.4f}", flush=True)
        trees[str(h)] = model.tree_count_
        if h == 1:
            best_score = float(model.best_score_["validation"]["MAE"])
    return {"validation_mae_h1": best_score, "seconds": time.perf_counter() - started,
            "peak_vram_bytes": 0, "trees": trees, "training_windows": len(train)}


def train_model(name, data, root, holiday_dates, registration, adjacency=None, graph_evidence=None):
    import shutil
    folder = root / name
    if folder.exists():
        raise ValueError(f"기존 실행을 덮어쓰지 않습니다. 다른 --run을 사용하세요: {folder}")
    folder.mkdir(parents=True)
    common = {"model": name, "prepared_identity": data.identity, "dataset_identity": data.dataset_identity, "registration": registration,
              "links": data.links, "created_at": utcnow(), "graph_evidence": graph_evidence,
              "group": "external_pretraining" if name == "chronos2" else "local_history"}
    if name in BASELINES or name == "chronos2":
        write_json(folder / "selection.json", {**common, "params": data.cfg["models"][name], "seeds": [0], "trials": []})
        return
    train = train_catboost if name == "catboost" else train_neural
    trials, selection_seed = [], data.cfg["training"]["selection_seed"]
    for i, params in enumerate(candidates(name, data.cfg)):
        target = folder / f"trial-{i}"
        if name == "catboost":
            stats = train(data, params, selection_seed, target, holiday_dates)
        else:
            stats = train(name, data, params, selection_seed, target, adjacency)
        trial = {"id": i, "params": params, **stats}
        trials.append(trial)
        write_json(target / "metrics.json", trial)
    chosen = min(trials, key=lambda t: (t["validation_mae_h1"], t["id"]))
    final_stats = {}
    for seed in data.cfg["seeds"]:
        target = folder / f"seed-{seed}"
        if seed == selection_seed:
            shutil.copytree(folder / f"trial-{chosen['id']}", target)
            stats = {k: v for k, v in chosen.items() if k not in {"id", "params"}}
        elif name == "catboost":
            stats = train(data, chosen["params"], seed, target, holiday_dates)
        else:
            stats = train(name, data, chosen["params"], seed, target, adjacency)
        final_stats[str(seed)] = stats
    write_json(folder / "selection.json", {**common, "params": chosen["params"], "trials": trials,
                                           "seeds": data.cfg["seeds"], "final_stats": final_stats})


def predict_model(name, data, keys, folder, seed, holiday_dates, adjacency=None, telemetry=None):
    telemetry = telemetry if telemetry is not None else {}
    telemetry["oom_retries"] = []
    info = json.loads((folder / "selection.json").read_text(encoding="utf-8"))
    if (info["prepared_identity"] != data.identity or info["links"] != data.links
            or info["dataset_identity"] != data.dataset_identity):
        raise ValueError("학습 자료·전처리·분할·링크가 저장된 모델과 다릅니다")
    if seed not in info["seeds"]:
        raise ValueError("선택 모델의 seed가 아닙니다")
    if name in BASELINES:
        return baseline(name, data, keys)
    if name == "catboost":
        from catboost import CatBoostRegressor
        out = np.full((len(keys), 3), np.nan, dtype="float32")
        for h in data.cfg["horizons"]:
            model = CatBoostRegressor()
            model.load_model(str(folder / f"seed-{seed}/h{h}.cbm"))
            out[:, h - 1] = model.predict(features(data, keys, h, holiday_dates))
        return out
    import torch
    device = data.cfg["training"]["device"]
    ensure_device(device)
    if name == "chronos2":
        from chronos import Chronos2Pipeline
        spec = info["params"]
        pipeline = Chronos2Pipeline.from_pretrained(spec["model_id"], revision=spec["revision"], device_map=device)
        telemetry["parameters"] = sum(p.numel() for p in pipeline.model.parameters())
        batch_size, offset = data.cfg["training"].get("chronos_inference_batch_size", data.cfg["training"]["batch_size"]), 0
        out = np.empty((len(keys), 3), dtype="float32")
        while offset < len(keys):
            part = keys[offset:offset + batch_size]
            x, _, _ = data.batch(part, scaled=False)
            try:
                quantiles, _ = pipeline.predict_quantiles([row for row in x], prediction_length=3,
                    quantile_levels=[0.5], batch_size=batch_size, context_length=168, cross_learning=False)
                out[offset:offset + len(part)] = np.stack([q.cpu().numpy().reshape(3) for q in quantiles])
                offset += len(part)
            except torch.OutOfMemoryError:
                telemetry["oom_retries"].append({"batch_size": batch_size, "offset": offset})
                if batch_size == 1:
                    raise
                batch_size = max(1, batch_size // 2)
                torch.cuda.empty_cache()
        telemetry["batch_size"] = batch_size
        return out
    model = network(name, info["params"], data.cfg, adjacency).to(device)
    model.load_state_dict(torch.load(folder / f"seed-{seed}/weights.pt", map_location=device, weights_only=True))
    telemetry["parameters"] = sum(p.numel() for p in model.parameters())
    batch_size = data.cfg["training"].get("graph_inference_batch_size" if name in GRAPH_MODELS else "inference_batch_size",
                                         info["final_stats"][str(seed)]["batch_size"])
    while True:
        try:
            out = neural_predict(model, name, data, keys, device, batch_size)
            telemetry["batch_size"] = batch_size
            return out
        except torch.OutOfMemoryError:
            telemetry["oom_retries"].append({"batch_size": batch_size})
            if batch_size == 1:
                raise
            batch_size = max(1, batch_size // 2)
            torch.cuda.empty_cache()
