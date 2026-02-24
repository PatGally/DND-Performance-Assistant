from __future__ import annotations

import math
from enum import Enum
from typing import Any, Dict, List, Optional, Union, Annotated

from pydantic import BaseModel, Field, ConfigDict, computed_field, field_validator, model_validator


class Ability(str, Enum):
    STR = "STR"
    DEX = "DEX"
    CON = "CON"
    INT = "INT"
    WIS = "WIS"
    CHA = "CHA"


ABILITY_ORDER: list[Ability] = [
    Ability.STR, Ability.DEX, Ability.CON, Ability.INT, Ability.WIS, Ability.CHA
]


def _mod(score: int) -> int:
    return math.floor((score - 10) / 2)


def _split_csvish(value: Union[str, List[str], None]) -> List[str]:
    """
    Accepts:
      "" / None -> []
      "fire, cold" -> ["fire", "cold"]
      ["Fire", "Cold"] -> ["fire", "cold"]
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip().lower() for x in value if str(x).strip()]
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        parts = [p.strip().lower() for p in s.split(",")]
        return [p for p in parts if p]
    # fallback: coerce single weird value into a 1-item list
    s = str(value).strip().lower()
    return [s] if s else []


def _coerce_int(value: Any, default: int = 0) -> int:
    """
    Accepts ints or numeric strings. Treats "", None as default.
    """
    if value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        s = value.strip()
        if s == "":
            return default
        # allow "42", "042", etc.
        return int(s)
    return int(value)


class Stats(BaseModel):
    """
    Base Stats model: Player/Monster can inherit.
    Accepts your legacy schema and normalizes everything into consistent shapes.
    """
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    # --- ability scores ---
    stat_array: Dict[Ability, int] = Field(alias="statArray")

    # --- saves ---
    save_profs: Optional[Dict[Ability, int]] = Field(default=None, alias="saveProfs")

    # --- damage/con immunities/resists/vulns (input can be str or list; output ALWAYS list[str]) ---
    dam_resists: List[str] = Field(default_factory=list, alias="damResists")
    dam_immunes: List[str] = Field(default_factory=list, alias="damImmunes")
    dam_vulns: List[str] = Field(default_factory=list, alias="damVulns")
    con_immunes: List[str] = Field(default_factory=list, alias="conImmunes")

    # --- status/conditions ---
    active_conditions: List[str] = Field(default_factory=list, alias="activeConditions")
    active_status_effects: List[Dict[str, Any]] = Field(default_factory=list, alias="activeStatusEffects")

    # --- HP (JSON strings ok; internal ints) ---
    hp: int = Field(default=0, alias="hp")
    max_hp: int = Field(default=0, alias="maxHP")
    position : List[int] = Field(min_length=2, max_length=2, default=[0, 0], alias="position")
    cid : str = Field(alias="cid")

    @computed_field
    @property
    def modifiers(self) -> Dict[Ability, int]:
        return {ability: _mod(score) for ability, score in self.stat_array.items()}

    # ---------- model-wide normalization ----------
    @model_validator(mode="before")
    @classmethod
    def normalize_inputs(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)

        # Build stats from statArray if needed
        if "stats" not in d and "statArray" in d: #Monsters
            arr = d.get("statArray")
        elif "stats" in d and "statArray" in d["stats"]:
            arr = d["stats"].get("statArray")
        else:
            raise ValueError("No statArray!")
        if not isinstance(arr, dict) or len(arr.keys()) != 6:
            raise ValueError("statArray must be a list of exactly 6 items: [STR, DEX, CON, INT, WIS, CHA]")
        d["statArray"] = {ABILITY_ORDER[i]: int(arr[stat]) for i, stat in enumerate(arr.keys())}

        # Convert saveProfs list-of-6 to dict
        sp = d.get("saveProfs")
        if isinstance(sp, list):
            if len(sp) != 6:
                raise ValueError("saveProfs must be a list of exactly 6 items: [STR, DEX, CON, INT, WIS, CHA]")
            d["saveProfs"] = {ABILITY_ORDER[i]: int(sp[i]) for i in range(6)}
        elif isinstance(sp, dict):
            d["saveProfs"] = {Ability(k): int(v) for k, v in sp.items()}

        return d

    # ---------- per-field normalization ----------
    @field_validator("dam_resists", "dam_immunes", "dam_vulns", "con_immunes", mode="before")
    @classmethod
    def normalize_csv_or_list_fields(cls, v):
        return _split_csvish(v)

    @field_validator("active_conditions", mode="before")
    @classmethod
    def normalize_active_conditions(cls, v):
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("activeConditions must be a list of strings")
        return [str(x).strip().lower() for x in v if str(x).strip()]

    @field_validator("active_status_effects", mode="before")
    @classmethod
    def normalize_active_status_effects(cls, v):
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("activeStatusEffects must be a list of dicts")
        out: List[Dict[str, Any]] = []
        for item in v:
            if not isinstance(item, dict):
                raise ValueError("Each activeStatusEffect must be an object/dict")
            # Optional normalization: lowercase "name" if present
            if "name" in item and isinstance(item["name"], str):
                item = dict(item)
                item["name"] = item["name"].lower()
            out.append(item)
        return out

    @field_validator("hp", "max_hp", mode="before")
    @classmethod
    def coerce_hp_fields(cls, v):
        return _coerce_int(v, default=0)

    @model_validator(mode="after")
    def default_save_profs_if_missing(self):
        # same behavior as your original: if absent, default to modifiers
        if self.save_profs is None:
            self.save_profs = dict(self.modifiers)
        return self