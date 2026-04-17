from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, ConfigDict, field_validator

from .ActionRequest import ActionRequest

class PreTurnRequest(ActionRequest):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    preTurnMeta: Literal["lingeffect", "lingsave"] = Field(alias="preTurnMeta")

    @field_validator("actionType", mode="before")
    @classmethod
    def normalize_action_type(cls, v: Any) -> str:
        s = str(v).strip()
        return s or "PreTurn"