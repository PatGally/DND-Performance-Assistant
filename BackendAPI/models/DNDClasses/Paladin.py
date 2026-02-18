from pydantic import Field

from BackendAPI.models import Player

class Paladin(Player):
    layOnHandsPool : int = Field(ge=0, le=100, alias='layOnHandsPool')