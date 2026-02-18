from __future__ import annotations

from pydantic import Field
from BackendAPI.models.Player import Player

class Cleric(Player):
    turnUndeadCharges : int = Field(le=1, ge=0, alias="turnUndeadCharges")
    destroyUndeadCap : int = Field(le=4, ge=0, alias="destroyUndeadCap")