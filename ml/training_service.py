from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Tuple

from db.db_access import (
    delete_monaction_weight_records_by_ids,
    delete_spell_weight_records_by_ids,
    delete_weapon_weight_records_by_ids,
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

    if family == "Spell":
        name = str(
            record.get("action_name")
            or record.get("spellname")
            or record.get("name")
            or ""
        ).strip().lower()
    elif family == "Weapon":
        name = str(
            record.get("action_name")
            or record.get("weaponname")
            or record.get("name")
            or ""
        ).strip().lower()
    elif family == "MonAction":
        name = str(
            record.get("action_name")
            or record.get("monactionname")
            or record.get("monster_action_name")
            or record.get("name")
            or ""
        ).strip().lower()
    else:
        name = str(
            record.get("action_name")
            or record.get("name")
            or ""
        ).strip().lower()

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


def get_ready_actions(
    action_counts: Dict[ActionKey, int],
    min_labeled_uses_per_action: int,
) -> List[Dict[str, Any]]:
    ready = [
        {"action_family": family, "action_name": name, "count": count}
        for (family, name), count in action_counts.items()
        if count >= min_labeled_uses_per_action
        and count % min_labeled_uses_per_action == 0
    ]
    return ready


def filter_training_records(
    labeled_records: List[Record],
    ready_actions: List[Dict[str, Any]],
) -> List[Record]:
    ready_action_keys = {
        (
            str(item["action_family"]).strip(),
            str(item["action_name"]).strip().lower(),
        )
        for item in ready_actions
    }

    training_records = [
        record
        for record in labeled_records
        if _action_key(record) in ready_action_keys
    ]

    print(f"[retrain] training_records={len(training_records)}")
    return training_records


def split_record_ids_by_family(records: List[Record]) -> Dict[str, List[Any]]:
    out: Dict[str, List[Any]] = {
        "Weapon": [],
        "Spell": [],
        "MonAction": [],
    }

    for record in records:
        record_id = record.get("_id")
        family = str(record.get("action_family", "") or "").strip()

        if record_id is None:
            print(f"[retrain] skipping deletion for record missing _id: {record}")
            continue

        if family in out:
            out[family].append(record_id)
        else:
            print(f"[retrain] unknown action_family during delete split: {family}")

    print(
        "[retrain] delete id buckets "
        f"weapon={len(out['Weapon'])} "
        f"spell={len(out['Spell'])} "
        f"monaction={len(out['MonAction'])}"
    )
    return out


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
            "training_record_count": 0,
            "deleted_records": False,
            "delete_summary": {
                "weapon_deleted": 0,
                "spell_deleted": 0,
                "monaction_deleted": 0,
            },
        }

    action_counts = get_labeled_action_counts(labeled_records)
    ready_actions = get_ready_actions(action_counts, min_labeled_uses_per_action)

    print(f"[retrain] ready_actions={ready_actions}")

    if not ready_actions:
        print(f"[retrain] no action reached {min_labeled_uses_per_action} labeled uses")
        return {
            "trained": False,
            "reason": f"No action has reached {min_labeled_uses_per_action} labeled uses yet.",
            "record_count": len(labeled_records),
            "ready_actions": [],
            "training_record_count": 0,
            "action_counts": [
                {"action_family": family, "action_name": name, "count": count}
                for (family, name), count in sorted(
                    action_counts.items(),
                    key=lambda item: (-item[1], item[0][0], item[0][1]),
                )
            ],
            "deleted_records": False,
            "delete_summary": {
                "weapon_deleted": 0,
                "spell_deleted": 0,
                "monaction_deleted": 0,
            },
        }

    training_records = filter_training_records(labeled_records, ready_actions)

    if not training_records:
        print("[retrain] ready_actions found but no matching training records")
        return {
            "trained": False,
            "reason": "Ready actions were found, but no matching records were collected for training.",
            "record_count": len(labeled_records),
            "ready_actions": ready_actions,
            "training_record_count": 0,
            "deleted_records": False,
            "delete_summary": {
                "weapon_deleted": 0,
                "spell_deleted": 0,
                "monaction_deleted": 0,
            },
        }

    print(f"[retrain] training model_path={model_path}")

    result: TrainResult = await asyncio.to_thread(
        train_residual_model,
        training_records,
        model_path,
    )

    print(
        f"[retrain] training result trained={result.trained} "
        f"num_records={result.num_records} "
        f"train_loss={result.train_loss} val_loss={result.val_loss}"
    )
    print(f"[retrain] delete_used_records={delete_used_records}")

    delete_summary: Dict[str, int] = {
        "weapon_deleted": 0,
        "spell_deleted": 0,
        "monaction_deleted": 0,
    }
    deleted_records = False

    if not result.trained:
        print("[retrain] training did not complete, skipping deletion")
        return {
            "trained": False,
            "reason": result.reason or "Training was skipped.",
            "record_count": result.num_records,
            "ready_actions": ready_actions,
            "training_record_count": len(training_records),
            "deleted_records": False,
            "delete_summary": delete_summary,
        }

    if not delete_used_records:
        print("[retrain] delete_used_records is False, skipping deletion")
    else:
        ids_by_family = split_record_ids_by_family(training_records)

        weapon_ids = ids_by_family["Weapon"]
        spell_ids = ids_by_family["Spell"]
        monaction_ids = ids_by_family["MonAction"]

        if weapon_ids:
            weapon_delete_result = await delete_weapon_weight_records_by_ids(weapon_ids)
            delete_summary["weapon_deleted"] = getattr(weapon_delete_result, "deleted_count", 0)

        if spell_ids:
            spell_delete_result = await delete_spell_weight_records_by_ids(spell_ids)
            delete_summary["spell_deleted"] = getattr(spell_delete_result, "deleted_count", 0)

        if monaction_ids:
            monaction_delete_result = await delete_monaction_weight_records_by_ids(monaction_ids)
            delete_summary["monaction_deleted"] = getattr(monaction_delete_result, "deleted_count", 0)

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
        "training_record_count": len(training_records),
        "model_path": str(result.model_path) if result.model_path is not None else None,
        "train_loss": result.train_loss,
        "val_loss": result.val_loss,
        "ready_actions": ready_actions,
        "deleted_records": deleted_records,
        "delete_summary": delete_summary,
    }