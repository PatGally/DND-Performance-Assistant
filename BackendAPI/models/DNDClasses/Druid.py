from pydantic import Field

from BackendAPI.models.Player import Player
from BackendAPI.models.Monster import Monster

class Druid(Player):
    monster : Monster = Field(alias='monster', default_factory=dict)
    wildShaped : bool = Field(alias='wildShaped')
    wildShapeCharges : int = Field(ge=0, le=2, alias="wildShapeCharges")