from __future__ import annotations
from typing import Any, Dict, Optional

from .features import build_feature_snapshot, get_action_name, infer_action_family
from .inference import predict_final_weight

def _action_to_dict(action: Any) -> dict:
    if isinstance(action, dict):
        return action
    if hasattr(action, "toDict") and callable(action.toDict):
        try:
            return action.toDict()
        except Exception:
            return {}
    return {}


def _extract_prob_value(prob) -> float:
    if isinstance(prob, (int, float)):
        return float(prob)

    if isinstance(prob, str):
        try:
            return float(prob.split(" - ")[0].strip())
        except Exception:
            return 0.0

    if isinstance(prob, dict):
        return float(prob.get("probSuccess", 0.0))

    return 0.0


def _sum_numeric(values: Any) -> float:
    total = 0.0
    for value in values or []:
        try:
            total += float(value)
        except (TypeError, ValueError):
            continue
    return total


def _normalize_targets(targets: Any) -> list[Any]:
    if targets is None:
        return []
    if isinstance(targets, dict):
        if isinstance(targets.get("targetsHit"), list):
            return [t for t in targets["targetsHit"] if t is not None]
        return [targets]
    if isinstance(targets, list):
        return [t for t in targets if t is not None]
    return [targets]


def _target_name(target: Any) -> str:
    if isinstance(target, dict):
        if isinstance(target.get("Statblock"), dict):
            return str(target["Statblock"].get("name", target.get("name", "")))
        if "name" in target:
            return str(target["name"])
        statblock = target.get("Statblock")
        getter = getattr(statblock, "getName", None)
        if callable(getter):
            try:
                return str(getter())
            except Exception:
                return ""
    getter = getattr(target, "getName", None)
    if callable(getter):
        try:
            return str(getter())
        except Exception:
            return ""
    return ""


def _target_cid(target: Any) -> str:
    if isinstance(target, dict):
        if isinstance(target.get("Statblock"), dict):
            return str(target["Statblock"].get("cid", target.get("cid", "")))
        if "cid" in target:
            return str(target["cid"])
        statblock = target.get("Statblock")
        getter = getattr(statblock, "getCID", None)
        if callable(getter):
            try:
                return str(getter())
            except Exception:
                return ""
    getter = getattr(target, "getCID", None)
    if callable(getter):
        try:
            return str(getter())
        except Exception:
            return ""
    return ""


def _build_target_snapshot(targets: Any) -> Dict[str, Any]:
    normalized = _normalize_targets(targets)
    return {
        "count": len(normalized),
        "names": [_target_name(t) for t in normalized],
        "cids": [_target_cid(t) for t in normalized],
        "types": [type(t).__name__ for t in normalized],
    }


