# app/models/weapon.py

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field, ConfigDict, field_validator
from .Stats import Ability

class WeaponEquippedProps(BaseModel):
    damage: str
    damageType: str
    weaponStat: Ability

    model_config = ConfigDict(extra="allow")  # allow extra later if you add range/ammo/etc.

    @field_validator("damage", mode="before")
    @classmethod
    def coerce_damage(cls, v: Any) -> str:
        return str(v).strip()

    @field_validator("damageType", mode="before")
    @classmethod
    def normalize_damage_type(cls, v: Any) -> str:
        return str(v).strip().lower()

    @field_validator("weaponStat", mode="before")
    @classmethod
    def normalize_weapon_stat(cls, v: Any) -> Any:
        # accept "str" / "STR"
        if isinstance(v, str):
            return v.strip().upper()
        return v


class Weapon(BaseModel):
    name: str
    properties: WeaponEquippedProps

    model_config = ConfigDict(extra="allow")

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v: Any) -> str:
        return str(v).strip().lower()