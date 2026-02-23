from pydantic import Field

from BackendAPI.models import Player

class Barbarian(Player):
    rageCharges : int = Field(ge=0, alias="rageCharges")
    isRaging : bool = Field(alias="isRaging")