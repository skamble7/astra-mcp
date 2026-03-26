# models/params.py
from __future__ import annotations
from pydantic import BaseModel, Field, field_validator


class GenerateGuidanceParams(BaseModel):
    workspace_id: str = Field(
        ...,
        description="Workspace ID whose artifacts are the source context for the guidance document.",
    )

    @field_validator("workspace_id", mode="before")
    @classmethod
    def _strip_ws_id(cls, v: str) -> str:
        return (v or "").strip()
