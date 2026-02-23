from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
def _split_csvish(value: Any) -> List[str]:
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
        return [p.strip().lower() for p in s.split(",") if p.strip()]
    s = str(value).strip().lower()
    return [s] if s else []

class ActionRollsModel(BaseModel):
    """
    Matches your action JSON "rolls" payload.
    Normalizes: damMod (current JSON) vs damageMod (legacy toDict()).
    """
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    roll_type: str = Field(default="", alias="rollType")
    save_type: str = Field(default="", alias="saveType")
    half_save: bool = Field(default=False, alias="halfSave")

    save_dc: Optional[int] = Field(default=None, alias="saveDC")
    damage: str = Field(default="")
    attack_bonus: Optional[int] = Field(default=0, alias="attackBonus")

    dam_mod: Optional[int] = Field(default=None, alias="damMod")

    @model_validator(mode="before")
    @classmethod
    def normalize_rolls_keys(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)

        # accept legacy "damageMod" as an alias for current "damMod"
        if "damMod" not in d and "damageMod" in d:
            d["damMod"] = d.get("damageMod")

        return d

    @field_validator("save_dc", "dam_mod", "attack_bonus", mode="before")
    @classmethod
    def coerce_int_fields(cls, v: Any):
        return _coerce_int(v)

    @field_validator("half_save", mode="before")
    @classmethod
    def coerce_half_save(cls, v: Any):
        return _coerce_bool(v)


class LingSaveModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    save_type: str = Field(default="", alias="saveType")
    save_dc: Optional[int] = Field(default=None, alias="saveDC")
    timing: str = Field(default="")

    @field_validator("save_dc", mode="before")
    @classmethod
    def coerce_save_dc(cls, v: Any):
        return _coerce_int(v)


class MonAction(BaseModel):
    """
    Pydantic replacement for your legacy MonAction class.
    Designed to parse monster_list_NEW.json action objects,
    while staying compatible with your legacy naming.
    """
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    name: str
    desc: str = ""

    action_range: str = Field(default="", alias="actionRange")
    num_target: int = Field(default=0, alias="numTarget")
    shape: str = ""

    rolls: ActionRollsModel = Field(default_factory=ActionRollsModel)

    dam_type: List[str] = Field(default_factory=list, alias="damType")
    conditions: List[str] = Field(default_factory=list)

    status_effect: Optional[list[dict[str, Any]]] = None

    ling_effect: Optional[list[dict[str, Any]]] = None
    extra_effect: Optional[list[dict[str, Any]]] = None

    # In your data this can be {} or a structured object
    ling_save: Optional[list[dict[str, Any]]] = None

    action_cost: str = Field(default="action", alias="actionCost")
    recharge: Union[str, List[str]] = Field(default="", alias="recharge")

    special_notes: Optional[list[str]] = None
    extra_damage: List[Any] = Field(default_factory=list, alias="extraDamage")

    @field_validator("dam_type", "conditions", mode="before")
    @classmethod
    def normalize_str_list_fields(cls, v: Any):
        return _split_csvish(v)

    @field_validator("ling_save", "extra_effect", "ling_effect", mode="before")
    @classmethod
    def normalize_dict_fields(cls, v : Any):
        if v is None:
            return {}
        return v

    @field_validator("special_notes", "status_effect", "conditions", "dam_type", "extra_damage", mode="before")
    @classmethod
    def normalize_list_fields(cls, v : Any):
        if v is None:
            return []
        return v

    @field_validator("num_target", mode="before")
    @classmethod
    def coerce_num_target(cls, v: Any):
        if v is None:
            return 0
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.strip() == "":
            return 0
        return int(v)