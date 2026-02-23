from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, ConfigDict, computed_field, model_validator

from BackendAPI.models.Player import Player

class MetaMagic(BaseModel):
    name: str
    cost: str
    ability: str
    numTarget: str
    attribute: List[str] = Field(default_factory=list)
    specialNotes: List[str] = Field(default_factory=list)


SORCERER_METAMAGIC_CATALOG: List[MetaMagic] = [ #read only
    MetaMagic(name="Careful Spell", cost="1", ability="autosuccess", numTarget="CHA", attribute=["ALL save"]),
    MetaMagic(name="Distant Spell", cost="1", ability="range *2", numTarget="1", attribute=["attack rolls for"]),
    MetaMagic(name="Empowered Spell", cost="1", ability="reroll", numTarget="CHA", attribute=["ALL damage"]),
    MetaMagic(name="Heightened Spell", cost="3", ability="disadvantage", numTarget="1", attribute=["ALL save"]),
    MetaMagic(name="Quickened Spell", cost="2", ability="action -> bonus action", numTarget="1", attribute=["ALL spells"]),
    MetaMagic(name="Seeking Spell", cost="2", ability="reroll", numTarget="1", attribute=["ALL attack rolls"]),
    MetaMagic(name="Transmuted Spell", cost="1", ability="damType -> damType", numTarget="1", attribute=["ALL spells"]),
    MetaMagic(name="Twinned Spell", cost="spellLvl", ability="numTarget *2", numTarget="1",
              attribute=["ALL spells"], specialNotes=["numTarget=1 required"]),
]


class Sorcerer(Player):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    sorceryPoints: int = Field(default=-1, alias="sorceryPoints")
    chosenMetaMagics: List[MetaMagic] = Field(default_factory=list, alias="chosenMetaMagics")

    @computed_field
    @property
    def metamagics(self) -> List[MetaMagic]:
        return SORCERER_METAMAGIC_CATALOG

    @model_validator(mode="after")
    def fill_defaults(self):
        # Compute sorceryPoints if not provided
        if self.sorceryPoints == -1:
            self.sorceryPoints = self.stats.level if self.stats.level > 1 else 0
        return self