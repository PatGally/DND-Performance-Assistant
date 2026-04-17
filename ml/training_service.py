from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

from db.db_access import (
    delete_monaction_weight_records_by_encounter,
    delete_spell_weight_records_by_encounter,
    delete_weapon_weight_records_by_encounter,
    get_monaction_weight_training_batch,
    get_spell_weight_training_batch,
    get_weapon_weight_training_batch,
)

from .config import DEFAULT_MODEL_PATH, MIN_LABELED_USES_PER_ACTION_TO_TRAIN
from .train import TrainResult, train_residual_model

Record = Dict[str, Any]
ActionKey = Tuple[str, str]


def _action_key(record: Record) -> ActionKey:
    family = str(record.get("action_family", "") or "").strip()
    name = str(record.get("action_name") or record.get("name") or "").strip().lower()
    return family, name


async def _load_labeled_records_from_cursor(cursor) -> List[Record]:
    rows: List[Record] = await cursor.to_list(length=None)
    return rows


async def load_all_labeled_records() -> List[Record]:
    print("[retrain] loading labeled records from DB")

    weapon_cursor = await get_weapon_weight_training_batch()
    spell_cursor = await get_spell_weight_training_batch()
    mon_cursor = await get_monaction_weight_training_batch()

    weapon_rows, spell_rows, mon_rows = await asyncio.gather(
        _load_labeled_records_from_cursor(weapon_cursor),
        _load_labeled_records_from_cursor(spell_cursor),
        _load_labeled_records_from_cursor(mon_cursor),
    )

    total = len(weapon_rows) + len(spell_rows) + len(mon_rows)
    print(
        f"[retrain] loaded weapon={len(weapon_rows)} "
        f"spell={len(spell_rows)} monaction={len(mon_rows)} total={total}"
    )

    return list(weapon_rows) + list(spell_rows) + list(mon_rows)


def get_labeled_action_counts(records: List[Record]) -> Dict[ActionKey, int]:
    counts: Counter[ActionKey] = Counter()

    for record in records:
        if record.get("label") is None:
            continue

        family, name = _action_key(record)

        if family and name:
            counts[(family, name)] += 1
        else:
            print(f"[retrain] skipped record missing key fields: {record}")

    print(f"[retrain] action counts={dict(counts)}")
    return dict(counts)


async def maybe_train_after_action_uses(
    *,
    min_labeled_uses_per_action: int = MIN_LABELED_USES_PER_ACTION_TO_TRAIN,
    model_path: str | Path = DEFAULT_MODEL_PATH,
    delete_used_records: bool = True,
) -> Dict[str, Any]:
    print("[retrain] maybe_train_after_action_uses start")

    records = await load_all_labeled_records()
    labeled_records: List[Record] = [r for r in records if r.get("label") is not None]

    print(f"[retrain] labeled_records={len(labeled_records)}")

    if not labeled_records:
        print("[retrain] no labeled records available")
        return {
            "trained": False,
            "reason": "No labeled records available.",
            "record_count": 0,
            "ready_actions": [],
            "deleted_records": False,
            "deleted_encounter_ids": [],
        }

    action_counts = get_labeled_action_counts(labeled_records)
    ready_actions = [
        {"action_family": family, "action_name": name, "count": count}
        for (family, name), count in action_counts.items()
        if count >= min_labeled_uses_per_action
        and count % min_labeled_uses_per_action == 0
    ]

    print(f"[retrain] ready_actions={ready_actions}")

    if not ready_actions:
        print(f"[retrain] no action reached {min_labeled_uses_per_action} labeled uses")
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
            "deleted_records": False,
            "deleted_encounter_ids": [],
        }

    print(f"[retrain] training model_path={model_path}")

    result: TrainResult = await asyncio.to_thread(
        train_residual_model,
        labeled_records,
        model_path,
    )

    print(
        f"[retrain] training result trained={result.trained} "
        f"num_records={result.num_records} "
        f"train_loss={result.train_loss} val_loss={result.val_loss}"
    )
    print(f"[retrain] delete_used_records={delete_used_records}")

    if not result.trained:
        print("[retrain] training did not complete, skipping deletion")
        return {
            "trained": False,
            "reason": result.reason or "Training was skipped.",
            "record_count": result.num_records,
            "ready_actions": ready_actions,
            "deleted_records": False,
            "deleted_encounter_ids": [],
        }

    deleted_encounter_ids: List[str] = []
    deleted_records = False
    delete_summary: Dict[str, int] = {
        "weapon_deleted": 0,
        "spell_deleted": 0,
        "monaction_deleted": 0,
    }

    if not delete_used_records:
        print("[retrain] delete_used_records is False, skipping deletion")
    else:
        encounter_ids: List[str] = sorted({
            str(r["encounter_id"]).strip()
            for r in labeled_records
            if r.get("encounter_id")
        })

        print(
            f"[retrain] trained={result.trained} "
            f"delete_used_records={delete_used_records} "
            f"encounter_ids={encounter_ids}"
        )

        if not encounter_ids:
            print("[retrain] no encounter_ids found on labeled records, nothing to delete")
        else:
            print(f"[retrain] deleting records for {len(encounter_ids)} encounter_ids")

            weapon_results = await asyncio.gather(
                *(delete_weapon_weight_records_by_encounter(eid) for eid in encounter_ids)
            )
            spell_results = await asyncio.gather(
                *(delete_spell_weight_records_by_encounter(eid) for eid in encounter_ids)
            )
            monaction_results = await asyncio.gather(
                *(delete_monaction_weight_records_by_encounter(eid) for eid in encounter_ids)
            )

            delete_summary["weapon_deleted"] = sum(
                getattr(result, "deleted_count", 0) for result in weapon_results
            )
            delete_summary["spell_deleted"] = sum(
                getattr(result, "deleted_count", 0) for result in spell_results
            )
            delete_summary["monaction_deleted"] = sum(
                getattr(result, "deleted_count", 0) for result in monaction_results
            )

            deleted_encounter_ids = encounter_ids
            deleted_records = True

            print(
                "[retrain] delete summary "
                f"weapon={delete_summary['weapon_deleted']} "
                f"spell={delete_summary['spell_deleted']} "
                f"monaction={delete_summary['monaction_deleted']}"
            )

    print("[retrain] maybe_train_after_action_uses complete")

    return {
        "trained": True,
        "record_count": result.num_records,
        "model_path": str(result.model_path) if result.model_path is not None else None,
        "train_loss": result.train_loss,
        "val_loss": result.val_loss,
        "ready_actions": ready_actions,
        "deleted_records": deleted_records,
        "deleted_encounter_ids": deleted_encounter_ids,
        "delete_summary": delete_summary,
    }