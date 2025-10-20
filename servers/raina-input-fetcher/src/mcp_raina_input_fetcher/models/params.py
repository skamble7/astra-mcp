from __future__ import annotations
from pydantic import BaseModel, Field, AnyHttpUrl, field_validator

class FetchParams(BaseModel):
    url: AnyHttpUrl = Field(..., description="HTTP(S) endpoint that returns the Raina input JSON.")
    name: str | None = Field(None, description="Optional human-friendly title for the artifact.")
    auth_bearer: str | None = Field(None, description="Optional Bearer token for the request.")

    @field_validator("name", mode="before")
    @classmethod
    def _trim_name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return v.strip() or None