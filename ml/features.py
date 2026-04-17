from __future__ import annotations

import hashlib
import math
from typing import Any, Dict, Optional, Sequence, Tuple

import torch

from .config import ACTION_FAMILY_TO_INDEX, FEATURE_KEYS, NUM_ACTION_NAME_BUCKETS

_ACTION_NAME_FIELDS = ("name", "spellname", "actionName", "action_name")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _coerce_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if _is_number(value):
        fv = float(value)
        if math.isnan(fv) or math.isinf(fv):
            return default
        return fv
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _safe_get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _action_to_dict(action: Any) -> Dict[str, Any]:
    if action is None:
        return {}
    if isinstance(action, dict):
        return action
    to_dict = getattr(action, "toDict", None)
    if callable(to_dict):
        try:
            return to_dict()
        except Exception:
            return {}
    return {}


def stable_hash_bucket(text: str, num_buckets: int = NUM_ACTION_NAME_BUCKETS) -> int:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "little") % num_buckets


def infer_action_family(record: Dict[str, Any]) -> str:
    family = record.get("action_family")
    if family in ACTION_FAMILY_TO_INDEX:
        return family
    if "spellname" in record:
        return "Spell"
    if "weaponStat" in record or "damageDice" in record:
        return "Weapon"
    return "MonAction"


def get_action_name(record: Dict[str, Any]) -> str:
    for key in _ACTION_NAME_FIELDS:
        value = record.get(key)
        if value:
            return str(value)
    return "unknown_action"


def get_action_level(record: Dict[str, Any]) -> float:
    for key in ("spell_level", "level", "action_level", "lvl"):
        if key in record and record[key] is not None:
            return _coerce_float(record[key])
    return 0.0


def get_action_range_ft(record: Dict[str, Any]) -> float:
    for key in ("range_ft", "actionRange", "action_range", "range", "spellRange"):
        if key in record and record[key] is not None:
            return _coerce_float(record[key])
    return 0.0


def get_action_cost_value(record: Dict[str, Any]) -> float:
    cost = record.get("actionCost", record.get("action_cost", "action"))
    if isinstance(cost, str):
        c = cost.strip().lower()
        if c == "action":
            return 1.0
        if c in {"bonus action", "bonus_action", "bonus"}:
            return 0.5
        if c == "reaction":
            return 0.75
        if c in {"free", "free action", "free_action"}:
            return 0.0
        return 1.0
    return _coerce_float(cost, 1.0)


def _extract_actor_features(actor: Any) -> Dict[str, float]:
    result = {
        "actor_level": 0.0,
        "actor_hp": 0.0,
        "actor_hp_pct": 0.0,
        "actor_ac": 0.0,
        "actor_spell_mod": 0.0,
    }

    if actor is None:
        return result

    if isinstance(actor, dict):
        stats = actor.get("stats", actor)
        result["actor_level"] = _coerce_float(stats.get("level"))
        result["actor_hp"] = _coerce_float(stats.get("hp"))
        max_hp = _coerce_float(stats.get("maxhp"))
        result["actor_hp_pct"] = (result["actor_hp"] / max_hp) if max_hp > 0 else 0.0
        result["actor_ac"] = _coerce_float(stats.get("ac"))
        result["actor_spell_mod"] = _coerce_float(actor.get("spellMod", actor.get("spell_mod")))
        return result

    for key, attr in (
        ("actor_level", "getLevel"),
        ("actor_hp", "getHP"),
        ("actor_ac", "getAC"),
    ):
        getter = getattr(actor, attr, None)
        if callable(getter):
            result[key] = _coerce_float(getter())

    max_hp_getter = getattr(actor, "getMaxHP", None)
    hp_getter = getattr(actor, "getHP", None)
    if callable(max_hp_getter) and callable(hp_getter):
        hp = _coerce_float(hp_getter())
        max_hp = _coerce_float(max_hp_getter())
        result["actor_hp_pct"] = (hp / max_hp) if max_hp > 0 else 0.0

    spell_mod_getter = getattr(actor, "getSpellMod", None)
    if callable(spell_mod_getter):
        result["actor_spell_mod"] = _coerce_float(spell_mod_getter())

    return result


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


