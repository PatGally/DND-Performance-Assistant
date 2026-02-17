from __future__ import annotations

from typing import Any, List
from pydantic import BaseModel, Field, ConfigDict

# Adjust these imports to match your project structure
from .Player import Player
from .Monster import Monster

class InitiativeEntry(BaseModel):
    name: str
    iValue: int
    turnType: str  # "Player" | "Monster" in your JSON
    currentTurn: bool = False
    actionResource: int = 1
    bonusActionResource: int = 1

    model_config = ConfigDict(extra="ignore")


class Encounter(BaseModel):
    """
    Pydantic version of Encounter as stored in encounter_list.json.

    Notes:
    - 'players' uses Player pydantic
    - 'monsters' uses Monster pydantic
    - 'results' is intentionally flexible because it is nested and can vary
    """
    name: str
    date: str  # keep as str; you can switch to datetime/date later if you want

    eid: str
    maplink: str = Field(alias="maplink")
    completed: bool = False

    monsters: List[Monster] = Field(default_factory=list)
    players: List[Player] = Field(default_factory=list)

    # results is usually: list[resultSet], where each resultSet may be:
    # - a list[dict]  (your sample)
    # - or a single dict
    results: List[Any] = Field(default_factory=list)

    initiative: List[InitiativeEntry] = Field(default_factory=list)

    model_config = ConfigDict(
        populate_by_name=True,
        extra="allow",  # encounter JSON may grow later; don't 500 on extra keys
    )