from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Sequence

import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset, random_split

from .config import (
    ACTION_FAMILY_TO_INDEX,
    BATCH_SIZE,
    DEFAULT_MODEL_PATH,
    EARLY_STOPPING_PATIENCE,
    EPOCHS,
    FEATURE_KEYS,
    HIDDEN_DIMS,
    LEARNING_RATE,
    MAX_RESIDUAL_DELTA,
    NUM_ACTION_NAME_BUCKETS,
    WEIGHT_DECAY,
)
from .features import record_has_label, record_to_model_parts
from .model import ResidualActionMLP


class ActionWeightDataset(Dataset):
    def __init__(self, records: Sequence[Dict[str, Any]]) -> None:
        labeled = [r for r in records if record_has_label(r)]
        if not labeled:
            raise ValueError("No labeled records were provided.")
        self.records = labeled

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, idx: int):
        record = self.records[idx]
        family_idx, name_bucket, features, base_weight, _action_name = record_to_model_parts(record)
        label = float(record["label"])
        residual_target = label - base_weight
        return (
            torch.tensor(family_idx, dtype=torch.long),
            torch.tensor(name_bucket, dtype=torch.long),
            features,
            torch.tensor(base_weight, dtype=torch.float32),
            torch.tensor(residual_target, dtype=torch.float32),
        )


def _collate(batch):
    family_idx = torch.stack([item[0] for item in batch], dim=0)
    name_bucket = torch.stack([item[1] for item in batch], dim=0)
    numeric = torch.stack([item[2] for item in batch], dim=0)
    base_weight = torch.stack([item[3] for item in batch], dim=0)
    residual_target = torch.stack([item[4] for item in batch], dim=0)
    return family_idx, name_bucket, numeric, base_weight, residual_target


@dataclass
class TrainResult:
    trained: bool
    model_path: str
    num_records: int
    train_loss: float | None = None
    val_loss: float | None = None
    reason: str | None = None


def build_model() -> ResidualActionMLP:
    return ResidualActionMLP(
        num_feature_inputs=len(FEATURE_KEYS),
        num_family_embeddings=max(ACTION_FAMILY_TO_INDEX.values()) + 1,
        family_embedding_dim=4,
        num_name_buckets=NUM_ACTION_NAME_BUCKETS,
        name_embedding_dim=16,
        hidden_dims=HIDDEN_DIMS,
        max_delta=MAX_RESIDUAL_DELTA,
    )


def train_residual_model(
    records: Sequence[Dict[str, Any]],
    output_path: Path | str = DEFAULT_MODEL_PATH,
    *,
    epochs: int = EPOCHS,
    batch_size: int = BATCH_SIZE,
    learning_rate: float = LEARNING_RATE,
    weight_decay: float = WEIGHT_DECAY,
    val_split: float = 0.2,
    seed: int = 1337,
    min_records: int = 10,
) -> TrainResult:
    labeled = [r for r in records if record_has_label(r)]
    if len(labeled) < min_records:
        return TrainResult(
            trained=False,
            model_path=str(output_path),
            num_records=len(labeled),
            reason=f"Need at least {min_records} labeled records.",
        )

    dataset = ActionWeightDataset(labeled)
    val_size = max(1, int(len(dataset) * val_split))
    train_size = max(1, len(dataset) - val_size)
    if train_size + val_size > len(dataset):
        val_size = len(dataset) - train_size

    generator = torch.Generator().manual_seed(seed)
    train_dataset, val_dataset = random_split(dataset, [train_size, len(dataset) - train_size], generator=generator)

    train_loader = DataLoader(train_dataset, batch_size=min(batch_size, len(train_dataset)), shuffle=True, collate_fn=_collate)
    val_loader = DataLoader(val_dataset, batch_size=min(batch_size, max(1, len(val_dataset))), shuffle=False, collate_fn=_collate)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = build_model().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
    criterion = nn.HuberLoss(delta=1.0)

    best_val = float("inf")
    best_state = None
    patience = 0
    last_train_loss = None
    last_val_loss = None

    for _epoch in range(epochs):
        model.train()
        epoch_loss = 0.0
        batch_count = 0

        for family_idx, name_bucket, numeric, base_weight, residual_target in train_loader:
            family_idx = family_idx.to(device)
            name_bucket = name_bucket.to(device)
            numeric = numeric.to(device)
            residual_target = residual_target.to(device)

            optimizer.zero_grad(set_to_none=True)
            pred = model(family_idx, name_bucket, numeric)
            loss = criterion(pred, residual_target)
            loss.backward()
            optimizer.step()

            epoch_loss += float(loss.item())
            batch_count += 1

        last_train_loss = epoch_loss / max(batch_count, 1)

        model.eval()
        val_loss = 0.0
        val_count = 0
        with torch.no_grad():
            for family_idx, name_bucket, numeric, base_weight, residual_target in val_loader:
                family_idx = family_idx.to(device)
                name_bucket = name_bucket.to(device)
                numeric = numeric.to(device)
                residual_target = residual_target.to(device)

                pred = model(family_idx, name_bucket, numeric)
                loss = criterion(pred, residual_target)
                val_loss += float(loss.item())
                val_count += 1

        last_val_loss = val_loss / max(val_count, 1)

        if last_val_loss < best_val:
            best_val = last_val_loss
            best_state = {
                "model_state_dict": model.state_dict(),
                "feature_keys": FEATURE_KEYS,
                "action_family_to_index": ACTION_FAMILY_TO_INDEX,
                "num_action_name_buckets": NUM_ACTION_NAME_BUCKETS,
                "hidden_dims": list(HIDDEN_DIMS),
                "max_delta": MAX_RESIDUAL_DELTA,
                "train_size": train_size,
                "val_size": len(dataset) - train_size,
                "num_records": len(labeled),
            }
            patience = 0
        else:
            patience += 1
            if patience >= EARLY_STOPPING_PATIENCE:
                break

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if best_state is None:
        best_state = {
            "model_state_dict": model.state_dict(),
            "feature_keys": FEATURE_KEYS,
            "action_family_to_index": ACTION_FAMILY_TO_INDEX,
            "num_action_name_buckets": NUM_ACTION_NAME_BUCKETS,
            "hidden_dims": list(HIDDEN_DIMS),
            "max_delta": MAX_RESIDUAL_DELTA,
            "train_size": train_size,
            "val_size": len(dataset) - train_size,
            "num_records": len(labeled),
        }

    torch.save(best_state, output_path)

    return TrainResult(
        trained=True,
        model_path=str(output_path),
        num_records=len(labeled),
        train_loss=last_train_loss,
        val_loss=last_val_loss,
    )
