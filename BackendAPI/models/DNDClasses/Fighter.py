from pydantic import Field

from BackendAPI.models import Player

class Fighter(Player):
    secondWindCharges : int = Field(ge=0, le=1)
    actionSurgeCharges : int = Field(ge=0, le=1)
    extraAttackAmt : int = Field(ge=0, le=4)