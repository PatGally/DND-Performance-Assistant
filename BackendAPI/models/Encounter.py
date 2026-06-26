from __future__ import annotations

from typing import Any, List, Union, Optional
from pydantic import BaseModel, Field, ConfigDict
from .MapData import MapData
from .DNDClasses import Fighter, Barbarian, Bard, Cleric, Druid, Paladin, Sorcerer
from .Player import Player
from .Monster import Monster

AnyPlayer = Union[
    Fighter, Barbarian, Bard, Cleric, Druid, Paladin, Sorcerer,
    Player,  # keep Player last
]

class InitiativeEntry(BaseModel):
    cid: str = ""
    name: str
    iValue: int
    turnType: str  # "Player" | "Monster"
    currentTurn: bool = False
    actionResource: int = 1
    bonusActionResource: int = 1
    movementResource: int = 0
    startingAnchor: List[List[int]] = Field(min_length=1, alias="startingAnchor")

    model_config = ConfigDict(extra="ignore")


class Encounter(BaseModel):
    """
    Pydantic version of Encounter including MapData for Mongo storage.
    """
    name: str
    date: str
    eid: str
    mapdata: Optional[MapData] = None  # Added MapData field
    completed: bool = False

    monsters: List[Monster] = Field(default_factory=list)
    players: List[Union[AnyPlayer, Player]] = Field(default_factory=list)
    results: List[Any] = Field(default_factory=list)
    initiative: List[InitiativeEntry] = Field(default_factory=list)

    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid"  # allows extra fields for future-proofing
    )
