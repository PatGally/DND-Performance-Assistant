from typing import List
from pydantic import Field
from BackendAPI.models.Player import Player
from BackendAPI.models.Spell import Spell

class Bard(Player):
    bardicCharges : int = Field(default=0, ge=-5,le=5, alias='bardicCharges')
    bardicDieType : int = Field(default=6, ge=6, le=12, alias="bardicDieType")
    magicalSecrets : List[Spell] = Field(min_length=0, max_length=5, alias='magicalSecrets')