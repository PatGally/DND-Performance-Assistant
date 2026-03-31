from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class StatBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    STR: Optional[int] = None
    DEX: Optional[int] = None
    CON: Optional[int] = None
    INT: Optional[int] = None
    WIS: Optional[int] = None
    CHA: Optional[int] = None


class AffectedCreature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cid: str

    statArray: Optional[StatBlock] = None
    saveProfs: Optional[StatBlock] = None
    modifiers: Optional[StatBlock] = None

    damResists: Optional[List[str]] = None
    damImmunes: Optional[List[str]] = None
    damVulns: Optional[List[str]] = None
    conImmunes: Optional[List[str]] = None

    activeConditions: Optional[List[str]] = None
    activeStatusEffects: Optional[List[dict]] = None

    hp: Optional[int] = None
    position: Optional[List[List[int]]] = None
    ac: Optional[int] = None
    lResists: Optional[int] = None
    enemy: Optional[bool] = None

    spellSlots: Optional[List[List[str]]] = None


class AffectedCreaturesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    affectedCreatures: List[AffectedCreature]