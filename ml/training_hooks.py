from __future__ import annotations
from typing import Any, Dict, Optional

from CoreEngine import Spell, Weapon
from db.db_access import (
    create_monaction_weight_record,
    create_spell_weight_record,
    create_weapon_weight_record,
    finalize_monaction_weight_record,
    finalize_spell_weight_record,
    finalize_weapon_weight_record,
)
from .main_hooks import make_training_record


def _extract_numeric_outcome_label(action_result: Dict[str, Any]) -> float:
    outcome = action_result.get("outcome", {}) or {}
    dice_results = outcome.get("diceResults", []) or []

    total = 0.0
    for value in dice_results:
        try:
            total += float(value)
        except (TypeError, ValueError):
            continue

    return float(total)


async def persist_labeled_action_record(
    *,
    action: Any,
    actor: Any = None,
    targets: Any = None,
    encounter_id: str,
    user_id: Optional[str] = None,
    base_weight: float = 0.0,
    predicted_weight: Optional[float] = None,
    heuristic_components: Optional[Dict[str, Any]] = None,
    outcome_snapshot: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
    action_result: Optional[Dict[str, Any]] = None,
    target_snapshot: Optional[Dict[str, Any]] = None,
    aoe_snapshot: Optional[Dict[str, Any]] = None,
    turn_context_snapshot: Optional[Dict[str, Any]] = None,
    model_version: Optional[str] = None,
) -> Dict[str, Any]:
    result_payload = action_result or {}
    final_outcome_snapshot = (
        outcome_snapshot if outcome_snapshot is not None else result_payload.get("outcome")
    )

    label = _extract_numeric_outcome_label(result_payload)
    residual = float(label) - float(base_weight)
    safe_predicted_weight = (
        float(predicted_weight) if predicted_weight is not None else float(base_weight)
    )

    record = make_training_record(
        action=action,
        actor=actor,
        targets=targets,
        encounter_id=encounter_id,
        user_id=user_id,
        base_weight=base_weight,
        predicted_weight=safe_predicted_weight,
        label=label,
        residual=residual,
        heuristic_components=heuristic_components,
        outcome_snapshot=final_outcome_snapshot,
        context=context,
        target_snapshot=target_snapshot,
        aoe_snapshot=aoe_snapshot,
        turn_context_snapshot=turn_context_snapshot,
    )

    if isinstance(action, Weapon):
        record_id = await create_weapon_weight_record(record)
        await finalize_weapon_weight_record(
            record_id,
            predicted_weight=safe_predicted_weight,
            label=label,
            residual=residual,
            model_version=model_version,
            outcome_snapshot=final_outcome_snapshot,
        )

    elif isinstance(action, Spell):
        record_id = await create_spell_weight_record(record)
        await finalize_spell_weight_record(
            record_id,
            predicted_weight=safe_predicted_weight,
            label=label,
            residual=residual,
            model_version=model_version,
            outcome_snapshot=final_outcome_snapshot,
        )

    else:
        record_id = await create_monaction_weight_record(record)
        await finalize_monaction_weight_record(
            record_id,
            predicted_weight=safe_predicted_weight,
            label=label,
            residual=residual,
            model_version=model_version,
            outcome_snapshot=final_outcome_snapshot,
        )

    record["_id"] = record_id
    return record