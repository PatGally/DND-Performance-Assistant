from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .Stats import Stats
from .MonAction import MonAction


def _coerce_int_or_none(v: Any) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return None
        return int(s)
    return int(v)
def _coerce_int(v: Any, default: int = 0) -> int:
    if v is None:
        return default
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return default
        return int(s)
    return int(v)
def _coerce_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in {"true", "t", "1", "yes", "y"}:
            return True
        if s in {"false", "f", "0", "no", "n", ""}:
            return False
    return bool(v)


class LegendaryActionModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: str
    desc: str = ""
    cost: int = 1
    action: Optional[MonAction] = None


class SpellInfoModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    type: str = ""
    dc: Optional[int] = Field(default=None, alias="DC")
    attack_roll: Optional[int] = Field(default=None, alias="attackRoll")

    spells: List[Dict[str, Any]] = Field(default_factory=list)
    spell_slots: List[List[str | int]] = Field(default_factory=list, alias="spellSlots")

    @field_validator("dc", "attack_roll", mode="before")
    @classmethod
    def coerce_ints(cls, v: Any):
        return _coerce_int_or_none(v)


class MultiattackModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: str = ""
    total: Optional[int] = None
    split: List[Dict[str, Any]] = Field(default_factory=list)

    @field_validator("total", mode="before")
    @classmethod
    def coerce_total(cls, v: Any):
        return _coerce_int_or_none(v)


class Monster(Stats):
    """
    Pydantic replacement for legacy Monster(Stats).

    Normalizes:
      - hit_points -> hp/maxHP
      - AC -> ac
      - activeCons -> activeConditions (legacy -> Stats)
      - legActions null -> []
    """
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: str
    cr: str  # keep string: "1/4" etc.
    creature_type: str = Field(alias="creatureType")
    ac: int = Field(default=0, alias="ac")
    l_resists: int = Field(default=0, alias="lResists")
    magic_resist: bool = Field(default=False, alias="magicResist")
    lair_action: bool = Field(default=False, alias="lairAction")
    enemy: bool = Field(default=False)
    size : str = Field(alias="size")
    movement : int = Field(alias="movement")


    actions: List[MonAction] = Field(default_factory=list)

    leg_actions: List[LegendaryActionModel] = Field(default_factory=list, alias="legActions")
    spell_info: Optional[SpellInfoModel] = Field(default=None, alias="spellInfo")
    multiattack: Optional[MultiattackModel] = Field(default=None)

    @model_validator(mode="before")
    @classmethod
    def normalize_monster_inputs(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)

        # hp fields: JSON uses hit_points
        if "hp" not in d and "hit_points" in d:
            d["hp"] = d.get("hit_points")
        if "maxHP" not in d:
            # if no explicit max, set it equal to hp/hit_points
            if "max_hp" in d:
                d["maxHP"] = d.get("max_hp")
            elif "hit_points" in d:
                d["maxHP"] = d.get("hit_points")

        # AC sometimes comes as "AC"
        if "ac" not in d and "AC" in d:
            d["ac"] = d.get("AC")

        # legacy Monster dict used activeCons; Stats expects activeConditions
        if "activeConditions" not in d and "activeCons" in d:
            d["activeConditions"] = d.get("activeCons")

        # legActions can be null
        if d.get("legActions") is None:
            d["legActions"] = []

        # actions can be missing/null
        if d.get("actions") is None:
            d["actions"] = []

        return d

    @field_validator("ac", "l_resists", mode="before")
    @classmethod
    def coerce_int_fields(cls, v: Any, info):
        # both AC and lResists show up as strings in some JSON
        return _coerce_int(v, default=0)

    @field_validator("magic_resist", "lair_action", "enemy", mode="before")
    @classmethod
    def coerce_bool_fields(cls, v: Any):
        return _coerce_bool(v)

    @field_validator("spell_info", "multiattack", mode="before")
    @classmethod
    def normalize_dict_fields(cls, v:Any):
        if v is None:
            return {}
        return v