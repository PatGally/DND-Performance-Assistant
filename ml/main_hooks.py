from __future__ import annotations
from typing import Any, Dict, Optional

from .features import build_feature_snapshot, get_action_name, infer_action_family
from .inference import predict_final_weight


def _action_to_dict(action: Any) -> Dict[str, Any]:
    if isinstance(action, dict):
        return action
    if hasattr(action, "toDict") and callable(action.toDict):
        return action.toDict()
    return {}

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
) -> Dict[str, Any]:
    action_dict = _action_to_dict(action)
    family = infer_action_family(action_dict)
    action_name = get_action_name(action_dict)
    ...

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
        "outcome_snapshot": outcome_snapshot,
        "encounter_id": encounter_id,
        "user_id": user_id,
        "model_version": None,
        "action_name": action_name,
    }

    if family == "Spell":
        record["spellname"] = action_name
    else:
        record["name"] = action_name

    return record


def predict_action_weight(record: Dict[str, Any], model_path: Optional[str] = None) -> float:
    return predict_final_weight(record, model_path=model_path)
