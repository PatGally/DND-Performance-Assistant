from __future__ import annotations

from typing import Sequence

import torch
from torch import nn

from .config import FEATURE_KEYS, HIDDEN_DIMS, MAX_RESIDUAL_DELTA, NUM_ACTION_NAME_BUCKETS


class ResidualActionMLP(nn.Module):
    def __init__(
        self,
        num_feature_inputs: int = len(FEATURE_KEYS),
        num_family_embeddings: int = 3,
        family_embedding_dim: int = 4,
        num_name_buckets: int = NUM_ACTION_NAME_BUCKETS,
        name_embedding_dim: int = 16,
        hidden_dims: Sequence[int] = HIDDEN_DIMS,
        max_delta: float = MAX_RESIDUAL_DELTA,
    ) -> None:
        super().__init__()
        self.max_delta = float(max_delta)

        self.family_embedding = nn.Embedding(num_family_embeddings, family_embedding_dim)
        self.name_embedding = nn.Embedding(num_name_buckets, name_embedding_dim)

        layers = []
        in_dim = num_feature_inputs + family_embedding_dim + name_embedding_dim
        for hidden_dim in hidden_dims:
            layers.append(nn.Linear(in_dim, hidden_dim))
            layers.append(nn.ReLU())
            layers.append(nn.Dropout(p=0.15))
            in_dim = hidden_dim
        layers.append(nn.Linear(in_dim, 1))
        self.mlp = nn.Sequential(*layers)

    def forward(
        self,
        family_idx: torch.Tensor,
        name_bucket: torch.Tensor,
        numeric_features: torch.Tensor,
    ) -> torch.Tensor:
        if family_idx.ndim == 0:
            family_idx = family_idx.unsqueeze(0)
        if name_bucket.ndim == 0:
            name_bucket = name_bucket.unsqueeze(0)
        if numeric_features.ndim == 1:
            numeric_features = numeric_features.unsqueeze(0)

        family_vec = self.family_embedding(family_idx.long())
        name_vec = self.name_embedding(name_bucket.long())
        x = torch.cat([family_vec, name_vec, numeric_features.float()], dim=-1)
        raw_delta = self.mlp(x).squeeze(-1)
        return torch.tanh(raw_delta) * self.max_delta

    def predict_delta(
        self,
        family_idx: torch.Tensor,
        name_bucket: torch.Tensor,
        numeric_features: torch.Tensor,
    ) -> torch.Tensor:
        self.eval()
        with torch.no_grad():
            return self.forward(family_idx, name_bucket, numeric_features)

    def predict_final_weight(
        self,
        family_idx: torch.Tensor,
        name_bucket: torch.Tensor,
        numeric_features: torch.Tensor,
        base_weight: torch.Tensor,
    ) -> torch.Tensor:
        delta = self.predict_delta(family_idx, name_bucket, numeric_features)
        return base_weight.float() + delta