def _build_aoe_snapshot(aoe_token: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    token = dict(aoe_token or {})
    positioning = token.get("positioning") or []
    shape = str(token.get("shape", "")).lower()
    timing = str(token.get("timing", "")).lower()

    return {
        "shape": token.get("shape"),
        "timing": token.get("timing"),
        "anchor": token.get("anchor"),
        "positioning": positioning,
        "cells_covered": len(positioning),
        "aoe_has_anchor": 1.0 if token.get("anchor") else 0.0,
        "aoe_is_lingering": 1.0 if timing == "lingering" else 0.0,
        "aoe_shape_circle": 1.0 if "circle" in shape else 0.0,
        "aoe_shape_cone": 1.0 if "cone" in shape else 0.0,
        "aoe_shape_square": 1.0 if "square" in shape else 0.0,
        "aoe_shape_line": 1.0 if "line" in shape else 0.0,
    }


def _build_outcome_snapshot(action_result: Optional[Dict[str, Any]], *, targets_count: int) -> Dict[str, Any]:
    payload = action_result or {}
    outcome = payload.get("outcome", {}) or {}
    extra = payload.get("extraOutcome", {}) or {}
    conditions = payload.get("conditions", []) or []
    status_effects = payload.get("statusEffects", []) or []

    return {
        "rollResults": outcome.get("rollResults", []) or [],
        "diceResults": outcome.get("diceResults", []) or [],
        "extraRollResults": extra.get("extraRollResults", []) or [],
        "extraDiceResults": extra.get("extraDiceResults", []) or [],
        "damage_total": _sum_numeric(outcome.get("diceResults", [])),
        "extra_damage_total": _sum_numeric(extra.get("extraDiceResults", [])),
        "conditions_applied": conditions,
        "status_effects_applied": status_effects,
        "conditions_applied_count": float(len(conditions)),
        "status_effects_applied_count": float(len(status_effects)),
        "targets_hit_count": float(targets_count),
    }


def build_scored_training_record_inputs(
    *,
    actor: Any,
    action_obj: Any,
    targets: Any,
    encounter_id: str,
    prob: Any,
    expected_damage: float,
    impact: float,
    aoe_token: Optional[Dict[str, Any]] = None,
    action_result: Optional[Dict[str, Any]] = None,
    turn_context: Optional[Dict[str, Any]] = None,
    base_weight: Optional[float] = None,
) -> Dict[str, Any]:
    prob_value = _extract_prob_value(prob)

    base_weight = float(base_weight)

    normalized_targets = _normalize_targets(targets)
    target_snapshot = _build_target_snapshot(normalized_targets)
    aoe_snapshot = _build_aoe_snapshot(aoe_token)
    outcome_snapshot = _build_outcome_snapshot(
        action_result,
        targets_count=len(normalized_targets),
    )

    heuristic_components = {
        "expected_damage": float(expected_damage or 0.0),
        "impact_score": float(impact or 0.0),
        "kill_chance": 0.0,
        "prob_success": float(prob_value),
    }

    context = {
        "expected_damage": float(expected_damage or 0.0),
        "impact_score": float(impact or 0.0),
        "num_targets": float(len(normalized_targets)),
        "num_targets_selected": float(len(normalized_targets)),
        "num_targets_hit": float(len(normalized_targets)),
        "targets_hit_count": float(len(normalized_targets)),
        "target_count_valid": float(len(normalized_targets)),
        "damage_total": float(outcome_snapshot["damage_total"]),
        "extra_damage_total": float(outcome_snapshot["extra_damage_total"]),
        "conditions_applied_count": float(outcome_snapshot["conditions_applied_count"]),
        "status_effects_applied_count": float(outcome_snapshot["status_effects_applied_count"]),
        "aoe_cells_covered": float(aoe_snapshot["cells_covered"]),
        "aoe_has_anchor": float(aoe_snapshot["aoe_has_anchor"]),
        "aoe_is_lingering": float(aoe_snapshot["aoe_is_lingering"]),
        "aoe_shape_circle": float(aoe_snapshot["aoe_shape_circle"]),
        "aoe_shape_cone": float(aoe_snapshot["aoe_shape_cone"]),
        "aoe_shape_square": float(aoe_snapshot["aoe_shape_square"]),
        "aoe_shape_line": float(aoe_snapshot["aoe_shape_line"]),
    }

    if turn_context:
        context.update(turn_context)

    record = make_training_record(
        action=action_obj,
        actor=actor,
        targets=normalized_targets,
        encounter_id=encounter_id,
        base_weight=float(base_weight),
        heuristic_components=heuristic_components,
        outcome_snapshot=outcome_snapshot,
        context=context,
        target_snapshot=target_snapshot,
        aoe_snapshot=aoe_snapshot,
        turn_context_snapshot=turn_context or {},
    )

    predicted_weight = float(predict_action_weight(record))
    record["predicted_weight"] = predicted_weight

    return {
        "record": record,
        "base_weight": float(base_weight),
        "predicted_weight": predicted_weight,
        "heuristic_components": heuristic_components,
        "context": context,
        "target_snapshot": target_snapshot,
        "aoe_snapshot": aoe_snapshot,
        "outcome_snapshot": outcome_snapshot,
        "turn_context_snapshot": turn_context or {},
    }

def make_training_record(
    *,
    action: Any,
    actor: Any = None,
    targets: Any = None,
    encounter_id: str,
    user_id: Optional[str] = None,
    base_weight: float = 0.0,
    predicted_weight: Optional[float] = None,
    label: Optional[float] = None,
    residual: Optional[float] = None,
    heuristic_components: Optional[Dict[str, Any]] = None,
    outcome_snapshot: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
    target_snapshot: Optional[Dict[str, Any]] = None,
    aoe_snapshot: Optional[Dict[str, Any]] = None,
    turn_context_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    action_dict = _action_to_dict(action)
    family = infer_action_family(action_dict)
    action_name = get_action_name(action_dict)

    feature_snapshot = build_feature_snapshot(
        action=action,
        actor=actor,
        targets=targets,
        base_weight=base_weight,
        predicted_weight=predicted_weight,
        label=label,
        residual=residual,
        heuristic_components=heuristic_components,
        context=context,
    )

    record: Dict[str, Any] = {
        "action_family": family,
        "base_weight": float(base_weight),
        "predicted_weight": float(predicted_weight) if predicted_weight is not None else None,
        "label": float(label) if label is not None else None,
        "residual": float(residual) if residual is not None else None,
        "feature_snapshot": feature_snapshot,
        "outcome_snapshot": outcome_snapshot or {},
        "context_snapshot": context or {},
        "target_snapshot": target_snapshot or {},
        "aoe_snapshot": aoe_snapshot or {},
        "turn_context_snapshot": turn_context_snapshot or {},
        "encounter_id": encounter_id,
        "user_id": user_id,
        "model_version": None,
        "action_name": action_name,
    }

    if family == "Spell":
        record["spellname"] = action_name
    elif family == "MonAction":
        record["name"] = action_name
    else:
        record["name"] = action_name

    return record

def predict_action_weight(record: Dict[str, Any], model_path: Optional[str] = None) -> float:
    return predict_final_weight(record, model_path=model_path)