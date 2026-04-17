from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

import torch

from .config import DEFAULT_MODEL_PATH, FEATURE_KEYS
from .features import record_to_model_parts
from .model import ResidualActionMLP


class ResidualActionPredictor:
    def __init__(self, model_path: Optional[str | Path] = None) -> None:
        self.model_path = Path(model_path) if model_path else DEFAULT_MODEL_PATH
        self._model = None
        self._metadata = None

    def _load(self):
        if self._model is not None:
            return self._model


        if not self.model_path.exists():
            self._model = None
            self._metadata = None
            return None

        checkpoint = torch.load(self.model_path, map_location="cpu")
        self._metadata = checkpoint

        model = ResidualActionMLP(
            num_feature_inputs=len(checkpoint.get("feature_keys", FEATURE_KEYS)),
            num_family_embeddings=len(checkpoint.get("action_family_to_index", {"Weapon": 0, "Spell": 1, "MonAction": 2})),
            family_embedding_dim=4,
            num_name_buckets=int(checkpoint.get("num_action_name_buckets", 1024)),
            name_embedding_dim=16,
            hidden_dims=tuple(checkpoint.get("hidden_dims", [128, 64])),
            max_delta=float(checkpoint.get("max_delta", 5.0)),
        )
        model.load_state_dict(checkpoint["model_state_dict"])
        model.eval()
        self._model = model

        return self._model

    def predict_delta(self, record: Dict[str, Any]) -> float:
        model = self._load()
        if model is None:
            return 0.0

        family_idx, name_bucket, features, base_weight, _action_name = record_to_model_parts(record)

        with torch.no_grad():
            delta = model(
                torch.tensor(family_idx, dtype=torch.long),
                torch.tensor(name_bucket, dtype=torch.long),
                features,
            )

        delta_value = float(delta.item())
        return delta_value

    def predict_final_weight(self, record: Dict[str, Any]) -> float:
        base_weight = float(record.get("base_weight", 0.0))
        final_weight = base_weight + self.predict_delta(record)
        return final_weight


@lru_cache(maxsize=1)
def get_predictor(model_path: Optional[str | Path] = None) -> ResidualActionPredictor:
    return ResidualActionPredictor(model_path=model_path)


def predict_final_weight(record: Dict[str, Any], model_path: Optional[str | Path] = None) -> float:
    return get_predictor(model_path).predict_final_weight(record)