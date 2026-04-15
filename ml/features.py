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


def _extract_target_features(targets: Any) -> Dict[str, float]:
    result = {
        "target_hp": 0.0,
        "target_hp_pct": 0.0,
        "target_ac": 0.0,
        "target_save_bonus": 0.0,
        "num_targets": 0.0,
        "target_count_valid": 0.0,
    }

    if targets is None:
        return result

    if not isinstance(targets, list):
        targets = [targets]

    result["num_targets"] = float(len(targets))
    result["target_count_valid"] = float(len(targets))

    first = targets[0] if targets else None
    if first is None:
        return result

    if isinstance(first, dict):
        statblock = first.get("Statblock", first)
        if isinstance(statblock, dict):
            result["target_hp"] = _coerce_float(statblock.get("hp", statblock.get("HP")))
            result["target_ac"] = _coerce_float(statblock.get("ac", statblock.get("AC")))
            max_hp = _coerce_float(statblock.get("maxhp", statblock.get("maxHP")))
            result["target_hp_pct"] = (result["target_hp"] / max_hp) if max_hp > 0 else 0.0
            result["target_save_bonus"] = _coerce_float(statblock.get("saveBonus", 0.0))
            return result

        hp_getter = getattr(statblock, "getHP", None)
        ac_getter = getattr(statblock, "getAC", None)
        max_hp_getter = getattr(statblock, "getMaxHP", None)
        if callable(hp_getter):
            result["target_hp"] = _coerce_float(hp_getter())
        if callable(ac_getter):
            result["target_ac"] = _coerce_float(ac_getter())
        if callable(max_hp_getter) and callable(hp_getter):
            max_hp = _coerce_float(max_hp_getter())
            hp = _coerce_float(hp_getter())
            result["target_hp_pct"] = (hp / max_hp) if max_hp > 0 else 0.0
        return result

    hp_getter = getattr(first, "getHP", None)
    ac_getter = getattr(first, "getAC", None)
    max_hp_getter = getattr(first, "getMaxHP", None)
    if callable(hp_getter):
        result["target_hp"] = _coerce_float(hp_getter())
    if callable(ac_getter):
        result["target_ac"] = _coerce_float(ac_getter())
    if callable(max_hp_getter) and callable(hp_getter):
        max_hp = _coerce_float(max_hp_getter())
        hp = _coerce_float(hp_getter())
        result["target_hp_pct"] = (hp / max_hp) if max_hp > 0 else 0.0
    return result


def build_feature_snapshot(
    *,
    action: Any,
    actor: Any = None,
    targets: Any = None,
    base_weight: float = 0.0,
    predicted_weight: Optional[float] = None,
    label: Optional[float] = None,
    residual: Optional[float] = None,
    heuristic_components: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, float]:
    snapshot = {key: 0.0 for key in FEATURE_KEYS}
    snapshot["base_weight"] = _coerce_float(base_weight)
    snapshot["predicted_weight"] = _coerce_float(predicted_weight)
    snapshot["label"] = _coerce_float(label)
    snapshot["residual"] = _coerce_float(residual)

    action_dict = action if isinstance(action, dict) else {}
    snapshot["action_level"] = get_action_level(action_dict)
    snapshot["action_range_ft"] = get_action_range_ft(action_dict)
    snapshot["action_cost_value"] = get_action_cost_value(action_dict)

    roll_type = ""
    if action is not None:
        getter = getattr(action, "getRollType", None)
        if callable(getter):
            try:
                roll_type = str(getter()).lower()
            except Exception:
                roll_type = ""
    snapshot["is_healing"] = 1.0 if "healing" in str(_safe_get(action, "getDamType", lambda: "")()).lower() else 0.0
    snapshot["is_save"] = 1.0 if "save" in roll_type else 0.0
    snapshot["is_to_hit"] = 1.0 if "tohit" in roll_type else 0.0
    snapshot["is_aoe"] = 1.0 if action_dict.get("shape") or action_dict.get("actionRadius") else 0.0
    snapshot["has_linger"] = 1.0 if action_dict.get("lingEffect") or action_dict.get("lingSave") else 0.0

    if heuristic_components:
        snapshot["expected_damage"] = _coerce_float(heuristic_components.get("expected_damage", 0.0))
        snapshot["kill_chance"] = _coerce_float(heuristic_components.get("kill_chance", 0.0))
        snapshot["impact_score"] = _coerce_float(heuristic_components.get("impact_score", 0.0))
        snapshot["ling_save_weight"] = _coerce_float(heuristic_components.get("ling_save_weight", 0.0))
        snapshot["ling_effect_weight"] = _coerce_float(heuristic_components.get("ling_effect_weight", 0.0))
        snapshot["extra_effect_weight"] = _coerce_float(heuristic_components.get("extra_effect_weight", 0.0))

    snapshot.update(_extract_actor_features(actor))
    snapshot.update(_extract_target_features(targets))

    if context:
        for key in FEATURE_KEYS:
            if key in context and context[key] is not None:
                snapshot[key] = _coerce_float(context[key], snapshot.get(key, 0.0))

    if targets:
        snapshot["target_count_valid"] = max(snapshot["target_count_valid"], 1.0)

    return snapshot


def feature_snapshot_to_tensor(snapshot: Dict[str, Any], feature_keys: Sequence[str] = FEATURE_KEYS) -> torch.Tensor:
    values = [_coerce_float(snapshot.get(key, 0.0)) for key in feature_keys]
    return torch.tensor(values, dtype=torch.float32)


def record_to_model_parts(record: Dict[str, Any]) -> Tuple[int, int, torch.Tensor, float, str]:
    family = infer_action_family(record)
    family_idx = ACTION_FAMILY_TO_INDEX.get(family, 2)
    action_name = get_action_name(record)
    name_bucket = stable_hash_bucket(action_name)
    snapshot = record.get("feature_snapshot") or {}
    features = feature_snapshot_to_tensor(snapshot)
    base_weight = _coerce_float(record.get("base_weight", 0.0))
    return family_idx, name_bucket, features, base_weight, action_name


def record_has_label(record: Dict[str, Any]) -> bool:
    return record.get("label") is not None
