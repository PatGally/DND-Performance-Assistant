from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Union, Any

class OriginPx(BaseModel):
    x: int
    y: int

class NaturalSizePx(BaseModel):
    w: int
    h: int

class MapImage(BaseModel):
    mapLink: str
    sourceType: str
    originPx: OriginPx
    naturalSizePx: NaturalSizePx

class CellBounds(BaseModel):
    cols: int
    rows: int

class Grid(BaseModel):
    cellBounds: CellBounds
    cellSizePx: int

class CreatureToken(BaseModel):
    cid: str
    token_image: str

class Shape(BaseModel):
    type: str
    radiusCells: int

class Anchor(BaseModel):
    x: int
    y: int

class AoeToken(BaseModel):
    tid: str
    cid: str
    resultID: int
    name: str
    shape: Shape
    anchor: Anchor
    timing: str

class Layers(BaseModel):
    creatureTokens: List[CreatureToken] = Field(default_factory=list)
    aoeTokens: List[AoeToken] = Field(default_factory=list)

class MapData(BaseModel):
    map: MapImage
    grid: Grid
    layers: Layers