def _extract_single_target_stats(target: Any) -> Dict[str, float]:
    result = {
        "hp": 0.0,
        "hp_pct": 0.0,
        "ac": 0.0,
        "save_bonus": 0.0,
    }

    if target is None:
        return result

    statblock = target.get("Statblock", target) if isinstance(target, dict) else target

    if isinstance(statblock, dict):
        hp = _coerce_float(statblock.get("hp", statblock.get("HP")))
        max_hp = _coerce_float(statblock.get("maxhp", statblock.get("maxHP")))
        result["hp"] = hp
        result["hp_pct"] = (hp / max_hp) if max_hp > 0 else 0.0
        result["ac"] = _coerce_float(statblock.get("ac", statblock.get("AC")))
        result["save_bonus"] = _coerce_float(
            statblock.get("saveBonus", statblock.get("save_bonus", 0.0))
        )
        return result

    hp_getter = getattr(statblock, "getHP", None)
    max_hp_getter = getattr(statblock, "getMaxHP", None)
    ac_getter = getattr(statblock, "getAC", None)
    save_bonus_getter = getattr(statblock, "getSaveBonus", None)

    if callable(hp_getter):
        result["hp"] = _coerce_float(hp_getter())
    if callable(max_hp_getter) and callable(hp_getter):
        max_hp = _coerce_float(max_hp_getter())
        result["hp_pct"] = (result["hp"] / max_hp) if max_hp > 0 else 0.0
    if callable(ac_getter):
        result["ac"] = _coerce_float(ac_getter())
    if callable(save_bonus_getter):
        result["save_bonus"] = _coerce_float(save_bonus_getter())
    else:
        result["save_bonus"] = _coerce_float(getattr(statblock, "saveBonus", 0.0))

    return result


def _extract_target_features(targets: Any) -> Dict[str, float]:
    result = {
        "target_hp": 0.0,
        "target_hp_pct": 0.0,
        "target_ac": 0.0,
        "target_save_bonus": 0.0,
        "target_hp_mean": 0.0,
        "target_hp_pct_min": 0.0,
        "target_hp_pct_max": 0.0,
        "target_ac_mean": 0.0,
        "target_save_bonus_mean": 0.0,
        "num_targets": 0.0,
        "num_targets_selected": 0.0,
        "num_targets_hit": 0.0,
        "targets_hit_count": 0.0,
        "target_count_valid": 0.0,
    }

    normalized = _normalize_targets(targets)
    if not normalized:
        return result

    result["num_targets"] = float(len(normalized))
    result["num_targets_selected"] = float(len(normalized))
    result["num_targets_hit"] = float(len(normalized))
    result["targets_hit_count"] = float(len(normalized))

    rows = [_extract_single_target_stats(t) for t in normalized]
    valid_rows = [r for r in rows if any(v != 0.0 for v in r.values())]

    result["target_count_valid"] = float(len(valid_rows) if valid_rows else len(normalized))
    if not valid_rows:
        return result

    hp_vals = [r["hp"] for r in valid_rows]
    hp_pct_vals = [r["hp_pct"] for r in valid_rows]
    ac_vals = [r["ac"] for r in valid_rows]
    save_vals = [r["save_bonus"] for r in valid_rows]

    result["target_hp"] = sum(hp_vals) / len(hp_vals)
    result["target_hp_mean"] = result["target_hp"]
    result["target_hp_pct"] = sum(hp_pct_vals) / len(hp_pct_vals)
    result["target_hp_pct_min"] = min(hp_pct_vals)
    result["target_hp_pct_max"] = max(hp_pct_vals)
    result["target_ac"] = sum(ac_vals) / len(ac_vals)
    result["target_ac_mean"] = result["target_ac"]
    result["target_save_bonus"] = sum(save_vals) / len(save_vals)
    result["target_save_bonus_mean"] = result["target_save_bonus"]

    return result


