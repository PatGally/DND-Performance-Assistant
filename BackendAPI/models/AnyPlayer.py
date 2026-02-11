from typing import Annotated, Union
from pydantic import Field

from .Sorcerer import Sorcerer

AnyPlayer = Annotated[
    Union[Sorcerer],  # later add Fighter, Cleric, etc.
    Field(discriminator="className"),
]