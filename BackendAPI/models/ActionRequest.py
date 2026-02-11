from __future__ import annotations

from datetime import datetime, time
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, ConfigDict, field_validator


class ActionRequest(BaseModel):
    """
    Payload received by the backend to apply/simulate a chosen action on encounter state.
    Mirrors the entry dict created client-side.
    """
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    resultID: int = Field(..., ge=1)  # random.randint(1, 9999999999)
    actor: str
    action: str
    actionType: str

    # These are often numeric; allow string input and normalize to float.
    actionProb: float = Field(..., ge=0.0, le=1.0)
    actionEDam: float
    actionImpact: float

    targets: List[str] = Field(default_factory=list)
    targetCRs: List[Union[int, float, str]] = Field(default_factory=list)  # CR could be int/float/string

    conditions: List[str] = Field(default_factory=list)
    statuseffects: List[Dict[str, Any]] = Field(default_factory=list)

    outcome: Dict[str, List[str]] = Field(default_factory=dict)
    extraOutcome: Optional[Dict[str, List[str]]] = Field(default_factory=dict)

    # Sender uses "%H:%M:%S"
    timestamp: time

    # -------------------
    # Validators
    # -------------------

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

    @field_validator("targetCRs", mode="before")
    @classmethod
    def normalize_target_crs(cls, v: Any) -> List[Union[int, float, str]]:
        """
        Keep this flexible:
        - Monsters might have CR like '1/4' or '2'
        - Players might have level as int
        We'll normalize numeric strings to int/float when possible, otherwise keep the string.
        """
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("targetCRs must be a list")
        out: List[Union[int, float, str]] = []
        for item in v:
            if item is None or item == "":
                continue
            if isinstance(item, (int, float)):
                out.append(item)
                continue
            s = str(item).strip()
            # try int
            try:
                out.append(int(s))
                continue
            except ValueError:
                pass
            # try float
            try:
                out.append(float(s))
                continue
            except ValueError:
                pass
            # keep string (e.g., "1/4")
            out.append(s)
        return out

    @field_validator("conditions", mode="before")
    @classmethod
    def normalize_conditions(cls, v: Any) -> List[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("conditions must be a list of strings")
        return [str(x).strip().lower() for x in v if str(x).strip()]

    @field_validator("statuseffects", mode="before")
    @classmethod
    def normalize_status_effects(cls, v: Any) -> List[Dict[str, Any]]:
        if v is None:
            return []
        if not isinstance(v, list):
            raise ValueError("statuseffects must be a list of dicts")
        out: List[Dict[str, Any]] = []
        for item in v:
            if not isinstance(item, dict):
                raise ValueError("each statuseffect must be a dict/object")
            # optional normalization: lowercase name if present
            if "name" in item and isinstance(item["name"], str):
                item = dict(item)
                item["name"] = item["name"].strip().lower()
            out.append(item)
        return out

    @field_validator("timestamp", mode="before")
    @classmethod
    def parse_timestamp(cls, v: Any) -> time:
        """
        Accepts:
          - datetime.time already
          - "HH:MM:SS" string (your sender format)
          - ISO datetime string (fallback)
        """
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