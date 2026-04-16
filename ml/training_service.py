from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

from db.db_access import (
    delete_monaction_weight_records_by_encounter,
    delete_spell_weight_records_by_encounter,
    delete_weapon_weight_records_by_encounter,
    monActionWeightDb,
    spellWeightDb,
    weaponWeightDb,
)

from .config import DEFAULT_MODEL_PATH, MIN_LABELED_USES_PER_ACTION_TO_TRAIN
from .train import TrainResult, train_residual_model


Record = Dict[str, Any]
ActionKey = Tuple[str, str]


def _action_key(record: Record) -> ActionKey:
    return (
        str(record.get("action_family", "")),
        str(record.get("action_name", "")),
    )


async def _load_labeled_records(collection: Any) -> List[Record]:
    cursor = collection.find({"label": {"$ne": None}})
    rows: List[Record] = await cursor.to_list(length=None)
    return rows


async def load_all_labeled_records() -> List[Record]:
    weapon_rows, spell_rows, mon_rows = await asyncio.gather(
        _load_labeled_records(weaponWeightDb),
        _load_labeled_records(spellWeightDb),
        _load_labeled_records(monActionWeightDb),
    )
    return list(weapon_rows) + list(spell_rows) + list(mon_rows)


def get_labeled_action_counts(records: List[Record]) -> Dict[ActionKey, int]:
    counts: Counter[ActionKey] = Counter()

    for record in records:
        if record.get("label") is None:
            continue
        key = _action_key(record)
        if key[0] and key[1]:
            counts[key] += 1

    return dict(counts)


async def maybe_train_after_action_uses(
    *,
    min_labeled_uses_per_action: int = MIN_LABELED_USES_PER_ACTION_TO_TRAIN,
    model_path: str | Path = DEFAULT_MODEL_PATH,
    delete_used_records: bool = True,
) -> Dict[str, Any]:
    records = await load_all_labeled_records()
    labeled_records: List[Record] = [r for r in records if r.get("label") is not None]

    if not labeled_records:
        return {
            "trained": False,
            "reason": "No labeled records available.",
            "record_count": 0,
            "ready_actions": [],
        }

    action_counts = get_labeled_action_counts(labeled_records)
    ready_actions = [
        {"action_family": family, "action_name": name, "count": count}
        for (family, name), count in action_counts.items()
        if count >= min_labeled_uses_per_action
    ]

    if not ready_actions:
        return {
            "trained": False,
            "reason": f"No action has reached {min_labeled_uses_per_action} labeled uses yet.",
            "record_count": len(labeled_records),
            "ready_actions": [],
            "action_counts": [
                {"action_family": family, "action_name": name, "count": count}
                for (family, name), count in sorted(
                    action_counts.items(),
                    key=lambda item: (-item[1], item[0][0], item[0][1]),
                )
            ],
        }

    result: TrainResult = await asyncio.to_thread(
        train_residual_model,
        labeled_records,
        model_path,
    )

    if not result.trained:
        return {
            "trained": False,
            "reason": result.reason or "Training was skipped.",
            "record_count": result.num_records,
            "ready_actions": ready_actions,
        }

    if delete_used_records:
        encounter_ids: List[str] = sorted({
            str(r["encounter_id"])
            for r in labeled_records
            if r.get("encounter_id")
        })

        await asyncio.gather(
            *(delete_weapon_weight_records_by_encounter(eid) for eid in encounter_ids),
            *(delete_spell_weight_records_by_encounter(eid) for eid in encounter_ids),
            *(delete_monaction_weight_records_by_encounter(eid) for eid in encounter_ids),
        )

    return {
        "trained": True,
        "record_count": result.num_records,
        "model_path": str(result.model_path) if result.model_path is not None else None,
        "train_loss": result.train_loss,
        "val_loss": result.val_loss,
        "ready_actions": ready_actions,
    }