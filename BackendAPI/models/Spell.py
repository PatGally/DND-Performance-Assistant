# app/models/spell.py

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

class RollType(str, Enum):
    save = "save"
    toHit = "toHit"
    autoHit = "autoHit"
    onHit = "onHit"


class SpellRolls(BaseModel):
    rollType: RollType
    saveType: str = "none"          # in JSON you also use "none"
    halfSave: bool = False
    damage: str = ""                # e.g. "4d4" or ""
    damageMod: str = ""             # "0", "", "spellMod", "1", etc.

    model_config = ConfigDict(extra="allow")


class SpellTargeting(BaseModel):
    # spell_list.json sometimes has extra keys like targetType
    targetType: Optional[str] = None  # seen in spell_list.json :contentReference[oaicite:3]{index=3}

    self: bool = False
    number: int = 1
    rolls: SpellRolls

    damType: list[str] = Field(default_factory=list)

    # These are frequently null in player_list.json :contentReference[oaicite:4]{index=4}
    conditions: list[str] = Field(default_factory=list)

    # Variable schema; keep loose. Also sometimes null, and sometimes inconsistent.
    statusEffect: list[dict[str, Any]] = Field(default_factory=list)

    # These can be {}, null, or complex nested dicts (e.g. Ensnaring Strike) :contentReference[oaicite:5]{index=5}
    lingEffect: dict[str, Any] = Field(default_factory=dict)
    extraEffect: dict[str, Any] = Field(default_factory=dict)
    lingSave: dict[str, Any] = Field(default_factory=dict)

    scaling: str = ""
    specialNotes: list[Any] = Field(default_factory=list)
    actionCost: str = "action"

    model_config = ConfigDict(extra="allow")

    @field_validator("number", mode="before")
    @classmethod
    def coerce_number(cls, v: Any) -> int:
        # player_list.json uses strings like "-1" :contentReference[oaicite:6]{index=6}
        if v is None or v == "":
            return 0
        if isinstance(v, int):
            return v
        return int(str(v).strip())

    @field_validator("conditions", "statusEffect", "specialNotes", mode="before")
    @classmethod
    def null_to_empty_list(cls, v: Any) -> list:
        # normalize null -> []
        if v is None:
            return []
        # handle the occasional "statusEffect": {} mistake by treating it as empty
        if isinstance(v, dict):
            return []
        return v

    @field_validator("lingEffect", "extraEffect", "lingSave", mode="before")
    @classmethod
    def null_to_empty_dict(cls, v: Any) -> dict:
        # normalize null -> {}
        if v is None:
            return {}
        # if something weird slips in, try to keep it dict-like
        if isinstance(v, dict):
            return v
        return {}  # safest fallback


class Spell(BaseModel):
    spellname: str
    level: int = Field(alias="level")
    targeting: list[SpellTargeting] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")

    @field_validator("level", mode="before")
    @classmethod
    def coerce_level(cls, v: Any) -> int:
        # player_list.json uses "2" as a string :contentReference[oaicite:7]{index=7}
        if isinstance(v, int):
            return v
        return int(str(v).strip())

    @field_validator("spellname", mode="before")
    @classmethod
    def normalize_spellname(cls, v: Any) -> str:
        return str(v).strip()