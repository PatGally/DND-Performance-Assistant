# app/models/player.py
from __future__ import annotations

from typing import Any, Optional, List
from pydantic import BaseModel, Field, ConfigDict

from .Stats import Stats
from .Weapon import Weapon
from .Spell import Spell


class PlayerStats(Stats):
    # These fields exist inside stats in player_list.json
    name: str
    level: int = Field(alias="level")
    ac: int
    hp: int
    class_: str = Field(alias="class")

    # Present on some players (e.g., PlayerOne) :contentReference[oaicite:4]{index=4}
    # Looks like a list of pairs: [["4","4"], ["3","3"], ...]
    spellSlots: Optional[List[List[int]]] = None
    model_config = ConfigDict(populate_by_name=True)

class Player(BaseModel):
    stats: PlayerStats
    spells: List[Spell] = Field(default_factory=list)
    weapons: List[Weapon] = Field(default_factory=list)