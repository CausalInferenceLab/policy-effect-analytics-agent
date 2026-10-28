"""검증된 역사적 연결표와 소규모 DCRNN·STGCN 구조를 제공한다."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn

from .common import require_checks, sha256


def load_graph(path, links, contract, cfg):
    require_checks(contract, "historical_graph")
    path = Path(path)
    evidence = json.loads(path.with_suffix(".source.json").read_text(encoding="utf-8"))
    if not evidence.get("verified") or not evidence.get("source") or evidence["sha256"] != sha256(path):
        raise ValueError("도로 연결표의 근거·해시 검증 실패")
    if (pd.Timestamp(evidence["valid_from"]) > pd.Timestamp(cfg["splits"]["train"][0])
            or pd.Timestamp(evidence["valid_to"]) < pd.Timestamp(cfg["splits"]["post_test"][1])):
        raise ValueError("학습·평가 전체 기간의 도로 연결 유효성이 필요합니다")
    if not set(links) <= set(evidence["node_ids"]):
        raise ValueError("선택 링크 일부가 검증된 노드 목록에 없습니다")
    frame = pd.read_csv(path, dtype={"source_link": str, "target_link": str})
    if frame.duplicated(["source_link", "target_link"]).any():
        raise ValueError("연결표 중복")
    if not np.isfinite(frame.weight).all() or (frame.weight <= 0).any():
        raise ValueError("그래프 가중치는 유한한 양수여야 합니다")
    ids = {link: i for i, link in enumerate(links)}
    a = np.zeros((len(links), len(links)), dtype="float32")
    for row in frame.itertuples():
        if row.source_link in ids and row.target_link in ids:
            a[ids[row.source_link], ids[row.target_link]] = row.weight
    if not np.count_nonzero(a):
        raise ValueError("선택 링크 사이에 검증된 연결이 없습니다")
    return a, evidence


def transition(a):
    a = torch.as_tensor(a, dtype=torch.float32)
    rows = a.sum(dim=1, keepdim=True)
    return a / rows.clamp_min(1e-12)


class Diffusion(nn.Module):
    def __init__(self, inputs, outputs, a, steps=2):
        super().__init__()
        self.register_buffer("forward_walk", transition(a))
        self.register_buffer("backward_walk", transition(np.asarray(a).T.copy()))
        self.steps = steps
        self.linear = nn.Linear(inputs * (1 + 2 * steps), outputs)

    def forward(self, x):
        terms = [x]
        for a in (self.forward_walk, self.backward_walk):
            term = x
            for _ in range(self.steps):
                term = torch.einsum("nm,bmf->bnf", a, term)
                terms.append(term)
        return self.linear(torch.cat(terms, dim=-1))


class DiffusionGRU(nn.Module):
    def __init__(self, inputs, hidden, a, steps):
        super().__init__()
        self.gates = Diffusion(inputs + hidden, 2 * hidden, a, steps)
        self.candidate = Diffusion(inputs + hidden, hidden, a, steps)

    def forward(self, x, state):
        reset, update = torch.sigmoid(self.gates(torch.cat([x, state], -1))).chunk(2, -1)
        candidate = torch.tanh(self.candidate(torch.cat([x, reset * state], -1)))
        return update * state + (1 - update) * candidate


class DCRNN(nn.Module):
    """확산 GRU 2층 encoder/decoder. 출력은 자기회귀, 정답 teacher forcing 없음."""
    def __init__(self, a, hidden_size=32, recurrent_layers=2, diffusion_steps=2):
        super().__init__()
        self.hidden, self.nodes = hidden_size, len(a)
        self.encoder = nn.ModuleList([DiffusionGRU(2 if i == 0 else hidden_size, hidden_size, a, diffusion_steps)
                                      for i in range(recurrent_layers)])
        self.decoder = nn.ModuleList([DiffusionGRU(1 if i == 0 else hidden_size, hidden_size, a, diffusion_steps)
                                      for i in range(recurrent_layers)])
        self.projection = nn.Linear(hidden_size, 1)

    def forward(self, x):
        states = [x.new_zeros(x.shape[0], self.nodes, self.hidden) for _ in self.encoder]
        for step in x.unbind(dim=1):
            for layer, cell in enumerate(self.encoder):
                states[layer] = cell(step, states[layer])
                step = states[layer]
        predictions, step = [], x[:, -1, :, :1]
        for _ in range(3):
            for layer, cell in enumerate(self.decoder):
                states[layer] = cell(step, states[layer])
                step = states[layer]
            step = self.projection(step)
            predictions.append(step.squeeze(-1))
        return torch.stack(predictions, dim=1)


class TemporalGLU(nn.Module):
    def __init__(self, channels, hidden, kernel):
        super().__init__()
        self.conv = nn.Conv2d(channels, 2 * hidden, (kernel, 1))
        self.residual = nn.Conv2d(channels, hidden, 1)
        self.kernel = kernel

    def forward(self, x):
        value, gate = self.conv(x).chunk(2, dim=1)
        residual = self.residual(x[:, :, self.kernel - 1:])
        return (value + residual) * torch.sigmoid(gate)


class STBlock(nn.Module):
    def __init__(self, channels, hidden, support, kernel):
        super().__init__()
        self.first = TemporalGLU(channels, hidden, kernel)
        self.last = TemporalGLU(hidden, hidden, kernel)
        self.register_buffer("support", support)
        self.spatial = nn.Conv2d(3 * hidden, hidden, 1)
        self.norm = nn.LayerNorm(hidden)

    def forward(self, x):
        x = self.first(x)
        t1 = torch.einsum("nm,bctm->bctn", self.support, x)
        t2 = 2 * torch.einsum("nm,bctm->bctn", self.support, t1) - x
        x = self.last(torch.relu(self.spatial(torch.cat([x, t1, t2], dim=1))))
        return self.norm(x.permute(0, 2, 3, 1)).permute(0, 3, 1, 2)


class STGCN(nn.Module):
    """대칭화된 정규화 라플라시안의 Chebyshev K=3과 시간 GLU 2개 블록."""
    def __init__(self, a, hidden_size=32, blocks=2, temporal_kernel=3):
        super().__init__()
        a = np.maximum(a, a.T)
        degree = a.sum(axis=1)
        inv = np.divide(1, np.sqrt(degree), out=np.zeros_like(degree), where=degree > 0)
        # λmax=2 근사에서 L~=L-I=-D^-1/2 A D^-1/2. 고립 노드는 자기 항만 사용.
        support = torch.tensor(-inv[:, None] * a * inv[None, :], dtype=torch.float32)
        self.blocks = nn.Sequential(*[STBlock(2 if i == 0 else hidden_size, hidden_size, support, temporal_kernel)
                                      for i in range(blocks)])
        self.output = nn.Linear(hidden_size, 3)

    def forward(self, x):
        hidden = self.blocks(x.permute(0, 3, 1, 2))[:, :, -1, :].transpose(1, 2)
        return self.output(hidden).transpose(1, 2)
