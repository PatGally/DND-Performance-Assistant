from __future__ import annotations

from datetime import datetime, time
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, ConfigDict, field_validator

class Outcome(BaseModel):
    rollResults : List[str] = Field(alias="rollResults")
    diceResults : List[int] = Field(alias="diceResults")

class ExtraOutcome(BaseModel):
    extraRollResults : List[str] = Field(alias="extraRollResults")
    extraDiceResults : List[int] = Field(alias="extraDiceResults")

class AoeTokenPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str
    positioning: List[List[int]]
    token_image: str
    resultID: str
    cid: str
    anchor: List[int]
    timing: str
    shape: str

    @field_validator("positioning", mode="before")
    @classmethod
    def validate_positioning(cls, v: Any) -> List[List[int]]:
        if not isinstance(v, list):
            raise ValueError("positioning must be a list of [x, y] coords")
        out: List[List[int]] = []
        for item in v:
            if (
                not isinstance(item, list)
                or len(item) != 2
                or not all(isinstance(n, int) for n in item)
            ):
                raise ValueError("each positioning entry must be [int, int]")
            out.append(item)
        return out

    @field_validator("anchor", mode="before")
    @classmethod
    def validate_anchor(cls, v: Any) -> List[int]:
        if isinstance(v, dict):
            v = [v.get("x"), v.get("y")]

        if (
                not isinstance(v, list)
                or len(v) != 2
                or not all(isinstance(n, int) for n in v)
        ):
            raise ValueError("anchor must be [int, int]")

        return v


    @field_validator("name", "token_image", "resultID", "cid", "timing", "shape", mode="before")
    @classmethod
    def strip_strings(cls, v: Any) -> str:
        return str(v).strip()


class ActionRequest(BaseModel):

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    resultID: str
    actor: str
    action: str
    actionType: str

    # These are often numeric; allow string input and normalize to float.
    actionProb: float = Field(..., ge=0.0, le=1.0)
    actionEDam: float
    actionImpact: float
    actionRanking : int
    base_weight : float
    ml_weight : Optional[float] = None
    useML : bool
    final_weight : float
    candidateCount : int

    targets: List[str] = Field(default_factory=list)

    conditions: List[str] = Field(default_factory=list)
    statusEffects: List[Dict[str, Any]] = Field(default_factory=list)

    outcome: Outcome
    extraOutcome: ExtraOutcome

    token : Optional[AoeTokenPayload] = None

    timestamp: time

    @field_validator("actor", "action", "actionType", mode="before")
    @classmethod
    def strip_strings(cls, v: Any) -> str:
        return str(v).strip()

    @field_validator("actionProb", "actionEDam", "actionImpact", mode="before")
    @classmethod
    def coerce_float(cls, v: Any) -> float:
        # Accept numbers or numeric strings
        if v is None or v == "":
            return 0.0
        if isinstance(v, (int, float)):
            return float(v)
        return float(str(v).strip())

    @field_validator("targets", mode="before")
    @classmethod
    def normalize_targets(cls, v: Any) -> List[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("targets must be a list of strings")
        return [str(x).strip() for x in v if str(x).strip()]

    @field_validator("conditions", mode="before")
    @classmethod
    def normalize_conditions(cls, v: Any) -> List[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("conditions must be a list of strings")
        return [str(x).strip().lower() for x in v if str(x).strip()]

    @field_validator("statusEffects", mode="before")
    @classmethod
    def normalize_status_effects(cls, v: Any) -> List[Dict[str, Any]]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("statusEffects must be a list of dicts")
        out: List[Dict[str, Any]] = []
        for item in v:
            if not isinstance(item, dict):
                raise ValueError("each statuseffect must be a dict/object")

            if "name" in item and isinstance(item["name"], str):
                item = dict(item)
                item["name"] = item["name"].strip().lower()
            out.append(item)
        return out

    @field_validator("timestamp", mode="before")
    @classmethod
    def parse_timestamp(cls, v: Any) -> time:
        if isinstance(v, time):
            return v
        if isinstance(v, str):
            s = v.strip()
            # preferred format: "%H:%M:%S"
            try:
                return datetime.strptime(s, "%H:%M:%S").time()
            except ValueError:
                pass
            # fallback: ISO-ish
            try:
                return datetime.fromisoformat(s).time()
            except ValueError:
                pass
        raise ValueError("timestamp must be 'HH:MM:SS' (e.g., '14:33:07')")