def build_feature_snapshot(
    *,
    action: Any,
    actor: Any = None,
    targets: Any = None,
    base_weight: float = 0.0,
    predicted_weight: Optional[float] = None,   # kept for compatibility
    label: Optional[float] = None,              # kept for compatibility
    residual: Optional[float] = None,           # kept for compatibility
    heuristic_components: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, float]:
    snapshot = {key: 0.0 for key in FEATURE_KEYS}

    action_dict = _action_to_dict(action)
    roll_type = _get_roll_type(action, action_dict)
    damage_type_text = _get_damage_type_text(action, action_dict)
    shape_text = _get_shape_text(action_dict)

    snapshot.update({
        "base_weight": _coerce_float(base_weight),
        "action_level": get_action_level(action_dict),
        "action_range_ft": get_action_range_ft(action_dict),
        "action_cost_value": get_action_cost_value(action_dict),
        "is_healing": 1.0 if "healing" in damage_type_text else 0.0,
        "is_save": 1.0 if "save" in roll_type else 0.0,
        "is_to_hit": 1.0 if "tohit" in roll_type else 0.0,
        "is_aoe": 1.0 if _is_aoe_action(action_dict, shape_text) else 0.0,  #1.0 stand for true, 0.0 for false
        "has_linger": 1.0 if _has_linger(action_dict) else 0.0,
    })

    if heuristic_components:
        snapshot.update(_extract_heuristic_features(heuristic_components))

    snapshot.update(_extract_actor_features(actor))
    snapshot.update(_extract_target_features(targets))

    if context:
        snapshot.update(_extract_context_features(context))

    if _normalize_targets(targets):
        snapshot["target_count_valid"] = max(snapshot["target_count_valid"], 1.0)

    return snapshot


def _get_roll_type(action: Any, action_dict: Dict[str, Any]) -> str:
    getter = getattr(action, "getRollType", None)
    if callable(getter):
        try:
            return str(getter()).lower()
        except Exception:
            pass
    return str(action_dict.get("rollType", "")).lower()


def _get_damage_type_text(action: Any, action_dict: Dict[str, Any]) -> str:
    getter = getattr(action, "getDamType", None)
    if callable(getter):
        try:
            damage_type = getter()
        except Exception:
            damage_type = action_dict.get("damType", "")
    else:
        damage_type = action_dict.get("damType", "")

    if isinstance(damage_type, list):
        return " ".join(str(x) for x in damage_type).lower()
    return str(damage_type).lower()


def _get_shape_text(action_dict: Dict[str, Any]) -> str:
    return " ".join(
        str(action_dict.get(key, "") or "")
        for key in ("shape", "spellShape", "actionShape")
    ).lower()


def _is_aoe_action(action_dict: Dict[str, Any], shape_text: str) -> bool:
    return bool(shape_text or action_dict.get("actionRadius") or action_dict.get("radius"))


def _has_linger(action_dict: Dict[str, Any]) -> bool:
    return bool(action_dict.get("lingEffect") or action_dict.get("lingSave"))


def _extract_heuristic_features(heuristic_components: Dict[str, Any]) -> Dict[str, float]:
    return {
        "expected_damage": _coerce_float(heuristic_components.get("expected_damage", 0.0)),
        "kill_chance": _coerce_float(heuristic_components.get("kill_chance", 0.0)),
        "impact_score": _coerce_float(heuristic_components.get("impact_score", 0.0)),
        "ling_save_weight": _coerce_float(heuristic_components.get("ling_save_weight", 0.0)),
        "ling_effect_weight": _coerce_float(heuristic_components.get("ling_effect_weight", 0.0)),
        "extra_effect_weight": _coerce_float(heuristic_components.get("extra_effect_weight", 0.0)),
    }


def _extract_context_features(context: Dict[str, Any]) -> Dict[str, float]:
    extracted: Dict[str, float] = {}
    for key in FEATURE_KEYS:
        if key in context and context[key] is not None:
            extracted[key] = _coerce_float(context[key])
    return extracted

def feature_snapshot_to_tensor(
    snapshot: Dict[str, Any],
    feature_keys: Sequence[str] = FEATURE_KEYS,
) -> torch.Tensor:
    values = [_coerce_float(snapshot.get(key, 0.0)) for key in feature_keys]
    return torch.tensor(values, dtype=torch.float32)


def record_to_model_parts(
    record: Dict[str, Any],
    feature_keys: Sequence[str] = FEATURE_KEYS,
) -> Tuple[int, int, torch.Tensor, float, str]:
    family = infer_action_family(record)
    family_idx = ACTION_FAMILY_TO_INDEX.get(family, 2)
    action_name = get_action_name(record)
    name_bucket = stable_hash_bucket(action_name)
    snapshot = record.get("feature_snapshot") or {}
    features = feature_snapshot_to_tensor(snapshot, feature_keys=feature_keys)
    base_weight = _coerce_float(record.get("base_weight", 0.0))
    return family_idx, name_bucket, features, base_weight, action_name


def record_has_label(record: Dict[str, Any]) -> bool:
    return record.get("label") is not None